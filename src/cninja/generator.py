"""Ninja build file generator."""

import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from termcolor import colored

from .ninja_syntax import Writer
from .parser import Command


class ReturnFromFunction(Exception):
    """Exception raised to exit early from a function."""

    pass


@dataclass
class Library:
    """A library target."""

    name: str
    sources: list[str]
    lib_type: str = "STATIC"  # STATIC, SHARED, or OBJECT
    compile_features: list[str] = field(default_factory=list)  # PRIVATE features
    public_compile_features: list[str] = field(default_factory=list)  # PUBLIC features
    include_directories: list[str] = field(default_factory=list)  # PRIVATE includes
    public_include_directories: list[str] = field(
        default_factory=list
    )  # PUBLIC includes
    compile_definitions: list[str] = field(default_factory=list)  # PRIVATE definitions
    public_compile_definitions: list[str] = field(
        default_factory=list
    )  # PUBLIC definitions


@dataclass
class Executable:
    """An executable target."""

    name: str
    sources: list[str]
    link_libraries: list[str] = field(default_factory=list)
    compile_features: list[str] = field(default_factory=list)
    include_directories: list[str] = field(default_factory=list)
    compile_definitions: list[str] = field(default_factory=list)


@dataclass
class ImportedTarget:
    """An imported target (e.g., from find_package)."""

    cflags: str = ""  # Compile flags (e.g., -I/path/to/include)
    libs: str = ""  # Link flags (e.g., -lgtest -pthread)


@dataclass
class FunctionDef:
    """A CMake function definition."""

    name: str
    params: list[str]
    body: list  # list[Command] - forward reference


@dataclass
class SourceFileProperties:
    """Properties for a source file."""

    object_depends: list[str] = field(default_factory=list)
    include_directories: list[str] = field(default_factory=list)
    compile_definitions: list[str] = field(default_factory=list)


@dataclass
class Test:
    """A test definition."""

    name: str
    command: list[str]


@dataclass
class BuildContext:
    """Context for processing CMake commands."""

    source_dir: Path
    build_dir: Path
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
    custom_commands: list[dict[str, object]] = field(
        default_factory=list
    )  # Custom build commands
    functions: dict[str, FunctionDef] = field(
        default_factory=dict
    )  # User-defined functions
    tests: list[Test] = field(default_factory=list)  # Test definitions
    source_file_properties: dict[str, SourceFileProperties] = field(
        default_factory=dict
    )  # Properties for source files
    parent_scope_vars: dict[str, str] = field(
        default_factory=dict
    )  # For PARENT_SCOPE in functions

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


def expand_variables(
    value: str, variables: dict[str, str], strict: bool = False, line: int = 0
) -> str:
    """Expand ${VAR} references in a string."""

    def replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        if var_name not in variables:
            warning_label = colored("warning:", "magenta", attrs=["bold"])
            location = f"CMakeLists.txt:{line}: " if line > 0 else ""
            print(
                f"{location}{warning_label} undefined variable referenced: {var_name}",
                file=sys.stderr,
            )
            if strict:
                error_label = colored("error:", "red", attrs=["bold"])
                print(
                    f"{location}{error_label} undefined variable in strict mode: {var_name}",
                    file=sys.stderr,
                )
                sys.exit(1)
            return ""
        return variables.get(var_name, "")

    return re.sub(r"\$\{(\w+)\}", replace, value)


def make_relative(path_str: str, root: Path) -> str:
    """Convert an absolute path to a relative path if it's under the root directory."""
    try:
        path = Path(path_str)
        if path.is_absolute() and path.is_relative_to(root):
            return str(path.relative_to(root))
    except ValueError:
        pass
    return path_str


def is_truthy(value: str) -> bool:
    """Check if a CMake value is considered true."""
    if not value:
        return False
    # CMake considers these values false
    false_values = ("0", "OFF", "NO", "FALSE", "N", "IGNORE", "NOTFOUND", "")
    upper = value.upper()
    if upper in false_values or upper.endswith("-NOTFOUND"):
        return False
    return True


def compile_feature_to_flag(feature: str) -> str | None:
    """Translate a CMake compile feature to a compiler flag."""
    # Map cxx_std_XX features to -std=c++XX flags
    if feature.startswith("cxx_std_"):
        std_version = feature[8:]  # Extract "11", "14", "17", "20", "23", etc.
        return f"-std=c++{std_version}"
    # Map c_std_XX features to -std=cXX flags
    if feature.startswith("c_std_"):
        std_version = feature[6:]
        return f"-std=c{std_version}"
    # Other features could be added here
    return None


def evaluate_condition(args: list[str], variables: dict[str, str]) -> bool:
    """Evaluate a CMake if() condition."""
    if not args:
        return False

    # Handle NOT
    if args[0] == "NOT":
        return not evaluate_condition(args[1:], variables)

    # Handle DEFINED
    if args[0] == "DEFINED" and len(args) >= 2:
        return args[1] in variables

    # Helper to get value (expand variable if it exists)
    def get_value(s: str) -> str:
        return variables.get(s, s)

    # Handle binary operators
    if len(args) >= 3:
        left = args[0]
        op = args[1]
        right = args[2]

        # Handle AND/OR with remaining args
        if op == "AND":
            return evaluate_condition([left], variables) and evaluate_condition(
                args[2:], variables
            )
        if op == "OR":
            return evaluate_condition([left], variables) or evaluate_condition(
                args[2:], variables
            )

        # For comparisons, expand variables
        left_val = get_value(left)
        right_val = get_value(right)

        # String comparisons
        if op == "STREQUAL":
            return left_val == right_val
        if op == "STRLESS":
            return left_val < right_val
        if op == "STRGREATER":
            return left_val > right_val
        if op == "MATCHES":
            return bool(re.search(right_val, left_val))

        # Numeric comparisons
        if op == "EQUAL":
            try:
                return int(left_val) == int(right_val)
            except ValueError:
                return False
        if op == "LESS":
            try:
                return int(left_val) < int(right_val)
            except ValueError:
                return False
        if op == "GREATER":
            try:
                return int(left_val) > int(right_val)
            except ValueError:
                return False

    # Single value - check if variable is defined and truthy
    if len(args) == 1:
        var_name = args[0]
        # In CMake, if(VAR) checks if VAR is defined and truthy
        # Undefined variables evaluate to false
        if var_name in variables:
            return is_truthy(variables[var_name])
        # If not a defined variable, treat as false (undefined = false in CMake)
        return False

    return False


def find_matching_endif(commands: list[Command], start: int) -> int:
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
    raise SyntaxError(f"No matching endif() for if() at line {commands[start].line}")


def find_matching_endforeach(commands: list[Command], start: int) -> int:
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
    raise SyntaxError(
        f"No matching endforeach() for foreach() at line {commands[start].line}"
    )


def find_matching_endfunction(commands: list[Command], start: int) -> int:
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
    raise SyntaxError(
        f"No matching endfunction() for function() at line {commands[start].line}"
    )


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


def process_commands(
    commands: list[Command],
    ctx: BuildContext,
    trace: bool = False,
    strict: bool = False,
) -> None:
    """Process CMake commands and populate the build context."""
    # Ensure CMAKE_COMMAND is always set
    ctx.variables["CMAKE_COMMAND"] = "cninja"
    i = 0
    while i < len(commands):
        cmd = commands[i]
        args = [
            expand_variables(arg, ctx.variables, strict, cmd.line) for arg in cmd.args
        ]

        if trace:
            args_str = " ".join(cmd.args) if cmd.args else ""
            print(f"{colored('--', 'cyan')} {cmd.name}({args_str})")

        match cmd.name:
            case "if":
                # Find matching endif
                endif_idx = find_matching_endif(commands, i)
                # Find elseif/else blocks
                blocks = find_else_or_elseif(commands, i, endif_idx)

                # Determine which block to execute
                executed = False
                block_start = i + 1

                # Check the if condition
                if_args = [
                    expand_variables(arg, ctx.variables, strict, cmd.line)
                    for arg in cmd.args
                ]
                if evaluate_condition(if_args, ctx.variables):
                    # Execute commands from if to first elseif/else or endif
                    block_end = blocks[0][1] if blocks else endif_idx
                    process_commands(
                        commands[block_start:block_end], ctx, trace, strict
                    )
                    executed = True
                else:
                    # Check elseif/else blocks
                    for j, (block_type, block_idx, block_args) in enumerate(blocks):
                        if executed:
                            break
                        if block_type == "elseif":
                            elseif_args = [
                                expand_variables(
                                    arg, ctx.variables, strict, commands[block_idx].line
                                )
                                for arg in block_args
                            ]
                            if evaluate_condition(elseif_args, ctx.variables):
                                # Execute this elseif block
                                block_start = block_idx + 1
                                block_end = (
                                    blocks[j + 1][1]
                                    if j + 1 < len(blocks)
                                    else endif_idx
                                )
                                process_commands(
                                    commands[block_start:block_end], ctx, trace, strict
                                )
                                executed = True
                        elif block_type == "else":
                            # Execute else block
                            block_start = block_idx + 1
                            process_commands(
                                commands[block_start:endif_idx], ctx, trace, strict
                            )
                            executed = True

                # Skip to after endif
                i = endif_idx + 1
                continue

            case "endif" | "else" | "elseif":
                # These should only be encountered when processing top-level commands
                # and indicate mismatched if/endif
                raise SyntaxError(f"Unexpected {cmd.name}() at line {cmd.line}")

            case "foreach":
                if not args:
                    raise SyntaxError(
                        f"foreach() requires at least a loop variable at line {cmd.line}"
                    )

                # Find matching endforeach
                endforeach_idx = find_matching_endforeach(commands, i)
                body = commands[i + 1 : endforeach_idx]

                loop_var = cmd.args[0]  # Use unexpanded for variable name
                remaining = args[1:]  # Use expanded args for values

                # Determine iteration items
                items: list[str] = []
                if remaining and remaining[0] == "RANGE":
                    # foreach(var RANGE stop) or foreach(var RANGE start stop [step])
                    range_args = remaining[1:]
                    if len(range_args) == 1:
                        stop = int(range_args[0])
                        items = [str(x) for x in range(stop + 1)]
                    elif len(range_args) == 2:
                        start, stop = int(range_args[0]), int(range_args[1])
                        items = [str(x) for x in range(start, stop + 1)]
                    elif len(range_args) >= 3:
                        start, stop, step = (
                            int(range_args[0]),
                            int(range_args[1]),
                            int(range_args[2]),
                        )
                        items = [str(x) for x in range(start, stop + 1, step)]
                elif remaining and remaining[0] == "IN":
                    # foreach(var IN LISTS list1 ... | ITEMS item1 ...)
                    mode = remaining[1] if len(remaining) > 1 else ""
                    values = remaining[2:]
                    if mode == "LISTS":
                        for list_name in values:
                            list_val = ctx.variables.get(list_name, "")
                            if list_val:
                                items.extend(list_val.split())
                    elif mode == "ITEMS":
                        items = values
                else:
                    # foreach(var item1 item2 ...)
                    items = remaining

                # Execute body for each item
                for item in items:
                    ctx.variables[loop_var] = item
                    process_commands(body, ctx, trace, strict)

                # Skip to after endforeach
                i = endforeach_idx + 1
                continue

            case "endforeach":
                raise SyntaxError(f"Unexpected endforeach() at line {cmd.line}")

            case "function":
                if not args:
                    raise SyntaxError(f"function() requires a name at line {cmd.line}")

                # Find matching endfunction
                endfunction_idx = find_matching_endfunction(commands, i)
                body = commands[i + 1 : endfunction_idx]

                func_name = cmd.args[0].lower()  # CMake functions are case-insensitive
                func_params = cmd.args[1:]  # Parameter names

                # Store the function definition
                ctx.functions[func_name] = FunctionDef(
                    name=func_name,
                    params=func_params,
                    body=body,
                )

                # Skip to after endfunction
                i = endfunction_idx + 1
                continue

            case "endfunction":
                raise SyntaxError(f"Unexpected endfunction() at line {cmd.line}")

            case "return":
                # Exit from current function early
                raise ReturnFromFunction()

            case "cmake_minimum_required":
                pass  # Just acknowledge it

            case "project":
                if args:
                    ctx.project_name = args[0]
                    ctx.variables["PROJECT_NAME"] = args[0]
                    ctx.variables["CMAKE_PROJECT_NAME"] = args[0]
                    ctx.variables["PROJECT_SOURCE_DIR"] = str(ctx.source_dir)
                    ctx.variables["PROJECT_BINARY_DIR"] = str(ctx.build_dir)
                    ctx.variables[f"{args[0]}_SOURCE_DIR"] = str(ctx.source_dir)
                    ctx.variables[f"{args[0]}_BINARY_DIR"] = str(ctx.build_dir)

            case "set":
                if args:
                    var_name = args[0]
                    values = args[1:]

                    # Filter out CACHE, PARENT_SCOPE, and track FORCE
                    filtered_values: list[str] = []
                    has_force = False
                    has_parent_scope = False
                    skip_next = 0
                    for idx, val in enumerate(values):
                        if skip_next > 0:
                            skip_next -= 1
                            continue
                        if val == "CACHE":
                            # CACHE TYPE "docstring" [FORCE] - skip type and docstring
                            skip_next = 2
                            continue
                        if val == "FORCE":
                            has_force = True
                            continue
                        if val == "PARENT_SCOPE":
                            has_parent_scope = True
                            continue
                        filtered_values.append(val)

                    # Don't override cache variables unless FORCE is specified
                    if var_name in ctx.cache_variables and not has_force:
                        pass  # Skip, variable was set via -D flag
                    elif has_parent_scope:
                        # Set in parent scope (for function calls)
                        if filtered_values:
                            ctx.parent_scope_vars[var_name] = " ".join(filtered_values)
                        else:
                            ctx.parent_scope_vars[var_name] = ""
                    elif filtered_values:
                        ctx.variables[var_name] = " ".join(filtered_values)
                    else:
                        # set(VAR) with no value unsets the variable
                        ctx.variables.pop(var_name, None)

            case "option":
                # option(<variable> "<help_text>" [value])
                # Defines a boolean cache variable, default OFF
                # Does nothing if variable already defined
                if args:
                    var_name = args[0]
                    if var_name not in ctx.variables:
                        # Default to OFF, or use provided value (3rd arg)
                        value = "OFF"
                        if len(args) >= 3:
                            value = args[2]
                        ctx.variables[var_name] = value

            case "math":
                # math(EXPR <variable> "<expression>" [OUTPUT_FORMAT <format>])
                if len(args) >= 3 and args[0] == "EXPR":
                    var_name = args[1]

                    # Find if OUTPUT_FORMAT is present
                    output_format = "DECIMAL"
                    expr_args = args[2:]
                    if "OUTPUT_FORMAT" in args:
                        idx = args.index("OUTPUT_FORMAT")
                        if idx + 1 < len(args):
                            output_format = args[idx + 1]
                        # Expression is everything between var_name and OUTPUT_FORMAT
                        expr_args = args[2:idx]

                    expr = " ".join(expr_args)
                    expr = " ".join(expr.split())

                    # Convert C-style operators to Python if necessary
                    # Integer division is // in Python.
                    # CMake's / is integer division.
                    expr = expr.replace("/", "//")

                    # Normalize leading-zero integer literals (CMake treats as decimal)
                    # Avoid transforming hex literals like 0xFF
                    def _normalize_leading_zeros(match: re.Match[str]) -> str:
                        literal = match.group(0)
                        return str(int(literal, 10))

                    expr = re.sub(r"\b0[0-9]+\b", _normalize_leading_zeros, expr)
                    # Handle bitwise NOT ~ which is the same in Python
                    # Handle % which is the same
                    # Handle <<, >>, &, |, ^ which are the same

                    try:
                        # Use a limited scope for eval
                        # We need to allow basic math operations
                        result = eval(expr, {"__builtins__": {}}, {})

                        if output_format == "HEXADECIMAL":
                            ctx.variables[var_name] = hex(int(result))
                        else:
                            ctx.variables[var_name] = str(int(result))
                    except Exception as e:
                        if strict:
                            error_label = colored("error:", "red", attrs=["bold"])
                            print(
                                f"CMakeLists.txt:{cmd.line}: {error_label} math(EXPR) evaluation error: {e}",
                                file=sys.stderr,
                            )
                            sys.exit(1)

            case "include":
                if args:
                    module_name = args[0]
                    known_modules = {
                        "CTest",
                        "CheckIPOSupported",
                        "CheckCXXCompilerFlag",
                        "CheckCCompilerFlag",
                        "CheckCXXSymbolExists",
                    }
                    if module_name == "CTest":
                        # CTest sets BUILD_TESTING to ON by default
                        if "BUILD_TESTING" not in ctx.variables:
                            ctx.variables["BUILD_TESTING"] = "ON"
                    elif module_name not in known_modules:
                        if strict:
                            error_label = colored("error:", "red", attrs=["bold"])
                            print(
                                f"CMakeLists.txt:{cmd.line}: {error_label} unknown module: {module_name}",
                                file=sys.stderr,
                            )
                            sys.exit(1)

            case "check_ipo_supported":
                # check_ipo_supported(RESULT <var> [OUTPUT <var>] [LANGUAGES <lang>...])
                result_var = None
                output_var = None

                arg_idx = 0
                while arg_idx < len(args):
                    if args[arg_idx] == "RESULT" and arg_idx + 1 < len(args):
                        result_var = args[arg_idx + 1]
                        arg_idx += 2
                    elif args[arg_idx] == "OUTPUT" and arg_idx + 1 < len(args):
                        output_var = args[arg_idx + 1]
                        arg_idx += 2
                    elif args[arg_idx] == "LANGUAGES":
                        # Skip languages, we just check C/C++
                        arg_idx += 1
                        while arg_idx < len(args) and args[arg_idx] not in (
                            "RESULT",
                            "OUTPUT",
                        ):
                            arg_idx += 1
                    else:
                        arg_idx += 1

                # Check if LTO is supported by trying to compile with -flto
                supported = False
                error_msg = ""
                try:
                    import tempfile

                    with tempfile.NamedTemporaryFile(suffix=".c", delete=False) as f:
                        f.write(b"int main() { return 0; }\n")
                        temp_src = f.name
                    temp_out = temp_src + ".out"
                    result = subprocess.run(
                        ["cc", "-flto", "-o", temp_out, temp_src],
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode == 0:
                        supported = True
                        Path(temp_out).unlink(missing_ok=True)
                    else:
                        error_msg = result.stderr
                    Path(temp_src).unlink(missing_ok=True)
                except Exception as e:
                    error_msg = str(e)

                if result_var:
                    ctx.variables[result_var] = "TRUE" if supported else "FALSE"
                if output_var:
                    ctx.variables[output_var] = error_msg

            case "check_cxx_compiler_flag":
                # check_cxx_compiler_flag(<flag> <var>)
                if len(args) >= 2:
                    flag = args[0]
                    result_var = args[1]

                    # Check if the C++ compiler accepts the flag
                    supported = False
                    try:
                        import tempfile

                        with tempfile.NamedTemporaryFile(
                            suffix=".cpp", delete=False
                        ) as f:
                            f.write(b"int main() { return 0; }\n")
                            temp_src = f.name
                        temp_out = temp_src + ".o"
                        result = subprocess.run(
                            ["c++", flag, "-c", "-o", temp_out, temp_src],
                            capture_output=True,
                            text=True,
                        )
                        # Check return code and that there are no warnings about unknown flags
                        if result.returncode == 0:
                            # Some compilers return 0 but warn about unknown flags
                            stderr_lower = result.stderr.lower()
                            if (
                                "unknown" not in stderr_lower
                                and "unrecognized" not in stderr_lower
                            ):
                                supported = True
                        Path(temp_out).unlink(missing_ok=True)
                        Path(temp_src).unlink(missing_ok=True)
                    except Exception:
                        pass

                    ctx.variables[result_var] = "1" if supported else ""

            case "check_c_compiler_flag":
                # check_c_compiler_flag(<flag> <var>)
                if len(args) >= 2:
                    flag = args[0]
                    result_var = args[1]

                    # Check if the C compiler accepts the flag
                    supported = False
                    try:
                        import tempfile

                        with tempfile.NamedTemporaryFile(
                            suffix=".c", delete=False
                        ) as f:
                            f.write(b"int main() { return 0; }\n")
                            temp_src = f.name
                        temp_out = temp_src + ".o"
                        result = subprocess.run(
                            ["cc", flag, "-c", "-o", temp_out, temp_src],
                            capture_output=True,
                            text=True,
                        )
                        # Check return code and that there are no warnings about unknown flags
                        if result.returncode == 0:
                            stderr_lower = result.stderr.lower()
                            if (
                                "unknown" not in stderr_lower
                                and "unrecognized" not in stderr_lower
                            ):
                                supported = True
                        Path(temp_out).unlink(missing_ok=True)
                        Path(temp_src).unlink(missing_ok=True)
                    except Exception:
                        pass

                    ctx.variables[result_var] = "1" if supported else ""

            case "check_cxx_symbol_exists":
                # check_cxx_symbol_exists(<symbol> <files> <variable>)
                if len(args) >= 3:
                    symbol = args[0]
                    # Files can be a semicolon-separated list or multiple args
                    # The last arg is the variable name
                    variable = args[-1]
                    files = args[1:-1]
                    # Handle semicolon-separated list
                    if len(files) == 1 and ";" in files[0]:
                        files = files[0].split(";")

                    # Check if the symbol exists by compiling a test program
                    found = False
                    try:
                        import tempfile

                        # Generate includes
                        includes = "\n".join(f"#include <{f}>" for f in files)
                        # Create test program that uses the symbol
                        test_code = f"""{includes}
int main() {{
    (void)({symbol});
    return 0;
}}
"""
                        with tempfile.NamedTemporaryFile(
                            suffix=".cpp", delete=False, mode="w"
                        ) as f:
                            f.write(test_code)
                            temp_src = f.name
                        temp_out = temp_src.replace(".cpp", "")
                        result = subprocess.run(
                            ["c++", "-o", temp_out, temp_src],
                            capture_output=True,
                            text=True,
                        )
                        if result.returncode == 0:
                            found = True
                        Path(temp_out).unlink(missing_ok=True)
                        Path(temp_src).unlink(missing_ok=True)
                    except Exception:
                        pass

                    ctx.variables[variable] = "1" if found else ""

            case "check_symbol_exists":
                # check_symbol_exists(<symbol> <files> <variable>)
                if len(args) >= 3:
                    symbol = args[0]
                    variable = args[-1]
                    files = args[1:-1]
                    if len(files) == 1 and ";" in files[0]:
                        files = files[0].split(";")

                    found = False
                    try:
                        import tempfile

                        includes = "\n".join(f"#include <{f}>" for f in files)
                        test_code = f"""{includes}
int main() {{
    (void)({symbol});
    return 0;
}}
"""
                        with tempfile.NamedTemporaryFile(
                            suffix=".c", delete=False, mode="w"
                        ) as f:
                            f.write(test_code)
                            temp_src = f.name
                        temp_out = temp_src.replace(".c", "")
                        result = subprocess.run(
                            ["cc", "-o", temp_out, temp_src],
                            capture_output=True,
                            text=True,
                        )
                        if result.returncode == 0:
                            found = True
                        Path(temp_out).unlink(missing_ok=True)
                        Path(temp_src).unlink(missing_ok=True)
                    except Exception:
                        pass

                    ctx.variables[variable] = "1" if found else ""

            case "add_library":
                if len(args) >= 2:
                    name = args[0]
                    # Check for STATIC/SHARED/OBJECT keyword
                    sources = args[1:]
                    lib_type = "STATIC"
                    if sources and sources[0] in ("STATIC", "SHARED", "OBJECT"):
                        lib_type = sources[0]
                        sources = sources[1:]
                    sources = [make_relative(s, ctx.source_dir) for s in sources]
                    ctx.libraries.append(
                        Library(
                            name=name,
                            sources=sources,
                            lib_type=lib_type,
                        )
                    )

            case "add_executable":
                if len(args) >= 2:
                    sources = [make_relative(s, ctx.source_dir) for s in args[1:]]
                    ctx.executables.append(Executable(name=args[0], sources=sources))

            case "target_link_libraries":
                if len(args) >= 2:
                    target_name = args[0]
                    libs = args[1:]
                    # Skip visibility keywords
                    libs = [
                        l for l in libs if l not in ("PUBLIC", "PRIVATE", "INTERFACE")
                    ]
                    exe = ctx.get_executable(target_name)
                    if exe:
                        exe.link_libraries.extend(libs)

            case "target_sources":
                if len(args) >= 2:
                    target_name = args[0]
                    sources = args[1:]
                    # Skip visibility keywords
                    sources = [
                        s
                        for s in sources
                        if s not in ("PUBLIC", "PRIVATE", "INTERFACE")
                    ]
                    sources = [make_relative(s, ctx.source_dir) for s in sources]
                    # Add sources to library or executable
                    lib = ctx.get_library(target_name)
                    if lib:
                        lib.sources.extend(sources)
                    else:
                        exe = ctx.get_executable(target_name)
                        if exe:
                            exe.sources.extend(sources)

            case "target_compile_features":
                if len(args) >= 2:
                    target_name = args[0]
                    # Parse features with visibility keywords
                    public_features: list[str] = []
                    target_features: list[str] = []
                    visibility = "PUBLIC"  # Default visibility
                    for arg in args[1:]:
                        if arg == "PUBLIC":
                            visibility = "PUBLIC"
                        elif arg == "INTERFACE":
                            visibility = "INTERFACE"
                        elif arg == "PRIVATE":
                            visibility = "PRIVATE"
                        else:
                            if visibility == "PUBLIC":
                                public_features.append(arg)
                                target_features.append(arg)
                            elif visibility == "INTERFACE":
                                public_features.append(arg)
                            else:
                                target_features.append(arg)
                    # Add features to library or executable
                    lib = ctx.get_library(target_name)
                    if lib:
                        lib.compile_features.extend(target_features)
                        lib.public_compile_features.extend(public_features)
                    else:
                        exe = ctx.get_executable(target_name)
                        if exe:
                            # Executables don't propagate, so all features go to compile_features
                            exe.compile_features.extend(target_features)
                            exe.compile_features.extend(public_features)

            case "target_include_directories":
                if len(args) >= 2:
                    target_name = args[0]
                    # Parse directories with visibility keywords
                    public_dirs: list[str] = []
                    target_dirs: list[str] = []
                    visibility = "PUBLIC"  # Default visibility
                    for arg in args[1:]:
                        if arg == "PUBLIC":
                            visibility = "PUBLIC"
                        elif arg == "INTERFACE":
                            visibility = "INTERFACE"
                        elif arg == "PRIVATE":
                            visibility = "PRIVATE"
                        elif arg == "SYSTEM":
                            # SYSTEM keyword is accepted but we don't differentiate
                            pass
                        else:
                            # Expand variables and resolve relative paths
                            expanded = expand_variables(
                                arg, ctx.variables, strict, cmd.line
                            )
                            if not Path(expanded).is_absolute():
                                expanded = str(ctx.source_dir / expanded)
                            if visibility == "PUBLIC":
                                public_dirs.append(expanded)
                                target_dirs.append(expanded)
                            elif visibility == "INTERFACE":
                                public_dirs.append(expanded)
                            else:
                                target_dirs.append(expanded)
                    # Add directories to library or executable
                    lib = ctx.get_library(target_name)
                    if lib:
                        lib.include_directories.extend(target_dirs)
                        lib.public_include_directories.extend(public_dirs)
                    else:
                        exe = ctx.get_executable(target_name)
                        if exe:
                            # Executables don't propagate, so all dirs go to include_directories
                            exe.include_directories.extend(target_dirs)
                            exe.include_directories.extend(public_dirs)

            case "target_compile_definitions":
                if len(args) >= 2:
                    target_name = args[0]
                    # Parse definitions with visibility keywords
                    public_defs: list[str] = []
                    target_defs: list[str] = []
                    visibility = "PUBLIC"  # Default visibility
                    for arg in args[1:]:
                        if arg == "PUBLIC":
                            visibility = "PUBLIC"
                        elif arg == "INTERFACE":
                            visibility = "INTERFACE"
                        elif arg == "PRIVATE":
                            visibility = "PRIVATE"
                        else:
                            # Expand variables
                            expanded = expand_variables(
                                arg, ctx.variables, strict, cmd.line
                            )
                            if visibility == "PUBLIC":
                                public_defs.append(expanded)
                                target_defs.append(expanded)
                            elif visibility == "INTERFACE":
                                public_defs.append(expanded)
                            else:
                                target_defs.append(expanded)
                    # Add definitions to library or executable
                    lib = ctx.get_library(target_name)
                    if lib:
                        lib.compile_definitions.extend(target_defs)
                        lib.public_compile_definitions.extend(public_defs)
                    else:
                        exe = ctx.get_executable(target_name)
                        if exe:
                            # Executables don't propagate, so all defs go to compile_definitions
                            exe.compile_definitions.extend(target_defs)
                            exe.compile_definitions.extend(public_defs)

            case "add_compile_options":
                # add_compile_options adds flags to all targets
                for arg in args:
                    expanded = expand_variables(arg, ctx.variables, strict, cmd.line)
                    ctx.compile_options.append(expanded)

            case "add_compile_definitions":
                # add_compile_definitions adds preprocessor definitions to all targets
                for arg in args:
                    expanded = expand_variables(arg, ctx.variables, strict, cmd.line)
                    ctx.compile_definitions.append(expanded)

            case "add_custom_command":
                # Minimal support: add_custom_command(OUTPUT ... COMMAND ... DEPENDS ... MAIN_DEPENDENCY ...)
                outputs: list[str] = []
                command: list[str] = []
                depends: list[str] = []
                main_dependency: str | None = None
                arg_idx = 0
                current_section = None
                while arg_idx < len(args):
                    arg = args[arg_idx]
                    if arg in ("OUTPUT", "COMMAND", "DEPENDS", "MAIN_DEPENDENCY"):
                        current_section = arg
                    else:
                        arg = expand_variables(arg, ctx.variables, strict, cmd.line)
                        if current_section == "OUTPUT":
                            outputs.append(arg)
                        elif current_section == "COMMAND":
                            command.append(arg)
                        elif current_section == "DEPENDS":
                            depends.append(arg)
                        elif current_section == "MAIN_DEPENDENCY":
                            main_dependency = arg
                    arg_idx += 1

                if outputs and command:
                    ctx.custom_commands.append(
                        {
                            "outputs": outputs,
                            "command": command,
                            "depends": depends,
                            "main_dependency": main_dependency,
                        }
                    )

            case "add_test":
                # Support: add_test(NAME <name> COMMAND <command> ...)
                # Or: add_test(<name> <command> ...)
                if len(args) >= 2:
                    test_name = ""
                    test_command = []
                    if args[0] == "NAME":
                        # NAME ... COMMAND ...
                        test_name = expand_variables(
                            args[1], ctx.variables, strict, cmd.line
                        )
                        if "COMMAND" in args:
                            cmd_idx = args.index("COMMAND")
                            test_command = [
                                expand_variables(a, ctx.variables, strict, cmd.line)
                                for a in args[cmd_idx + 1 :]
                            ]
                    else:
                        # <name> <command> ...
                        test_name = expand_variables(
                            args[0], ctx.variables, strict, cmd.line
                        )
                        test_command = [
                            expand_variables(a, ctx.variables, strict, cmd.line)
                            for a in args[1:]
                        ]

                    if test_name and test_command:
                        ctx.tests.append(Test(name=test_name, command=test_command))

            case "set_source_files_properties":
                if "PROPERTIES" in args:
                    prop_idx = args.index("PROPERTIES")
                    files = args[:prop_idx]
                    props = args[prop_idx + 1 :]

                    for filename in files:
                        expanded_filename = expand_variables(
                            filename, ctx.variables, strict, cmd.line
                        )
                        if not Path(expanded_filename).is_absolute():
                            expanded_filename = str(ctx.source_dir / expanded_filename)

                        if expanded_filename not in ctx.source_file_properties:
                            ctx.source_file_properties[expanded_filename] = (
                                SourceFileProperties()
                            )

                        file_props = ctx.source_file_properties[expanded_filename]

                        # Parse properties in pairs
                        i = 0
                        while i < len(props):
                            prop_name = props[i]
                            i += 1
                            if i < len(props):
                                prop_value = props[i]
                                i += 1
                                # Handle semicolon-separated lists in CMake
                                values = prop_value.split(";")
                                expanded_values = [
                                    expand_variables(v, ctx.variables, strict, cmd.line)
                                    for v in values
                                ]

                                if prop_name == "OBJECT_DEPENDS":
                                    for v in expanded_values:
                                        if not Path(v).is_absolute():
                                            v = str(ctx.source_dir / v)
                                        v = make_relative(v, ctx.source_dir)
                                        file_props.object_depends.append(v)
                                elif prop_name == "INCLUDE_DIRECTORIES":
                                    for v in expanded_values:
                                        if not Path(v).is_absolute():
                                            v = str(ctx.source_dir / v)
                                        v = make_relative(v, ctx.source_dir)
                                        file_props.include_directories.append(v)
                                elif prop_name == "COMPILE_DEFINITIONS":
                                    file_props.compile_definitions.extend(
                                        expanded_values
                                    )

            case "find_program":
                if len(args) >= 2:
                    var_name = args[0]
                    # Parse arguments: find_program(VAR name1 [name2...] [NAMES name1...] [REQUIRED])
                    names: list[str] = []
                    required = False
                    arg_idx = 1
                    while arg_idx < len(args):
                        arg = args[arg_idx]
                        if arg == "REQUIRED":
                            required = True
                        elif arg == "NAMES":
                            # Collect names until next keyword or end
                            arg_idx += 1
                            while arg_idx < len(args) and args[arg_idx] not in (
                                "REQUIRED",
                                "PATHS",
                                "HINTS",
                                "DOC",
                            ):
                                names.append(args[arg_idx])
                                arg_idx += 1
                            continue
                        elif arg not in ("PATHS", "HINTS", "DOC", "NO_CACHE"):
                            names.append(arg)
                        arg_idx += 1

                    # Search for program
                    found_path = None
                    for name in names:
                        found_path = shutil.which(name)
                        if found_path:
                            break

                    if found_path:
                        ctx.variables[var_name] = found_path
                    else:
                        ctx.variables[var_name] = f"{var_name}-NOTFOUND"
                        if required:
                            raise FileNotFoundError(
                                f"Could not find program: {' or '.join(names)}"
                            )

            case "find_package":
                if args:
                    package_name = args[0]
                    required = "REQUIRED" in args

                    if package_name == "GTest":
                        # Try to find GTest using pkg-config
                        found = False
                        try:
                            result = subprocess.run(
                                ["pkg-config", "--exists", "gtest"],
                                capture_output=True,
                            )
                            if result.returncode == 0:
                                found = True
                                # Get cflags and libs
                                cflags_result = subprocess.run(
                                    ["pkg-config", "--cflags", "gtest"],
                                    capture_output=True,
                                    text=True,
                                )
                                libs_result = subprocess.run(
                                    ["pkg-config", "--libs", "gtest"],
                                    capture_output=True,
                                    text=True,
                                )
                                gtest_cflags = cflags_result.stdout.strip()
                                gtest_libs = libs_result.stdout.strip()
                                ctx.variables["GTEST_INCLUDE_DIRS"] = gtest_cflags
                                ctx.variables["GTEST_LIBRARIES"] = gtest_libs

                                # Register GTest::gtest imported target
                                ctx.imported_targets["GTest::gtest"] = ImportedTarget(
                                    cflags=gtest_cflags,
                                    libs=gtest_libs,
                                )

                                # Also try gtest_main
                                main_result = subprocess.run(
                                    ["pkg-config", "--libs", "gtest_main"],
                                    capture_output=True,
                                    text=True,
                                )
                                if main_result.returncode == 0:
                                    gtest_main_libs = main_result.stdout.strip()
                                    ctx.variables["GTEST_MAIN_LIBRARIES"] = (
                                        gtest_main_libs
                                    )
                                    ctx.variables["GTEST_BOTH_LIBRARIES"] = (
                                        gtest_libs + " " + gtest_main_libs
                                    )
                                    # Register GTest::gtest_main imported target
                                    ctx.imported_targets["GTest::gtest_main"] = (
                                        ImportedTarget(
                                            cflags=gtest_cflags,
                                            libs=gtest_main_libs,
                                        )
                                    )
                        except FileNotFoundError:
                            pass  # pkg-config not available

                        if found:
                            ctx.variables["GTest_FOUND"] = "TRUE"
                            ctx.variables["GTEST_FOUND"] = "TRUE"
                        else:
                            ctx.variables["GTest_FOUND"] = "FALSE"
                            ctx.variables["GTEST_FOUND"] = "FALSE"
                            if required:
                                raise FileNotFoundError("Could not find package: GTest")
                    elif package_name == "Threads":
                        # Threads is always available on Unix-like systems
                        ctx.variables["Threads_FOUND"] = "TRUE"
                        ctx.variables["CMAKE_THREAD_LIBS_INIT"] = "-pthread"
                        ctx.variables["CMAKE_USE_PTHREADS_INIT"] = "TRUE"
                        # Register the imported target
                        ctx.imported_targets["Threads::Threads"] = ImportedTarget(
                            libs="-pthread"
                        )
                    else:
                        # Unknown package
                        ctx.variables[f"{package_name}_FOUND"] = "FALSE"
                        if required:
                            raise FileNotFoundError(
                                f"Could not find package: {package_name}"
                            )

            case "message":
                if args:
                    # Check for mode keyword
                    modes = (
                        "STATUS",
                        "WARNING",
                        "AUTHOR_WARNING",
                        "SEND_ERROR",
                        "FATAL_ERROR",
                        "DEPRECATION",
                    )
                    mode = ""
                    message_parts = args
                    if args[0] in modes:
                        mode = args[0]
                        message_parts = args[1:]

                    message = " ".join(message_parts)

                    if mode == "FATAL_ERROR":
                        error_label = colored("error:", "red", attrs=["bold"])
                        print(
                            f"CMakeLists.txt:{cmd.line}: {error_label} {message}",
                            file=sys.stderr,
                        )
                        raise SystemExit(1)
                    elif mode == "SEND_ERROR":
                        error_label = colored("error:", "red", attrs=["bold"])
                        print(
                            f"CMakeLists.txt:{cmd.line}: {error_label} {message}",
                            file=sys.stderr,
                        )
                    elif mode in ("WARNING", "AUTHOR_WARNING", "DEPRECATION"):
                        warning_label = colored("warning:", "magenta", attrs=["bold"])
                        print(
                            f"CMakeLists.txt:{cmd.line}: {warning_label} {message}",
                            file=sys.stderr,
                        )
                    elif mode == "STATUS":
                        print(f"{message}")
                    else:
                        print(message)

            case "execute_process":
                # Parse execute_process arguments
                commands_list: list[list[str]] = []
                current_command: list[str] = []
                working_directory: str | None = None
                result_variable: str | None = None
                output_variable: str | None = None
                error_variable: str | None = None
                output_strip = False
                error_strip = False

                arg_idx = 0
                while arg_idx < len(args):
                    arg = args[arg_idx]
                    if arg == "COMMAND":
                        if current_command:
                            commands_list.append(current_command)
                        current_command = []
                    elif arg == "WORKING_DIRECTORY":
                        arg_idx += 1
                        if arg_idx < len(args):
                            working_directory = expand_variables(
                                args[arg_idx], ctx.variables, strict, cmd.line
                            )
                    elif arg == "RESULT_VARIABLE":
                        arg_idx += 1
                        if arg_idx < len(args):
                            result_variable = args[arg_idx]
                    elif arg == "OUTPUT_VARIABLE":
                        arg_idx += 1
                        if arg_idx < len(args):
                            output_variable = args[arg_idx]
                    elif arg == "ERROR_VARIABLE":
                        arg_idx += 1
                        if arg_idx < len(args):
                            error_variable = args[arg_idx]
                    elif arg == "OUTPUT_STRIP_TRAILING_WHITESPACE":
                        output_strip = True
                    elif arg == "ERROR_STRIP_TRAILING_WHITESPACE":
                        error_strip = True
                    elif arg in (
                        "INPUT_FILE",
                        "OUTPUT_FILE",
                        "ERROR_FILE",
                        "TIMEOUT",
                        "COMMAND_ECHO",
                        "OUTPUT_QUIET",
                        "ERROR_QUIET",
                        "COMMAND_ERROR_IS_FATAL",
                        "ENCODING",
                    ):
                        # Skip unsupported options and their values
                        if arg not in ("OUTPUT_QUIET", "ERROR_QUIET"):
                            arg_idx += 1
                    else:
                        # Part of current command
                        current_command.append(
                            expand_variables(arg, ctx.variables, strict, cmd.line)
                        )
                    arg_idx += 1

                if current_command:
                    commands_list.append(current_command)

                # Execute the commands (piped together if multiple)
                if commands_list:
                    try:
                        # For now, only support single command (no piping)
                        cmd = commands_list[0]
                        result = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            cwd=working_directory,
                        )

                        if result_variable:
                            ctx.variables[result_variable] = str(result.returncode)

                        if output_variable:
                            output = result.stdout
                            if output_strip:
                                output = output.rstrip()
                            ctx.variables[output_variable] = output

                        if error_variable:
                            error = result.stderr
                            if error_strip:
                                error = error.rstrip()
                            ctx.variables[error_variable] = error

                    except FileNotFoundError:
                        if result_variable:
                            ctx.variables[result_variable] = "1"

            case _:
                # Check if this is a user-defined function call
                func_name = cmd.name.lower()
                if func_name in ctx.functions:
                    func_def = ctx.functions[func_name]
                    # Save current variables for function scope
                    saved_vars = ctx.variables.copy()

                    # Set up function arguments
                    # ARGC = number of arguments
                    ctx.variables["ARGC"] = str(len(args))
                    # ARGV = all arguments as semicolon-separated list
                    ctx.variables["ARGV"] = ";".join(args)
                    # ARGVn = individual arguments
                    for idx, arg in enumerate(args):
                        ctx.variables[f"ARGV{idx}"] = arg
                    # Named parameters
                    for idx, param in enumerate(func_def.params):
                        if idx < len(args):
                            ctx.variables[param] = args[idx]
                        else:
                            ctx.variables[param] = ""
                    # ARGN = arguments after named parameters
                    extra_args = args[len(func_def.params) :]
                    ctx.variables["ARGN"] = ";".join(extra_args)

                    # Clear parent_scope_vars before calling
                    ctx.parent_scope_vars.clear()

                    # Execute function body
                    try:
                        process_commands(func_def.body, ctx, trace, strict)
                    except ReturnFromFunction:
                        # return() was called, exit function early
                        pass

                    # Apply PARENT_SCOPE changes to saved_vars
                    for var_name, var_value in ctx.parent_scope_vars.items():
                        saved_vars[var_name] = var_value
                    ctx.parent_scope_vars.clear()

                    # Restore variables
                    ctx.variables = saved_vars
                elif strict:
                    error_label = colored("error:", "red", attrs=["bold"])
                    print(
                        f"CMakeLists.txt:{cmd.line}: {error_label} unsupported command: {cmd.name}()",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                # Ignore unknown commands by default

        i += 1


def generate_ninja(ctx: BuildContext, output_path: Path, builddir: str) -> None:
    """Generate ninja build file."""
    # Detect compiler
    cc = "cc"
    cxx = "c++"

    # Detect extensions
    exe_ext = ".exe" if platform.system() == "Windows" else ""
    lib_ext = ".lib" if platform.system() == "Windows" else ".a"

    # Determine build type flags
    build_type = ctx.variables.get("CMAKE_BUILD_TYPE", "Debug").upper()
    build_type_flags = ""
    if build_type == "DEBUG":
        build_type_flags = "-g -O0"
    elif build_type == "RELEASE":
        build_type_flags = "-O3 -DNDEBUG"
    elif build_type == "RELWITHDEBINFO":
        build_type_flags = "-O2 -g -DNDEBUG"
    elif build_type == "MINSIZEREL":
        build_type_flags = "-Os -DNDEBUG"

    with open(output_path, "w") as f:
        n = Writer(f)

        n.comment("Generated by cninja")
        n.newline()

        # Variables
        n.variable("builddir", builddir)
        n.variable("cc", cc)
        n.variable("cxx", cxx)
        n.variable("ar", "ar")
        n.newline()

        # Compile rules - include build type flags
        base_cflags = f"-fdiagnostics-color {build_type_flags}".strip()
        n.rule(
            "cc",
            command=f"$cc -MMD -MF $out.d {base_cflags} $cflags -c $in -o $out",
            depfile="$out.d",
            description="CC $out",
        )
        n.newline()

        n.rule(
            "cxx",
            command=f"$cxx -MMD -MF $out.d {base_cflags} $cflags -c $in -o $out",
            depfile="$out.d",
            description="CXX $out",
        )
        n.newline()

        # Archive rule for static libraries
        n.rule(
            "ar",
            command="$ar rcs $out $in",
            description="AR $out",
        )
        n.newline()

        # Link rules
        n.rule(
            "link",
            command="$cc $in -o $out $libs",
            description="LINK $out",
        )
        n.newline()

        n.rule(
            "link_cxx",
            command="$cxx $in -o $out $libs",
            description="LINK $out",
        )
        n.newline()

        # Track library and executable outputs for linking and testing
        lib_outputs: dict[str, str] = {}
        exe_outputs: dict[str, str] = {}
        object_lib_objects: dict[str, list[str]] = {}
        custom_command_outputs: set[str] = set()

        # Generate custom command rule
        n.rule(
            "custom_command",
            command="$cmd",
            description="CUSTOM $out",
        )
        n.newline()

        # Generate custom commands
        for custom_cmd in ctx.custom_commands:
            outputs = []
            for o in custom_cmd["outputs"]:  # type: ignore
                if not Path(o).is_absolute():
                    prefixed_o = f"$builddir/{o}"
                    outputs.append(prefixed_o)
                    custom_command_outputs.add(o)
                else:
                    outputs.append(o)
            command = custom_cmd["command"]  # type: ignore
            depends = [
                f"$builddir/{d}"
                if d in custom_command_outputs and not Path(d).is_absolute()
                else d
                for d in custom_cmd["depends"]  # type: ignore
            ]
            main_dep = custom_cmd.get("main_dependency")  # type: ignore
            if main_dep:
                if (
                    main_dep in custom_command_outputs
                    and not Path(main_dep).is_absolute()
                ):
                    main_dep = f"$builddir/{main_dep}"
                depends.insert(0, main_dep)

            cmd_str = " ".join(str(c) for c in command)
            n.build(
                outputs,
                "custom_command",
                depends,
                variables={"cmd": cmd_str},
            )
            n.newline()

        # Generate build statements for libraries
        for lib in ctx.libraries:
            objects: list[str] = []

            # Collect compile flags from global options, compile definitions, compile features, and include dirs
            lib_compile_flags: list[str] = list(ctx.compile_options)
            for definition in ctx.compile_definitions:
                lib_compile_flags.append(f"-D{definition}")
            for definition in lib.compile_definitions:
                lib_compile_flags.append(f"-D{definition}")
            for feature in lib.compile_features:
                flag = compile_feature_to_flag(feature)
                if flag:
                    lib_compile_flags.append(flag)
            for inc_dir in lib.include_directories:
                lib_compile_flags.append(f"-I{inc_dir}")

            lib_compile_vars: dict[str, str] | None = None
            if lib_compile_flags:
                lib_compile_vars = {"cflags": " ".join(lib_compile_flags)}

            for source in lib.sources:
                actual_source = source
                if source in custom_command_outputs:
                    actual_source = f"$builddir/{source}"

                obj_name = f"$builddir/{lib.name}_{Path(source).stem}.o"
                objects.append(obj_name)

                # Determine if C or C++
                if source.endswith((".cpp", ".cxx", ".cc", ".C")):
                    rule = "cxx"
                else:
                    rule = "cc"

                # Check for source file properties
                abs_source = str(ctx.source_dir / source)
                file_props = ctx.source_file_properties.get(abs_source)

                source_compile_flags = list(lib_compile_flags)
                source_depends = []

                if file_props:
                    for definition in file_props.compile_definitions:
                        source_compile_flags.append(f"-D{definition}")
                    for inc_dir in file_props.include_directories:
                        source_compile_flags.append(f"-I{inc_dir}")
                    for d in file_props.object_depends:
                        if d in custom_command_outputs:
                            source_depends.append(f"$builddir/{d}")
                        else:
                            source_depends.append(d)

                source_vars = None
                if source_compile_flags:
                    source_vars = {"cflags": " ".join(source_compile_flags)}

                n.build(
                    obj_name,
                    rule,
                    actual_source,
                    implicit=source_depends,
                    variables=source_vars,
                )

            if lib.lib_type == "OBJECT":
                # Object libraries don't produce an archive, just track objects
                object_lib_objects[lib.name] = objects
                n.newline()
            elif lib.lib_type == "STATIC":
                # Create static library archive
                lib_name = f"$builddir/lib{lib.name}{lib_ext}"
                n.build(lib_name, "ar", objects)
                n.newline()
                lib_outputs[lib.name] = lib_name

        # Generate build statements for executables
        default_targets: list[str] = []

        for exe in ctx.executables:
            objects: list[str] = []
            uses_cxx = False

            # Collect cflags from global options, compile definitions, compile features, include dirs, linked libraries, and imported targets
            compile_flags: list[str] = list(ctx.compile_options)
            for definition in ctx.compile_definitions:
                compile_flags.append(f"-D{definition}")
            for definition in exe.compile_definitions:
                compile_flags.append(f"-D{definition}")
            for feature in exe.compile_features:
                flag = compile_feature_to_flag(feature)
                if flag:
                    compile_flags.append(flag)
            for inc_dir in exe.include_directories:
                compile_flags.append(f"-I{inc_dir}")
            for lib_name in exe.link_libraries:
                # Check for public compile features from linked libraries
                linked_lib = ctx.get_library(lib_name)
                if linked_lib:
                    for feature in linked_lib.public_compile_features:
                        flag = compile_feature_to_flag(feature)
                        if flag and flag not in compile_flags:
                            compile_flags.append(flag)
                    # Check for public include directories from linked libraries
                    for inc_dir in linked_lib.public_include_directories:
                        inc_flag = f"-I{inc_dir}"
                        if inc_flag not in compile_flags:
                            compile_flags.append(inc_flag)
                    # Check for public compile definitions from linked libraries
                    for definition in linked_lib.public_compile_definitions:
                        def_flag = f"-D{definition}"
                        if def_flag not in compile_flags:
                            compile_flags.append(def_flag)
                # Check for cflags from imported targets
                if lib_name in ctx.imported_targets:
                    imported = ctx.imported_targets[lib_name]
                    if imported.cflags:
                        compile_flags.append(imported.cflags)

            compile_vars: dict[str, str] | None = None
            if compile_flags:
                compile_vars = {"cflags": " ".join(compile_flags)}

            for source in exe.sources:
                actual_source = source
                if source in custom_command_outputs:
                    actual_source = f"$builddir/{source}"

                obj_name = f"$builddir/{exe.name}_{Path(source).stem}.o"
                objects.append(obj_name)

                # Determine if C or C++
                if source.endswith((".cpp", ".cxx", ".cc", ".C")):
                    rule = "cxx"
                    uses_cxx = True
                else:
                    rule = "cc"

                # Check for source file properties
                abs_source = str(ctx.source_dir / source)
                file_props = ctx.source_file_properties.get(abs_source)

                source_compile_flags = list(compile_flags)
                source_depends = []

                if file_props:
                    for definition in file_props.compile_definitions:
                        source_compile_flags.append(f"-D{definition}")
                    for inc_dir in file_props.include_directories:
                        source_compile_flags.append(f"-I{inc_dir}")
                    for d in file_props.object_depends:
                        if d in custom_command_outputs:
                            source_depends.append(f"$builddir/{d}")
                        else:
                            source_depends.append(d)

                source_vars = None
                if source_compile_flags:
                    source_vars = {"cflags": " ".join(source_compile_flags)}

                n.build(
                    obj_name,
                    rule,
                    actual_source,
                    implicit=source_depends,
                    variables=source_vars,
                )

            # Add linked libraries to inputs
            link_inputs = objects.copy()
            link_flags: list[str] = []
            for lib_name in exe.link_libraries:
                if lib_name in object_lib_objects:
                    # Object library: add object files directly
                    link_inputs.extend(object_lib_objects[lib_name])
                elif lib_name in lib_outputs:
                    # Static library: add archive
                    link_inputs.append(lib_outputs[lib_name])
                elif lib_name in ctx.imported_targets:
                    # Imported target (e.g., Threads::Threads): add link flags
                    imported = ctx.imported_targets[lib_name]
                    if imported.libs:
                        link_flags.append(imported.libs)

            # Link
            exe_name = f"$builddir/{exe.name}{exe_ext}"
            link_rule = "link_cxx" if uses_cxx else "link"
            variables: dict[str, str] = {}
            if link_flags:
                variables["libs"] = " ".join(link_flags)
            n.build(
                exe_name,
                link_rule,
                link_inputs,
                variables=variables if variables else None,
            )
            n.newline()

            exe_outputs[exe.name] = exe_name
            default_targets.append(exe_name)

        # Generate test runner
        if ctx.tests:
            n.rule(
                "test_run",
                command="$cmd",
                description="TEST $name",
                pool="console",
            )
            n.newline()

            test_targets: list[str] = []
            for test in ctx.tests:
                # Resolve target in command
                cmd = list(test.command)
                depends = []
                if cmd[0] in exe_outputs:
                    target_exe = exe_outputs[cmd[0]]
                    cmd[0] = target_exe
                    depends.append(target_exe)

                test_target = f"test_{test.name}"
                n.build(
                    test_target,
                    "test_run",
                    implicit=depends,
                    variables={
                        "cmd": " ".join(cmd),
                        "name": test.name,
                    },
                )
                test_targets.append(test_target)

            n.newline()
            n.build("test", "phony", test_targets)
            n.newline()

        # Default target
        if default_targets:
            n.default(default_targets)


def configure(
    source_dir: Path,
    build_dir: str,
    variables: dict[str, str] | None = None,
    trace: bool = False,
    strict: bool = False,
) -> None:
    """Configure a CMake project and generate build.ninja.

    Args:
        source_dir: Path to source directory containing CMakeLists.txt
        build_dir: Relative path for build directory (e.g., "build")
        variables: Optional dict of variables to set (e.g., from -D flags)
        trace: If True, print each command as it's processed
        strict: If True, error on unsupported commands instead of ignoring them
    """
    source_dir = source_dir.resolve()
    cmake_file = source_dir / "CMakeLists.txt"
    if not cmake_file.exists():
        raise FileNotFoundError(f"CMakeLists.txt not found in {source_dir}")

    from .parser import parse_file

    commands = parse_file(cmake_file)

    ctx = BuildContext(
        source_dir=source_dir,
        build_dir=source_dir / build_dir,
    )

    # Set variables from command line (-D flags) first
    # These are cache variables that won't be overridden by set()
    if variables:
        ctx.variables.update(variables)
        ctx.cache_variables.update(variables.keys())

    # Set up standard CMake variables
    ctx.variables["CMAKE_SOURCE_DIR"] = str(ctx.source_dir)
    ctx.variables["CMAKE_BINARY_DIR"] = str(ctx.build_dir)

    process_commands(commands, ctx, trace, strict)

    # Generate ninja manifest in source directory (named after build dir)
    output_path = source_dir / f"{build_dir}.ninja"
    generate_ninja(ctx, output_path, build_dir)

    # Create build directory
    ctx.build_dir.mkdir(parents=True, exist_ok=True)

    print(f"{colored('Configured', 'green', attrs=['bold'])} {build_dir}.ninja")
