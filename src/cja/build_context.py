from dataclasses import dataclass, field
import os
from pathlib import Path
import platform
import re
import sys

from termcolor import colored

from .parser import Command
from .syntax import FetchContentInfo, FunctionDef, MacroDef, SourceFileProperties, Test
from .utils import make_relative, resolve_cmake_path
from .targets import Executable, ImportedTarget, InstallTarget, Library


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
    defined_file: Path | None = None
    defined_line: int = 0


@dataclass
class BuildContext:
    """Context for processing CMake commands."""

    source_dir: Path
    build_dir: Path
    current_source_dir: Path = field(init=False)
    current_list_file: Path = field(init=False)
    project_name: str = ""
    variables: dict[str, str] = field(default_factory=dict)
    cache_variables: set[str] = field(default_factory=set)  # Variables from -D flags
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
    functions: dict[str, FunctionDef] = field(
        default_factory=dict
    )  # User-defined functions
    macros: dict[str, MacroDef] = field(
        default_factory=dict
    )  # User-defined macros  # noqa: F821
    tests: list[Test] = field(default_factory=list)  # Test definitions
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
    cmake_files: set[Path] = field(default_factory=set)
    c_compiler: str = field(default_factory=_default_c_compiler)
    cxx_compiler: str = field(default_factory=_default_cxx_compiler)

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

    def get_library(self, name: str) -> Library | None:
        for lib in self.libraries:
            if lib.name == name:
                return lib
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

    def raise_syntax_error(self, message: str, line: int) -> None:
        """Raise a SyntaxError with file and line information."""
        raise SyntaxError(message, (str(self.current_list_file), line, 0, ""))

    def expand_variables(
        self,
        value: str,
        strict: bool = False,
        line: int = 0,
        allow_undefined_empty: bool = False,
        allow_undefined_warning: bool = False,
    ) -> str:
        """Expand ${VAR} and $ENV{VAR} references in a string."""
        # Common CMake pattern: if ("${VAR}" STREQUAL "") should not warn when VAR is undefined.
        if allow_undefined_empty:
            exact_var = re.fullmatch(r"\$\{(\w+)\}", value)
            quoted_var = re.fullmatch(r"[\"']\$\{(\w+)\}[\"']", value)
            match = exact_var or quoted_var
            if match and match.group(1) not in self.variables:
                return ""

        def replace_normal(match: re.Match[str]) -> str:
            var_name = match.group(1)
            if var_name not in self.variables:
                if allow_undefined_empty:
                    return ""
                if allow_undefined_warning:
                    self.print_warning(f"undefined variable referenced: {var_name}", line)
                    return ""
                level = self.print_error if strict else self.print_warning
                level(f"undefined variable referenced: {var_name}", line)
                if strict:
                    sys.exit(1)
                return ""
            return self.variables.get(var_name, "")

        def replace_env(match: re.Match[str]) -> str:
            var_name = match.group(1)
            return os.environ.get(var_name, "")

        result = value
        for _ in range(10):
            # Expand $ENV{VAR} first
            expanded = re.sub(r"\$ENV\{(\w+)\}", replace_env, result)
            # Then ${VAR}; match innermost braces first to support nested names like
            # ${CPM_PACKAGE_${PACKAGE}_SOURCE_DIR}.
            expanded = re.sub(r"\$\{([^{}]+)\}", replace_normal, expanded)
            if expanded == result:
                break
            result = expanded
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
