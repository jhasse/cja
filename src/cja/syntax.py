import operator
import os
import platform
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .parser import Command
from .utils import (
    UNDEFINED_VAR_SENTINEL,
    cmake_regex_to_python,
    compare_versions,
    is_off,
    is_on,
)

# Commands built into CMake (cmake --help-command-list), documented at
# https://cmake.org/cmake/help/latest/command/<name>.html
BUILTIN_COMMANDS = frozenset(
    {
        "add_compile_definitions", "add_compile_options", "add_custom_command",
        "add_custom_target", "add_definitions", "add_dependencies", "add_executable",
        "add_library", "add_link_options", "add_subdirectory", "add_test",
        "aux_source_directory", "block", "break", "build_command", "build_name",
        "cmake_file_api", "cmake_host_system_information", "cmake_instrumentation",
        "cmake_language", "cmake_minimum_required", "cmake_parse_arguments",
        "cmake_path", "cmake_pkg_config", "cmake_policy", "configure_file", "continue",
        "create_test_sourcelist", "ctest_build", "ctest_configure", "ctest_coverage",
        "ctest_empty_binary_directory", "ctest_memcheck", "ctest_read_custom_files",
        "ctest_run_script", "ctest_sleep", "ctest_start", "ctest_submit", "ctest_test",
        "ctest_update", "ctest_upload", "define_property", "else", "elseif",
        "enable_language", "enable_testing", "endblock", "endforeach", "endfunction",
        "endif", "endmacro", "endwhile", "exec_program", "execute_process", "export",
        "export_library_dependencies", "file", "find_file", "find_library",
        "find_package", "find_path", "find_program", "fltk_wrap_ui", "foreach",
        "function", "get_cmake_property", "get_directory_property",
        "get_filename_component", "get_property", "get_source_file_property",
        "get_target_property", "get_test_property", "if", "include",
        "include_directories", "include_external_msproject", "include_guard",
        "include_regular_expression", "install", "install_files", "install_programs",
        "install_targets", "link_directories", "link_libraries", "list", "load_cache",
        "load_command", "macro", "make_directory", "mark_as_advanced", "math",
        "message", "option", "output_required_files", "project", "qt_wrap_cpp",
        "qt_wrap_ui", "remove", "remove_definitions", "return", "separate_arguments",
        "set", "set_directory_properties", "set_property",
        "set_source_files_properties", "set_target_properties", "set_tests_properties",
        "site_name", "source_group", "string", "subdir_depends", "subdirs",
        "target_compile_definitions", "target_compile_features",
        "target_compile_options", "target_include_directories",
        "target_link_directories", "target_link_libraries", "target_link_options",
        "target_precompile_headers", "target_sources", "try_compile", "try_run",
        "unset", "use_mangled_mesa", "utility_source", "variable_requires",
        "variable_watch", "while", "write_file",
    }
)


@dataclass
class FetchContentInfo:
    """Information for FetchContent_Declare."""

    name: str
    args: list[str]


@dataclass
class FunctionDef:
    """A CMake function definition."""

    name: str
    params: list[str]
    body: list  # list[Command] - forward reference
    defining_file: Path


@dataclass
class MacroDef:
    """A CMake macro definition."""

    name: str
    params: list[str]
    body: list  # list[Command] - forward reference


@dataclass
class SourceFileProperties:
    """Properties for a source file."""

    object_depends: list[str] = field(default_factory=list)
    include_directories: list[str] = field(default_factory=list)
    compile_definitions: list[str] = field(default_factory=list)
    compile_options: list[str] = field(default_factory=list)
    compile_flags: str = ""  # Legacy COMPILE_FLAGS, a command-line string
    skip_precompile_headers: bool = False


@dataclass
class Test:
    """A test definition."""

    name: str
    command: list[str]
    working_directory: str | None = None
    properties: dict[str, str] = field(default_factory=dict)


# The newest policy of CMake 3.28, which cja reports as CMAKE_VERSION.
_NEWEST_POLICY = 155

# EQUAL, LESS, ... compare numbers, STREQUAL, STRLESS, ... strings and
# VERSION_EQUAL, VERSION_LESS, ... versions.
_COMPARISONS: dict[str, Callable[[Any, Any], bool]] = {
    "EQUAL": operator.eq,
    "LESS": operator.lt,
    "LESS_EQUAL": operator.le,
    "GREATER": operator.gt,
    "GREATER_EQUAL": operator.ge,
}
_BINARY_OPERATORS = {
    "MATCHES",
    "IN_LIST",
    "IS_NEWER_THAN",
    "PATH_EQUAL",
    *_COMPARISONS,
    *(f"STR{op}" for op in _COMPARISONS),
    *(f"VERSION_{op}" for op in _COMPARISONS),
}

# Like in CMake, an empty path is no file.
_FILE_TESTS: dict[str, Callable[[str], bool]] = {
    "EXISTS": os.path.exists,
    "IS_DIRECTORY": os.path.isdir,
    "IS_SYMLINK": os.path.islink,
    "IS_READABLE": lambda path: os.access(path, os.R_OK),
    "IS_WRITABLE": lambda path: os.access(path, os.W_OK),
    "IS_EXECUTABLE": lambda path: os.access(path, os.X_OK),
}
_UNARY_OPERATORS = {
    "DEFINED",
    "COMMAND",
    "TARGET",
    "TEST",
    "POLICY",
    "IS_ABSOLUTE",
    *_FILE_TESTS,
}


def _is_absolute(path: str) -> bool:
    """Like CMake's IS_ABSOLUTE, which follows the rules of the host."""
    if platform.system() == "Windows":
        return len(path) >= 2 and (path[1] == ":" or path[0] in "/\\")
    return path.startswith(("/", "~"))


def _is_newer_than(file1: str, file2: str) -> bool:
    """Like CMake, also true for equal times or if a file doesn't exist."""
    try:
        return os.stat(file1).st_mtime_ns >= os.stat(file2).st_mtime_ns
    except OSError:
        return True


def _path_components(path: str) -> list[str]:
    """Split a path for PATH_EQUAL, where repeated separators count as one."""
    if platform.system() == "Windows":
        path = path.replace("\\", "/")
    parts = [part for part in path.split("/") if part]
    if path.endswith("/") and parts:
        parts.append("")  # A trailing separator ends in an empty component
    return ["/" if path.startswith("/") else "", *parts]

# The longest prefixes sscanf("%lg") reads as a number.
_SPECIAL_NUMBER_RE = re.compile(
    r"[+-]?(?:inf(?:i(?:n(?:i(?:ty?)?)?)?)?|nan)", re.IGNORECASE
)
_HEX_NUMBER_RE = re.compile(
    r"[+-]?0[xX](?P<mantissa>[0-9a-fA-F]*\.?[0-9a-fA-F]*)(?:[pP](?P<exp>[+-]?[0-9]*))?"
)
_DECIMAL_NUMBER_RE = re.compile(
    r"[+-]?(?P<mantissa>[0-9]*\.?[0-9]*)(?:[eE](?P<exp>[+-]?[0-9]*))?"
)


def _parse_number(value: str, whole: bool = False) -> float | None:
    """Parse a number like sscanf("%lg"), which CMake uses.

    It reads as much as could still become a number and ignores the rest, so
    "3abc" is 3, but fails if what it read isn't a number, like "1e" or "0x".
    With ``whole``, the rest has to be empty, like for a condition's constant.
    """
    text = value.lstrip(" \t\n\v\f\r")
    special = _SPECIAL_NUMBER_RE.match(text)
    if special:
        word = special.group().lstrip("+-").lower()
        if word not in ("inf", "infinity", "nan") or (
            whole and special.end() != len(text)
        ):
            return None
        return float(special.group())
    hex_number = _HEX_NUMBER_RE.match(text)
    match = hex_number or _DECIMAL_NUMBER_RE.match(text)
    assert match  # The decimal pattern also matches nothing
    exponent = match.group("exp")
    if (
        not match.group("mantissa").strip(".")
        or (exponent is not None and not exponent.lstrip("+-"))
        or (whole and match.end() != len(text))
    ):
        return None
    return float.fromhex(match.group()) if hex_number else float(match.group())


def evaluate_condition(
    args: list[str],
    variables: dict[str, str],
    target_exists: Callable[[str], bool] | None = None,
    command_exists: Callable[[str], bool] | None = None,
    test_exists: Callable[[str], bool] | None = None,
) -> bool:
    """Evaluate a CMake if() condition.

    ``command_exists`` is asked about lowercase names of commands that aren't
    built into CMake, i.e. functions and macros.
    """
    if not args:
        return False

    i = 0

    def is_defined(name: str) -> bool:
        m = re.fullmatch(r"ENV\{\s*(\w+)\s*\}", name)
        if m:
            return m.group(1) in os.environ
        m = re.fullmatch(r"CACHE\{\s*(\w+)\s*\}", name)
        if m:
            return m.group(1) in variables and variables.get(m.group(1)) != UNDEFINED_VAR_SENTINEL
        return name in variables and variables.get(name) != UNDEFINED_VAR_SENTINEL

    def resolve(name: str) -> str:
        if name in variables:
            val = variables[name]
            if val == UNDEFINED_VAR_SENTINEL:
                return ""
            return val
        return name

    def parse_or() -> bool:
        nonlocal i
        left = parse_and()
        while i < len(args) and args[i] == "OR":
            i += 1
            right = parse_and()
            left = left or right
        return left

    def parse_and() -> bool:
        nonlocal i
        left = parse_not()
        while i < len(args) and args[i] == "AND":
            i += 1
            right = parse_not()
            left = left and right
        return left

    def parse_not() -> bool:
        nonlocal i
        if i < len(args) and args[i] == "NOT":
            i += 1
            return not parse_not()
        return parse_atom()

    def parse_atom() -> bool:
        nonlocal i
        if i >= len(args):
            return False

        if args[i] == "(":
            i += 1
            res = parse_or()
            if i < len(args) and args[i] == ")":
                i += 1
            return res

        # Handle other unary operators
        if args[i] in _UNARY_OPERATORS:
            op = args[i]
            i += 1
            if i < len(args):
                val = args[i]
                i += 1
                if op == "DEFINED":
                    return is_defined(val)
                if op in _FILE_TESTS:
                    return _FILE_TESTS[op](val)
                if op == "IS_ABSOLUTE":
                    return _is_absolute(val)
                if op == "COMMAND":
                    return val.lower() in BUILTIN_COMMANDS or (
                        command_exists is not None and command_exists(val.lower())
                    )
                if op == "TARGET":
                    return target_exists(val) if target_exists else False
                if op == "TEST":
                    return test_exists(val) if test_exists else False
                if op == "POLICY":
                    match = re.fullmatch(r"CMP([0-9]{4})", val)
                    return match is not None and int(match.group(1)) <= _NEWEST_POLICY
            return False

        # Handle binary operators/comparisons
        left = args[i]
        i += 1
        if i < len(args) and args[i] in _BINARY_OPERATORS:
            op = args[i]
            i += 1
            if i < len(args):
                right = args[i]
                i += 1

                left_val = resolve(left)
                right_val = resolve(right)

                if op in _COMPARISONS:
                    left_num = _parse_number(left_val)
                    right_num = _parse_number(right_val)
                    if left_num is None or right_num is None:
                        return False
                    return _COMPARISONS[op](left_num, right_num)
                if op.startswith("STR"):
                    return _COMPARISONS[op[3:]](left_val, right_val)
                if op.startswith("VERSION_"):
                    compare = _COMPARISONS[op[8:]]
                    return compare(compare_versions(left_val, right_val), 0)
                if op == "IS_NEWER_THAN":
                    return _is_newer_than(left, right)
                if op == "PATH_EQUAL":
                    return _path_components(left_val) == _path_components(right_val)
                if op == "IN_LIST":
                    # The right side always names a list variable.
                    items = variables.get(right)
                    if items is None or items == UNDEFINED_VAR_SENTINEL:
                        return False
                    return left_val in items.split(";")
                if op == "MATCHES":
                    match = re.search(cmake_regex_to_python(right_val), left_val)
                    if match:
                        variables["CMAKE_MATCH_0"] = match.group(0)
                        for idx, group in enumerate(match.groups(), start=1):
                            variables[f"CMAKE_MATCH_{idx}"] = group
                        return True
                    return False
            return False

        # Single value: a constant, or else the name of a variable
        if is_on(left):
            return True
        if is_off(left):
            return False
        number = _parse_number(left, whole=True)
        if number is not None:
            return bool(number)
        return left in variables and not is_off(resolve(left))

    return parse_or()


def find_else_or_elseif(
    commands: list[Command], start: int, end: int
) -> list[tuple[str, int, list[str]]]:
    """Find elseif/else blocks between if and endif, returns list of (type, index, args)."""
    blocks: list[tuple[str, int, list[str]]] = []
    depth = 0
    i = start + 1
    while i < end:
        if commands[i].name == "if":
            depth += 1
        elif commands[i].name == "endif":
            depth -= 1
        elif depth == 0:
            if commands[i].name == "elseif":
                blocks.append(("elseif", i, commands[i].args))
            elif commands[i].name == "else":
                blocks.append(("else", i, []))
        i += 1
    return blocks
