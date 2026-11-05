import os
import platform
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from termcolor import colored

from .parser import LITERAL_BACKSLASH_MARKER, Command
from .syntax import FetchContentInfo, FunctionDef, MacroDef, SourceFileProperties, Test
from .targets import (
    TARGET_PROPERTY_FIELDS,
    Executable,
    ImportedTarget,
    InstallTarget,
    Library,
)
from .utils import (
    UNDEFINED_VAR_SENTINEL,
    make_relative,
    resolve_cmake_path,
    split_unquoted_list_args,
    to_posix_path,
)

# Modules bundled with cja (e.g. FindGTest.cmake, CMakeFindDependencyMacro.cmake)
# CMAKE_ROOT: like CMake's, it has the bundled modules in Modules/
CMAKE_ROOT = Path(__file__).parent / "cmake"
BUILTIN_MODULES_DIR = CMAKE_ROOT / "Modules"


def is_exact_variable_reference(arg: str) -> bool:
    """Whether arg is a single ${VAR} or $CACHE{VAR}, optionally in quotes."""
    if len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in "\"'":
        arg = arg[1:-1]
    return arg.startswith(("${", "$CACHE{")) and arg.endswith("}")


class TrackedDict(dict[str, str]):
    """Dict subclass that records which keys are read.

    Used so we can warn at the end of configure about -D variables that the
    project never accessed (mirrors CMake's "Manually-specified variables were
    not used by the project" warning).
    """

    def __init__(
        self,
        *args: Any,
        _tracker: set[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._tracker: set[str] = _tracker if _tracker is not None else set()
        # Names with a normal binding in this scope. Such a binding hides a
        # cache entry of the same name, like in CMake. Every assignment
        # creates one; cache entries are written via BuildContext.set_cache().
        self.normal_bindings: set[str] = set()

    def __setitem__(self, key: str, value: str) -> None:
        self.normal_bindings.add(key)
        super().__setitem__(key, value)

    def pop(self, key: str, *args: Any) -> Any:  # type: ignore[override]
        self.normal_bindings.discard(key)
        return super().pop(key, *args)

    def __getitem__(self, key: str) -> str:
        self._tracker.add(key)
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        if isinstance(key, str):
            self._tracker.add(key)
        return super().__contains__(key)

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        self._tracker.add(key)
        return super().get(key, default)

    def setdefault(self, key: str, default: Any = "") -> Any:  # type: ignore[override]
        self._tracker.add(key)
        return super().setdefault(key, default)

    def copy(self) -> "TrackedDict":
        new = TrackedDict(_tracker=self._tracker)
        for k, v in dict.items(self):
            dict.__setitem__(new, k, v)
        new.normal_bindings = set(self.normal_bindings)
        return new


def _default_c_compiler() -> str:
    """Pick a sensible default C compiler command for the host platform."""
    env_cc = os.getenv("CC")
    if env_cc:
        return env_cc
    if platform.system() == "Windows":
        return "clang"
    return "cc"


def _default_cxx_compiler() -> str:
    """Pick a sensible default C++ compiler command for the host platform."""
    env_cxx = os.getenv("CXX")
    if env_cxx:
        return env_cxx
    if platform.system() == "Windows":
        return "clang++"
    return "c++"


@dataclass
class CustomCommand:
    """A custom build command."""

    outputs: list[str]
    commands: list[list[str]]
    depends: list[str]
    main_dependency: str | None = None
    working_directory: str | None = None
    verbatim: bool = False
    uses_terminal: bool = False
    defined_file: Path | None = None
    defined_line: int = 0


@dataclass
class CustomTarget:
    """A custom target (phony build target)."""

    name: str
    commands: list[list[str]]
    depends: list[str]
    all: bool = False
    working_directory: str | None = None
    verbatim: bool = False
    uses_terminal: bool = False
    comment: str = ""
    defined_file: Path | None = None
    defined_line: int = 0
    dependencies: list[str] = field(default_factory=list)


@dataclass
class ConfigureDependGlob:
    """A file(GLOB ... CONFIGURE_DEPENDS) call, re-checked at build time."""

    pattern: str
    base_dir: Path
    recursive: bool
    list_directories: bool | None
    files: list[str]
    dirs: list[str]


@dataclass
class DeferredCall:
    """A call scheduled by cmake_language(DEFER)."""

    id: str
    # Its arguments are expanded only when it runs.
    command: Command
    # The file of cmake_language(DEFER), where diagnostics of the call point.
    list_file: Path


@dataclass
class Directory:
    """The top-level directory or one added by add_subdirectory() or FetchContent."""

    source_dir: Path
    binary_dir: Path
    # Calls to run at the end of the directory; None once it's finished.
    deferred_calls: list[DeferredCall] | None = field(default_factory=list)


@dataclass
class BuildContext:
    """Context for processing CMake commands."""

    source_dir: Path
    build_dir: Path
    current_source_dir: Path = field(init=False)
    current_list_file: Path = field(init=False)
    project_name: str = ""
    variables: TrackedDict = field(default_factory=TrackedDict)
    # Cache entries. Their values are visible through `variables` unless a
    # normal binding of the same name hides them.
    cache_values: dict[str, str] = field(default_factory=dict)
    cli_variables: dict[str, str] = field(
        default_factory=dict
    )  # Original -D flag values
    libraries: list[Library] = field(default_factory=list)
    executables: list[Executable] = field(default_factory=list)
    imported_targets: dict[str, ImportedTarget] = field(default_factory=dict)
    compile_options: list[str] = field(default_factory=list)  # Global compile options
    compile_definitions: list[str] = field(
        default_factory=list
    )  # Global compile definitions
    custom_commands: list[CustomCommand] = field(
        default_factory=list
    )  # Custom build commands
    custom_targets: list[CustomTarget] = field(
        default_factory=list
    )  # Custom targets (phony)
    functions: dict[str, FunctionDef] = field(
        default_factory=dict
    )  # User-defined functions
    macros: dict[str, MacroDef] = field(
        default_factory=dict
    )  # User-defined macros
    tests: list[Test] = field(default_factory=list)  # Test definitions
    # Messages of message(CHECK_START) still waiting for CHECK_PASS/CHECK_FAIL
    check_messages: list[str] = field(default_factory=list)
    install_targets: list[InstallTarget] = field(
        default_factory=list
    )  # Installation targets
    source_file_properties: dict[str, SourceFileProperties] = field(
        default_factory=dict
    )  # Properties for source files
    parent_scope_vars: dict[str, str | None] = field(
        default_factory=dict
    )  # For PARENT_SCOPE in functions
    fetched_content: dict[str, FetchContentInfo] = field(
        default_factory=dict
    )  # For FetchContent
    global_properties: dict[str, str] = field(
        default_factory=dict
    )  # Global properties set via set_property(GLOBAL ...)
    directory_properties: dict[str, dict[str, str]] = field(
        default_factory=dict
    )  # Properties for directories
    parent_directory: str = ""  # Path to parent directory (if in subdirectory)
    # Inside an add_subdirectory(... EXCLUDE_FROM_ALL), so new targets start
    # out excluded from "all"
    exclude_from_all: bool = False
    # How many add_subdirectory()/FetchContent levels below the top-level
    # directory we are, so "cja run" can prefer the shallowest executable
    directory_depth: int = 0
    cmake_files: set[Path] = field(default_factory=set)
    configure_depends: set[Path] = field(default_factory=set)
    configure_depend_globs: list[ConfigureDependGlob] = field(default_factory=list)
    include_guarded_files: set[Path] = field(default_factory=set)
    c_compiler: str = field(default_factory=_default_c_compiler)
    cxx_compiler: str = field(default_factory=_default_cxx_compiler)
    # argv behind CMAKE_COMMAND; kept as a list because the joined variable
    # can't distinguish a path with spaces from a multi-word command.
    cja_cmd: list[str] = field(default_factory=list)
    quiet: bool = False
    # message(SEND_ERROR) was called: keep processing, but fail at the end.
    send_error: bool = False
    # Every directory entered so far, parents before their subdirectories
    directories: list[Directory] = field(default_factory=list)
    # Number of ids generated for cmake_language(DEFER) so far
    deferred_call_ids: int = 0

    def __post_init__(self) -> None:
        self.current_source_dir = self.source_dir
        self.current_list_file = self.source_dir / "CMakeLists.txt"
        self.record_cmake_file(self.current_list_file)

    def record_cmake_file(self, path: Path) -> None:
        """Track a CMakeLists.txt or .cmake file used during configure."""
        try:
            resolved = path.resolve()
        except FileNotFoundError:
            resolved = path
        self.cmake_files.add(resolved)

    def record_configure_depend(self, path: Path) -> None:
        """Track a path whose mtime should trigger reconfigure (e.g. GLOB dirs)."""
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        self.configure_depends.add(resolved)

    def enter_list_file(self, path: Path) -> Callable[[], None]:
        """Start processing another list file, like include() does.

        Returns the function that goes back to the previous list file, even
        when this was called inside a function or macro, whose commands come
        from another file than CMAKE_CURRENT_LIST_FILE.
        """
        saved_file = self.current_list_file
        saved_values = {
            name: self.variables.get(name)
            for name in ("CMAKE_CURRENT_LIST_FILE", "CMAKE_CURRENT_LIST_DIR")
        }
        self.current_list_file = path
        self.variables["CMAKE_CURRENT_LIST_FILE"] = to_posix_path(path)
        self.variables["CMAKE_CURRENT_LIST_DIR"] = to_posix_path(path.parent)

        def leave() -> None:
            self.current_list_file = saved_file
            for name, value in saved_values.items():
                if value is None:
                    self.variables.pop(name, None)
                else:
                    self.variables[name] = value

        return leave

    def default_install_prefix(self) -> str:
        """cja installs into the build directory unless told otherwise."""
        return to_posix_path(self.build_dir / "install")

    def set_cache(self, name: str, value: str) -> None:
        """Set a cache entry; a normal binding of the same name keeps hiding it."""
        self.cache_values[name] = value
        if name not in self.variables.normal_bindings:
            dict.__setitem__(self.variables, name, value)

    def cache_updates(self) -> dict[str, str]:
        """Cache entries to carry over to the parent when leaving a scope."""
        return dict(self.cache_values)

    def apply_cache_updates(self, updates: dict[str, str]) -> None:
        """Make cache entries visible unless a normal binding hides them."""
        for name, value in updates.items():
            if name not in self.variables.normal_bindings:
                dict.__setitem__(self.variables, name, value)

    def get_library(self, name: str) -> Library | None:
        for lib in self.libraries:
            if lib.name == name:
                if lib.is_alias and lib.alias_for:
                    return self.get_library(lib.alias_for)
                return lib
        return None

    def target_property(self, name: str, prop: str) -> str | None:
        """A target's property, or None if the target or property is unknown."""
        lib = self.get_library(name)
        exe = self.get_executable(name)
        target = lib or exe
        if target is not None:
            if prop == "TYPE":
                return f"{lib.lib_type}_LIBRARY" if lib else "EXECUTABLE"
            field_name = TARGET_PROPERTY_FIELDS.get(prop)
            if field_name is not None and hasattr(target, field_name):
                values: list[str] = getattr(target, field_name)
                return ";".join(values) if values else None
            return target.properties.get(prop)
        imported = self.imported_targets.get(name)
        if imported is not None:
            return imported.properties.get(prop)
        return None

    def get_executable(self, name: str) -> Executable | None:
        for exe in self.executables:
            if exe.name == name:
                return exe
        return None

    def resolve_path(self, path: str) -> str:
        """Resolve a path against current_source_dir and make it relative to source_dir."""
        resolved = resolve_cmake_path(path, self.current_source_dir)
        return make_relative(resolved, self.source_dir)

    def print_warning(self, message: str, line: int = 0) -> None:
        """Print a warning message."""
        if self.quiet:
            return
        warning_label = colored("warning:", "magenta", attrs=["bold"])
        rel_file = make_relative(str(self.current_list_file), self.source_dir)
        location = f"{rel_file}:{line}: " if line > 0 else ""
        print(f"{location}{warning_label} {message}", file=sys.stderr)

    def print_error(self, message: str, line: int = 0) -> None:
        """Print an error message."""
        error_label = colored("error:", "red", attrs=["bold"])
        rel_file = make_relative(str(self.current_list_file), self.source_dir)
        location = f"{rel_file}:{line}: " if line > 0 else ""
        print(f"{location}{error_label} {message}", file=sys.stderr)

    def check_unsupported_args(
        self, cmd: Command, unsupported: list[str], strict: bool
    ) -> None:
        """With --strict, error out if the command got arguments cja ignores."""
        if not strict or not unsupported:
            return
        names = list(dict.fromkeys(unsupported))
        plural = "s" if len(names) > 1 else ""
        self.print_error(
            f"unsupported argument{plural} to {cmd.name}(): {', '.join(names)}",
            cmd.line,
        )
        sys.exit(1)

    def enter_directory(self, source_dir: Path, binary_dir: Path) -> Directory:
        """Start processing the CMakeLists.txt of a directory."""
        directory = Directory(
            Path(os.path.normpath(source_dir)), Path(os.path.normpath(binary_dir))
        )
        self.directories.append(directory)
        return directory

    def current_directory(self) -> Directory | None:
        """The innermost directory whose CMakeLists.txt is still processed."""
        return next(
            (d for d in reversed(self.directories) if d.deferred_calls is not None),
            None,
        )

    def expand_arguments(
        self, cmd: Command, strict: bool, start: int = 0, stop: int | None = None
    ) -> list[str]:
        """Expand the arguments of cmd from start to stop for calling it."""
        expanded_args: list[str] = []
        for idx in range(start, len(cmd.args) if stop is None else stop):
            arg = cmd.args[idx]
            is_bracket = cmd.is_bracket[idx] if idx < len(cmd.is_bracket) else False
            if is_bracket:
                # Bracket arguments ([[...]] / [==[...]==]) are literal: no
                # variable expansion and no list splitting.
                expanded_args.append(arg)
                continue
            allow_undefined = False
            is_exact_var = is_exact_variable_reference(arg)
            if cmd.name in ("if", "elseif", "while"):
                allow_undefined = (
                    idx + 2 < len(cmd.args)
                    and cmd.args[idx + 1] == "STREQUAL"
                    and cmd.args[idx + 2] in ("", '""', "''")
                    and is_exact_var
                )
                # In CMake conditions, unresolved ${VAR} or $CACHE{VAR} tokens
                # are treated as empty and should not raise undefined-variable
                # warnings.
                allow_undefined = allow_undefined or is_exact_var
            elif cmd.name == "option":
                # Common CMake pattern:
                #   option(FOO "help" ${SOME_DEFAULT})
                # where SOME_DEFAULT can be undefined and should evaluate empty.
                allow_undefined = idx == 2 and is_exact_var
            expanded = self.expand_variables(
                arg,
                strict,
                cmd.line,
                allow_undefined_empty=allow_undefined,
            )
            quoted = cmd.is_quoted[idx] if idx < len(cmd.is_quoted) else False
            if arg and not expanded and not quoted:
                # An unquoted argument that expands to nothing is dropped.
                continue
            if ";" in expanded and not quoted:
                # Like the whole argument, empty list elements are dropped.
                expanded_args.extend(
                    item for item in split_unquoted_list_args(expanded) if item
                )
            else:
                expanded_args.append(expanded)
        return expanded_args

    def raise_syntax_error(self, message: str, line: int) -> None:
        """Raise a SyntaxError with file and line information."""
        raise SyntaxError(message, (str(self.current_list_file), line, 0, ""))

    def expand_variables(
        self,
        value: str,
        strict: bool = False,
        line: int = 0,
        allow_undefined_empty: bool = False,
    ) -> str:
        """Expand ${VAR}, $ENV{VAR} and $CACHE{VAR} references in a string."""
        escaped_var_marker = "__CJA_ESC_VAR_OPEN__"
        escaped_env_marker = "__CJA_ESC_ENV_OPEN__"
        escaped_cache_marker = "__CJA_ESC_CACHE_OPEN__"
        value = value.replace("\\$ENV{", escaped_env_marker)
        value = value.replace("\\$CACHE{", escaped_cache_marker)
        value = value.replace("\\${", escaped_var_marker)

        # Common CMake pattern: if ("${VAR}" STREQUAL "") should not warn when VAR is undefined.
        if allow_undefined_empty:
            exact_var = re.fullmatch(r"\$\{(\w+)\}", value)
            quoted_var = re.fullmatch(r"[\"']\$\{(\w+)\}[\"']", value)
            match = exact_var or quoted_var
            if match and match.group(1) not in self.variables:
                return ""

        def replace_undefined(var_name: str) -> str:
            # Modules from CMake rely on undefined variables being empty,
            # and projects can't change cja's bundled modules anyway.
            if (
                strict
                and not allow_undefined_empty
                and self.current_list_file.parent != BUILTIN_MODULES_DIR
            ):
                self.print_warning(f"undefined variable referenced: {var_name}", line)
            return ""

        def replace_normal(var_name: str) -> str:
            if not var_name:
                return ""
            if var_name not in self.variables:
                return replace_undefined(var_name)
            value = self.variables.get(var_name, "")
            if value == UNDEFINED_VAR_SENTINEL:
                return ""
            return value

        def replace_env(var_name: str) -> str:
            return os.environ.get(var_name, "")

        def replace_cache(var_name: str) -> str:
            if not var_name:
                return ""
            if var_name in self.cache_values:
                return self.cache_values[var_name]
            # Like CMake, only warn if there's no normal variable either.
            if var_name in self.variables:
                return ""
            return replace_undefined(var_name)

        references = (
            ("${", replace_normal),
            ("$ENV{", replace_env),
            ("$CACHE{", replace_cache),
        )

        def scan(pos: int, in_ref: bool) -> tuple[str, int] | None:
            """Expand references starting at pos in a single pass.

            Names like ${CPM_PACKAGE_${PACKAGE}_SOURCE_DIR} or $ENV{${FOO}} are
            expanded innermost first, and substituted values are never scanned
            again. Inside a reference, stops at the closing "}" and returns its
            index; returns None if that "}" is missing.
            """
            out: list[str] = []
            while pos < len(value):
                reference = None
                if value[pos] == "$":
                    reference = next(
                        (r for r in references if value.startswith(r[0], pos)), None
                    )
                if reference:
                    opening, replace = reference
                    inner = scan(pos + len(opening), in_ref=True)
                    if inner is None:
                        # Unterminated reference: keep the rest literally
                        out.append(value[pos:])
                        pos = len(value)
                        break
                    name, end = inner
                    out.append(replace(name))
                    pos = end + 1
                elif in_ref and value[pos] == "}":
                    return "".join(out), pos
                else:
                    out.append(value[pos])
                    pos += 1
            if in_ref:
                return None
            return "".join(out), pos

        scanned = scan(0, in_ref=False)
        assert scanned is not None
        result = scanned[0]
        result = result.replace(escaped_env_marker, "$ENV{")
        result = result.replace(escaped_cache_marker, "$CACHE{")
        result = result.replace(escaped_var_marker, "${")
        result = result.replace(LITERAL_BACKSLASH_MARKER, "\\")
        return result


def find_matching_endif(commands: list[Command], start: int, ctx: BuildContext) -> int:
    """Find the index of the endif() matching the if() at start."""
    depth = 1
    i = start + 1
    while i < len(commands):
        if commands[i].name == "if":
            depth += 1
        elif commands[i].name == "endif":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    ctx.raise_syntax_error("No matching endif() for if()", commands[start].line)
    return -1  # unreachable


def find_matching_endforeach(
    commands: list[Command], start: int, ctx: BuildContext
) -> int:
    """Find the index of the endforeach() matching the foreach() at start."""
    depth = 1
    i = start + 1
    while i < len(commands):
        if commands[i].name == "foreach":
            depth += 1
        elif commands[i].name == "endforeach":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    ctx.raise_syntax_error(
        "No matching endforeach() for foreach()", commands[start].line
    )
    return -1  # unreachable


def find_matching_endwhile(
    commands: list[Command], start: int, ctx: BuildContext
) -> int:
    """Find the index of the endwhile() matching the while() at start."""
    depth = 1
    i = start + 1
    while i < len(commands):
        if commands[i].name == "while":
            depth += 1
        elif commands[i].name == "endwhile":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    ctx.raise_syntax_error("No matching endwhile() for while()", commands[start].line)
    return -1  # unreachable


def find_matching_endfunction(
    commands: list[Command], start: int, ctx: BuildContext
) -> int:
    """Find the index of the endfunction() matching the function() at start."""
    depth = 1
    i = start + 1
    while i < len(commands):
        if commands[i].name == "function":
            depth += 1
        elif commands[i].name == "endfunction":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    ctx.raise_syntax_error(
        "No matching endfunction() for function()", commands[start].line
    )
    return -1  # unreachable


def find_matching_endmacro(
    commands: list[Command], start: int, ctx: BuildContext
) -> int:
    """Find the index of the endmacro() matching the macro() at start."""
    depth = 1
    i = start + 1
    while i < len(commands):
        if commands[i].name == "macro":
            depth += 1
        elif commands[i].name == "endmacro":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    ctx.raise_syntax_error("No matching endmacro() for macro()", commands[start].line)
    return -1  # unreachable
