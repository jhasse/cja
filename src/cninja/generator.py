"""Ninja build file generator."""

from dataclasses import dataclass, field
import hashlib
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, cast

from .utils import make_relative, strip_generator_expressions
from .syntax import (
    FetchContentInfo,
    SourceFileProperties,
    Test,
    evaluate_condition,
    find_else_or_elseif,
)
from .build_context import (
    BuildContext,
    CustomCommand,
    find_matching_endforeach,
    find_matching_endif,
)
from .commands import (
    handle_add_executable,
    handle_add_library,
    handle_file,
    handle_function,
    handle_get_directory_property,
    handle_get_filename_component,
    handle_get_property,
    handle_include_directories,
    handle_cmake_parse_arguments,
    handle_list,
    handle_macro,
    handle_math,
    handle_option,
    handle_set,
    handle_set_property,
    handle_set_target_properties,
    handle_string,
    handle_target_compile_definitions,
    handle_target_compile_features,
    handle_target_include_directories,
    handle_target_link_directories,
    handle_target_link_libraries,
    handle_target_sources,
    handle_unset,
)

from .targets import ImportedTarget, InstallTarget

from rich.progress import (
    Progress,
    DownloadColumn,
    TransferSpeedColumn,
    BarColumn,
    TextColumn,
    TimeRemainingColumn,
)
from termcolor import colored

from .ninja_syntax import Writer
from .parser import Command


class ReturnFromFunction(Exception):
    """Exception raised to exit early from a function."""

    pass


@dataclass
class Frame:
    commands: list[Command] | None
    pc: int = 0
    on_exit: Callable[[], None] | None = None
    kind: str = "commands"
    foreach_items: list[str] = field(default_factory=list)
    foreach_index: int = 0
    foreach_loop_var: str = ""
    foreach_body: list[Command] | None = None
    fetchcontent_names: list[str] = field(default_factory=list)
    fetchcontent_index: int = 0
    fetchcontent_cmd: Command | None = None
    fetchcontent_make_available: bool = True


def is_header(filename: str) -> bool:
    """Check if a filename refers to a header file."""
    header_extensions = (".h", ".hpp", ".hxx", ".hh", ".inc", ".inl")
    return filename.lower().endswith(header_extensions)


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


def framework_link_flags(lib_path: str) -> list[str] | None:
    """Return macOS framework link flags if lib_path refers to a framework."""
    if platform.system() != "Darwin":
        return None
    if ".framework" not in lib_path:
        return None
    idx = lib_path.find(".framework")
    framework_path = lib_path[: idx + len(".framework")]
    framework_name = Path(framework_path).stem
    framework_dir = str(Path(framework_path).parent)
    flags = []
    if framework_dir:
        flags.append(f"-F{framework_dir}")
    flags.extend(["-framework", framework_name])
    return flags


def _ninja_flag_path(path: str) -> str:
    """Format paths for Ninja flags consistently on Windows."""
    if len(path) >= 3 and path[1] == ":" and path[2] == "\\":
        head, sep, tail = path.rpartition("\\")
        if sep:
            return f"{head}/{tail}"
    return path


def handle_add_subdirectory(
    ctx: BuildContext,
    cmd: Command,
    args: list[str],
    trace: bool,
    strict: bool,
) -> None:
    """Handle add_subdirectory() command."""
    if args:
        sub_dir_name = args[0]
        sub_source_dir = ctx.current_source_dir / sub_dir_name
        if not sub_source_dir.exists():
            # Try relative to the root source dir as well?
            # CMake usually expects it relative to current source dir.
            pass

        sub_cmakelists = sub_source_dir / "CMakeLists.txt"
        if sub_cmakelists.exists():
            from .parser import parse_file

            ctx.record_cmake_file(sub_cmakelists)
            sub_commands = parse_file(sub_cmakelists)

            # Save current state
            saved_current_source_dir = ctx.current_source_dir
            saved_current_list_file = ctx.current_list_file
            saved_parent_directory = ctx.parent_directory
            saved_vars = ctx.variables.copy()
            ctx.parent_scope_vars = {}

            # Update current_source_dir for the subdirectory
            ctx.current_source_dir = sub_source_dir
            ctx.current_list_file = sub_cmakelists
            ctx.parent_directory = str(saved_current_source_dir)
            ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] = str(sub_source_dir)
            ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(sub_cmakelists)
            ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(sub_cmakelists.parent)
            # For now, CMAKE_CURRENT_BINARY_DIR is the same as CMAKE_BINARY_DIR
            # since we don't support separate binary dirs for subdirectories yet
            ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(ctx.build_dir)

            try:
                process_commands(sub_commands, ctx, trace, strict)
            finally:
                # Apply PARENT_SCOPE changes
                parent_scope_updates = ctx.parent_scope_vars

                # Restore state
                ctx.current_source_dir = saved_current_source_dir
                ctx.current_list_file = saved_current_list_file
                ctx.parent_directory = saved_parent_directory
                ctx.variables = saved_vars
                for var, val in parent_scope_updates.items():
                    if val is None:
                        ctx.variables.pop(var, None)
                    else:
                        ctx.variables[var] = val
        elif strict:
            ctx.print_error(
                f'add_subdirectory given source "{sub_dir_name}" which does not exist.',
                cmd.line,
            )
            sys.exit(1)


def select_if_block(
    ctx: BuildContext,
    commands: list[Command],
    pc: int,
    strict: bool,
) -> tuple[int, tuple[int, int] | None]:
    """Select the if/elseif/else block to execute."""
    cmd = commands[pc]
    # Find matching endif
    endif_idx = find_matching_endif(commands, pc, ctx)
    # Find elseif/else blocks
    blocks = find_else_or_elseif(commands, pc, endif_idx)

    block_start = pc + 1

    def _is_empty_string_token(token: str) -> bool:
        return token == "" or token in ('""', "''")

    def _is_exact_var_token(token: str) -> bool:
        return (
            (token.startswith("${") and token.endswith("}"))
            or (token.startswith("\"${") and token.endswith("}\""))
            or (token.startswith("'${") and token.endswith("}'"))
        )

    # Check the if condition
    if_args = []
    for i, arg in enumerate(cmd.args):
        allow_undefined = (
            i + 2 < len(cmd.args)
            and cmd.args[i + 1] == "STREQUAL"
            and _is_empty_string_token(cmd.args[i + 2])
            and _is_exact_var_token(arg)
        )
        if_args.append(ctx.expand_variables(arg, strict, cmd.line, allow_undefined))
    if evaluate_condition(if_args, ctx.variables):
        # Execute commands from if to first elseif/else or endif
        block_end = blocks[0][1] if blocks else endif_idx
        return endif_idx, (block_start, block_end)

    # Check elseif/else blocks
    for j, (block_type, block_idx, block_args) in enumerate(blocks):
        if block_type == "elseif":
            elseif_args = []
            for i, arg in enumerate(block_args):
                allow_undefined = (
                    i + 2 < len(block_args)
                    and block_args[i + 1] == "STREQUAL"
                    and _is_empty_string_token(block_args[i + 2])
                    and _is_exact_var_token(arg)
                )
                elseif_args.append(
                    ctx.expand_variables(
                        arg, strict, commands[block_idx].line, allow_undefined
                    )
                )
            if evaluate_condition(elseif_args, ctx.variables):
                block_start = block_idx + 1
                block_end = blocks[j + 1][1] if j + 1 < len(blocks) else endif_idx
                return endif_idx, (block_start, block_end)
        elif block_type == "else":
            block_start = block_idx + 1
            return endif_idx, (block_start, endif_idx)

    return endif_idx, None


def build_foreach_info(
    ctx: BuildContext,
    commands: list[Command],
    pc: int,
    args: list[str],
) -> tuple[int, str, list[str], list[Command]]:
    """Build foreach() iteration info."""
    cmd = commands[pc]
    if not args:
        ctx.raise_syntax_error("foreach() requires at least a loop variable", cmd.line)

    # Find matching endforeach
    endforeach_idx = find_matching_endforeach(commands, pc, ctx)
    body = commands[pc + 1 : endforeach_idx]

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

    return endforeach_idx, loop_var, items, body


def process_commands(
    commands: list[Command],
    ctx: BuildContext,
    trace: bool = False,
    strict: bool = False,
) -> None:
    """Process CMake commands and populate the build context."""
    # Ensure CMAKE_COMMAND is always set
    ctx.variables["CMAKE_COMMAND"] = "cninja"
    ctx.variables["CMAKE_VERSION"] = "3.28.0"
    stack: list[Frame] = [Frame(commands=commands, pc=0, kind="commands")]
    while stack:
        frame = stack[-1]
        if frame.kind == "foreach":
            if frame.foreach_index >= len(frame.foreach_items):
                if frame.on_exit:
                    frame.on_exit()
                stack.pop()
                continue
            ctx.variables[frame.foreach_loop_var] = frame.foreach_items[
                frame.foreach_index
            ]
            frame.foreach_index += 1
            stack.append(Frame(commands=frame.foreach_body, pc=0, kind="commands"))
            continue
        if frame.kind == "fetchcontent":
            if frame.fetchcontent_index >= len(frame.fetchcontent_names):
                if frame.on_exit:
                    frame.on_exit()
                stack.pop()
                continue
            name = frame.fetchcontent_names[frame.fetchcontent_index]
            frame.fetchcontent_index += 1
            info = ctx.fetched_content.get(name.lower())
            if not info:
                if strict:
                    cmd_line = (
                        frame.fetchcontent_cmd.line if frame.fetchcontent_cmd else 0
                    )
                    ctx.print_error(
                        f"FetchContent_MakeAvailable called for undeclared content: {name}",
                        cmd_line,
                    )
                    sys.exit(1)
                continue

            url = None
            url_hash = None
            arg_idx = 0
            while arg_idx < len(info.args):
                if info.args[arg_idx] == "URL" and arg_idx + 1 < len(info.args):
                    url = info.args[arg_idx + 1]
                    arg_idx += 2
                elif info.args[arg_idx] == "URL_HASH" and arg_idx + 1 < len(info.args):
                    url_hash = info.args[arg_idx + 1]
                    arg_idx += 2
                else:
                    arg_idx += 1

            if url:
                deps_dir = ctx.build_dir / "_deps"
                deps_dir.mkdir(parents=True, exist_ok=True)

                src_dir = deps_dir / f"{name.lower()}-src"

                if not src_dir.exists():
                    print(f"Downloading {name} from {url}")
                    download_file = deps_dir / Path(url).name

                    with Progress(
                        TextColumn("[bold blue]{task.description}"),
                        BarColumn(),
                        DownloadColumn(),
                        TransferSpeedColumn(),
                        "•",
                        TimeRemainingColumn(),
                    ) as progress:
                        task_id = progress.add_task(description="", total=None)

                        with urllib.request.urlopen(url) as response:
                            total_size = response.info().get("Content-Length")
                            if total_size:
                                progress.update(task_id, total=int(total_size))

                            with open(download_file, "wb") as f:
                                while True:
                                    chunk = response.read(16384)
                                    if not chunk:
                                        break
                                    f.write(chunk)
                                    progress.update(task_id, advance=len(chunk))

                    if url_hash:
                        algo, expected = url_hash.split("=")
                        h = hashlib.new(algo.lower())
                        h.update(download_file.read_bytes())
                        actual = h.hexdigest()
                        if actual.lower() != expected.lower():
                            raise RuntimeError(
                                f"Hash mismatch for {url}: expected {expected}, got {actual}"
                            )

                    src_dir.mkdir(parents=True, exist_ok=True)
                    if url.endswith(".zip"):
                        with zipfile.ZipFile(download_file, "r") as zip_ref:
                            zip_ref.extractall(src_dir)
                    elif url.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar.bz2")):
                        with tarfile.open(download_file, "r:*") as tar_ref:
                            tar_ref.extractall(src_dir)

                ctx.variables[f"{name.lower()}_SOURCE_DIR"] = str(src_dir)
                ctx.variables[f"{name.lower()}_BINARY_DIR"] = str(
                    ctx.build_dir / "_deps" / f"{name.lower()}-build"
                )
                ctx.variables[f"{name.lower()}_POPULATED"] = "TRUE"

                actual_src_dir = src_dir
                contents = [p for p in src_dir.iterdir() if not p.name.startswith(".")]
                if len(contents) == 1 and contents[0].is_dir():
                    actual_src_dir = contents[0]

                ctx.variables[f"{name.lower()}_SOURCE_DIR"] = str(actual_src_dir)
                ctx.variables[f"{name.lower()}_BINARY_DIR"] = str(
                    ctx.build_dir / "_deps" / f"{name.lower()}-build"
                )
                ctx.variables[f"{name.lower()}_POPULATED"] = "TRUE"

                if frame.fetchcontent_make_available:
                    sub_cmakelists = actual_src_dir / "CMakeLists.txt"
                    if sub_cmakelists.exists():
                        from .parser import parse_file

                        ctx.record_cmake_file(sub_cmakelists)
                        ctx.record_cmake_file(sub_cmakelists)
                        sub_commands = parse_file(sub_cmakelists)

                        saved_current_source_dir = ctx.current_source_dir
                        saved_current_list_file = ctx.current_list_file
                        saved_vars = ctx.variables.copy()
                        ctx.parent_scope_vars = {}

                        ctx.current_source_dir = actual_src_dir
                        ctx.current_list_file = sub_cmakelists
                        ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] = str(actual_src_dir)
                        ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(sub_cmakelists)
                        ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                            sub_cmakelists.parent
                        )
                        ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(ctx.build_dir)

                        def on_exit() -> None:
                            parent_scope_updates = ctx.parent_scope_vars
                            ctx.current_source_dir = saved_current_source_dir
                            ctx.current_list_file = saved_current_list_file
                            ctx.variables = saved_vars
                            for var, val in parent_scope_updates.items():
                                if val is None:
                                    ctx.variables.pop(var, None)
                                else:
                                    ctx.variables[var] = val
                            ctx.parent_scope_vars.clear()

                        stack.append(Frame(commands=sub_commands, on_exit=on_exit))
            continue

        current_commands = cast(list[Command], frame.commands)
        if frame.pc >= len(current_commands):
            if frame.on_exit:
                frame.on_exit()
            stack.pop()
            continue

        cmd = current_commands[frame.pc]
        expanded_args: list[str] = []
        for idx, arg in enumerate(cmd.args):
            allow_undefined = False
            if cmd.name in ("if", "elseif"):
                allow_undefined = (
                    idx + 2 < len(cmd.args)
                    and cmd.args[idx + 1] == "STREQUAL"
                    and cmd.args[idx + 2] in ("", "\"\"", "''")
                    and (
                        (arg.startswith("${") and arg.endswith("}"))
                        or (arg.startswith("\"${") and arg.endswith("}\""))
                        or (arg.startswith("'${") and arg.endswith("}'"))
                    )
                )
            expanded = ctx.expand_variables(arg, strict, cmd.line, allow_undefined)
            quoted = cmd.is_quoted[idx] if idx < len(cmd.is_quoted) else False
            if ";" in expanded and not quoted:
                expanded_args.extend(expanded.split(";"))
            else:
                expanded_args.append(expanded)
        args = expanded_args

        if trace:
            args_str = " ".join(cmd.args) if cmd.args else ""
            rel_file = make_relative(str(ctx.current_list_file), ctx.source_dir)
            print(f"{rel_file}:{cmd.line}: {cmd.name}({args_str})")

        match cmd.name:
            case "if":
                endif_idx, block = select_if_block(
                    ctx, current_commands, frame.pc, strict
                )
                frame.pc = endif_idx + 1
                if block:
                    block_start, block_end = block
                    stack.append(
                        Frame(commands=current_commands[block_start:block_end])
                    )
                continue

            case "endif" | "else" | "elseif":
                ctx.raise_syntax_error(f"Unexpected {cmd.name}()", cmd.line)

            case "foreach":
                endforeach_idx, loop_var, items, body = build_foreach_info(
                    ctx, current_commands, frame.pc, args
                )
                frame.pc = endforeach_idx + 1
                stack.append(
                    Frame(
                        commands=None,
                        kind="foreach",
                        foreach_items=items,
                        foreach_loop_var=loop_var,
                        foreach_body=body,
                    )
                )
                continue

            case "endforeach":
                ctx.raise_syntax_error("Unexpected endforeach()", cmd.line)

            case "function":
                frame.pc = handle_function(ctx, current_commands, frame.pc, args)
                continue

            case "endfunction":
                ctx.raise_syntax_error("Unexpected endfunction()", cmd.line)

            case "macro":
                frame.pc = handle_macro(ctx, current_commands, frame.pc, args)
                continue

            case "endmacro":
                ctx.raise_syntax_error("Unexpected endmacro()", cmd.line)

            case "return":
                func_index = next(
                    (
                        i
                        for i in range(len(stack) - 1, -1, -1)
                        if stack[i].kind == "function"
                    ),
                    None,
                )
                if func_index is None:
                    raise ReturnFromFunction()
                while len(stack) > func_index:
                    popped = stack.pop()
                    if popped.on_exit:
                        popped.on_exit()
                continue

            case "cmake_policy":
                if args:
                    subcommand = args[0].upper()
                    if subcommand == "SET" and len(args) >= 3:
                        policy = args[1]
                        value = args[2].upper()
                        if value == "OLD":
                            ctx.print_warning(
                                f"cmake_policy(SET {policy} OLD) is called, but cninja always uses NEW behavior for all policies",
                                cmd.line,
                            )
                    elif subcommand == "GET" and len(args) >= 3:
                        var_name = args[2]
                        ctx.variables[var_name] = "NEW"
                    elif subcommand in ("PUSH", "POP", "VERSION"):
                        pass
                frame.pc += 1
                continue

            case "cmake_minimum_required":
                pass

            case "project":
                if args:
                    ctx.project_name = args[0]
                    ctx.variables["PROJECT_NAME"] = args[0]
                    ctx.variables["CMAKE_PROJECT_NAME"] = args[0]
                    ctx.variables["CMAKE_C_FLAGS"] = (
                        ""  # TODO: Only set when C is enabled
                    )
                    ctx.variables["CMAKE_CXX_FLAGS"] = (
                        ""  # TODO: Only set when CXX is enabled
                    )
                    ctx.variables["PROJECT_SOURCE_DIR"] = str(ctx.current_source_dir)
                    ctx.variables["PROJECT_BINARY_DIR"] = str(ctx.build_dir)
                    ctx.variables[f"{args[0]}_SOURCE_DIR"] = str(ctx.current_source_dir)
                    ctx.variables[f"{args[0]}_BINARY_DIR"] = str(ctx.build_dir)

            case "enable_language":
                # Objective-C++ is always enabled; ignore for now.
                pass

            case "add_subdirectory":
                if args:
                    sub_dir_name = args[0]
                    sub_source_dir = ctx.current_source_dir / sub_dir_name
                    if not sub_source_dir.exists():
                        pass

                    sub_cmakelists = sub_source_dir / "CMakeLists.txt"
                    if sub_cmakelists.exists():
                        from .parser import parse_file

                        sub_commands = parse_file(sub_cmakelists)

                        saved_current_source_dir = ctx.current_source_dir
                        saved_current_list_file = ctx.current_list_file
                        saved_parent_directory = ctx.parent_directory
                        saved_vars = ctx.variables.copy()
                        ctx.parent_scope_vars = {}

                        ctx.current_source_dir = sub_source_dir
                        ctx.current_list_file = sub_cmakelists
                        ctx.parent_directory = str(saved_current_source_dir)
                        ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] = str(sub_source_dir)
                        ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(sub_cmakelists)
                        ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                            sub_cmakelists.parent
                        )
                        ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(ctx.build_dir)

                        def on_exit() -> None:
                            parent_scope_updates = ctx.parent_scope_vars
                            ctx.current_source_dir = saved_current_source_dir
                            ctx.current_list_file = saved_current_list_file
                            ctx.parent_directory = saved_parent_directory
                            ctx.variables = saved_vars
                            for var, val in parent_scope_updates.items():
                                if val is None:
                                    ctx.variables.pop(var, None)
                                else:
                                    ctx.variables[var] = val
                            ctx.parent_scope_vars.clear()

                        stack.append(Frame(commands=sub_commands, on_exit=on_exit))
                    elif strict:
                        ctx.print_error(
                            f'add_subdirectory given source "{sub_dir_name}" which does not exist.',
                            cmd.line,
                        )
                        sys.exit(1)
                frame.pc += 1
                continue

            case "fetchcontent_declare":
                if len(args) >= 2:
                    name = args[0]
                    ctx.fetched_content[name.lower()] = FetchContentInfo(
                        name=name, args=args[1:]
                    )

            case "fetchcontent_getproperties":
                if args:
                    name = args[0].lower()
                    if name in ctx.variables:  # Check if already populated
                        pass
                    # Set variables even if not populated yet, as CMake does
                    # Actually, we should check our internal state
                    source_dir = ctx.variables.get(f"{name}_SOURCE_DIR", "")
                    binary_dir = ctx.variables.get(f"{name}_BINARY_DIR", "")
                    populated = ctx.variables.get(f"{name}_POPULATED", "FALSE")
                    ctx.variables[f"{name}_SOURCE_DIR"] = source_dir
                    ctx.variables[f"{name}_BINARY_DIR"] = binary_dir
                    ctx.variables[f"{name}_POPULATED"] = populated

            case "fetchcontent_makeavailable" | "fetchcontent_populate":
                stack.append(
                    Frame(
                        commands=None,
                        kind="fetchcontent",
                        fetchcontent_names=args,
                        fetchcontent_cmd=cmd,
                        fetchcontent_make_available=cmd.name
                        == "fetchcontent_makeavailable",
                    )
                )
                frame.pc += 1
                continue

            case "set":
                handle_set(ctx, cmd, args, strict)

            case "unset":
                handle_unset(ctx, cmd, args, strict)

            case "option":
                handle_option(ctx, args)

            case "cmake_parse_arguments":
                handle_cmake_parse_arguments(ctx, cmd, strict)

            case "math":
                handle_math(ctx, cmd, args, strict)

            case "string":
                handle_string(ctx, cmd, args, strict)

            case "list":
                handle_list(ctx, cmd, args, strict)

            case "include":
                if args:
                    module_name = args[0]
                    known_modules = {
                        "CTest",
                        "CheckIPOSupported",
                        "CheckCXXCompilerFlag",
                        "CheckCCompilerFlag",
                        "CheckCXXSymbolExists",
                        "FetchContent",
                        "FindPackageHandleStandardArgs",
                        "GNUInstallDirs",
                    }
                    if module_name == "CTest":
                        # CTest sets BUILD_TESTING to ON by default
                        if "BUILD_TESTING" not in ctx.variables:
                            ctx.variables["BUILD_TESTING"] = "ON"
                    elif module_name == "GNUInstallDirs":
                        ctx.variables["CMAKE_INSTALL_BINDIR"] = "bin"
                        ctx.variables["CMAKE_INSTALL_SBINDIR"] = "sbin"
                        ctx.variables["CMAKE_INSTALL_LIBEXECDIR"] = "libexec"
                        ctx.variables["CMAKE_INSTALL_SYSCONFDIR"] = "etc"
                        ctx.variables["CMAKE_INSTALL_SHAREDSTATEDIR"] = "com"
                        ctx.variables["CMAKE_INSTALL_LOCALSTATEDIR"] = "var"
                        ctx.variables["CMAKE_INSTALL_LIBDIR"] = "lib"
                        ctx.variables["CMAKE_INSTALL_INCLUDEDIR"] = "include"
                        ctx.variables["CMAKE_INSTALL_OLDINCLUDEDIR"] = "/usr/include"
                        ctx.variables["CMAKE_INSTALL_DATAROOTDIR"] = "share"
                        ctx.variables["CMAKE_INSTALL_DATADIR"] = "share"
                        ctx.variables["CMAKE_INSTALL_INFODIR"] = "share/info"
                        ctx.variables["CMAKE_INSTALL_LOCALEDIR"] = "share/locale"
                        ctx.variables["CMAKE_INSTALL_MANDIR"] = "share/man"
                        project_name = ctx.variables.get("PROJECT_NAME", "")
                        ctx.variables["CMAKE_INSTALL_DOCDIR"] = (
                            f"share/doc/{project_name}"
                        )
                    elif module_name.endswith(".cmake") or "/" in module_name:
                        inc_file = Path(module_name)
                        if not inc_file.is_absolute():
                            inc_file = ctx.current_source_dir / inc_file

                        if inc_file.exists():
                            from .parser import parse_file

                            ctx.record_cmake_file(inc_file)
                            inc_commands = parse_file(inc_file)
                            saved_list_file = ctx.current_list_file
                            ctx.current_list_file = inc_file
                            ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(inc_file)
                            ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                                inc_file.parent
                            )

                            def on_exit() -> None:
                                ctx.current_list_file = saved_list_file
                                ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(
                                    saved_list_file
                                )
                                ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                                    saved_list_file.parent
                                )

                            stack.append(Frame(commands=inc_commands, on_exit=on_exit))
                            frame.pc += 1
                            continue
                        elif strict:
                            ctx.print_error(
                                f"include() could not find file: {module_name}",
                                cmd.line,
                            )
                            sys.exit(1)
                    elif module_name not in known_modules:
                        if strict:
                            ctx.print_error(f"unknown module: {module_name}", cmd.line)
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
                        [ctx.c_compiler, "-flto", "-o", temp_out, temp_src],
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
                            [ctx.cxx_compiler, flag, "-c", "-o", temp_out, temp_src],
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
                            [ctx.c_compiler, flag, "-c", "-o", temp_out, temp_src],
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
                            [ctx.cxx_compiler, "-o", temp_out, temp_src],
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
                            [ctx.c_compiler, "-o", temp_out, temp_src],
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
                handle_add_library(ctx, cmd, args)

            case "add_executable":
                handle_add_executable(ctx, cmd, args)

            case "set_target_properties":
                handle_set_target_properties(ctx, cmd, args, strict)

            case "set_property":
                handle_set_property(ctx, cmd, args, strict)

            case "get_property":
                handle_get_property(ctx, cmd, args, strict)

            case "get_directory_property":
                handle_get_directory_property(ctx, cmd, args, strict)

            case "get_filename_component":
                handle_get_filename_component(ctx, args)

            case "get_target_property":
                if len(args) >= 3:
                    var_name = args[0]
                    target_name = args[1]
                    prop_name = args[2]

                    lib = ctx.get_library(target_name)
                    exe = ctx.get_executable(target_name)

                    if prop_name == "TYPE":
                        if lib:
                            ctx.variables[var_name] = f"{lib.lib_type}_LIBRARY"
                        elif exe:
                            ctx.variables[var_name] = "EXECUTABLE"
                        else:
                            ctx.variables[var_name] = f"{var_name}-NOTFOUND"
                    else:
                        ctx.variables[var_name] = f"{var_name}-NOTFOUND"

            case "target_link_libraries":
                handle_target_link_libraries(ctx, cmd, args)

            case "target_link_directories":
                handle_target_link_directories(ctx, cmd, args, strict)

            case "target_sources":
                handle_target_sources(ctx, args)

            case "target_compile_features":
                handle_target_compile_features(ctx, args)

            case "target_include_directories":
                handle_target_include_directories(ctx, cmd, args, strict)

            case "target_compile_definitions":
                handle_target_compile_definitions(ctx, cmd, args, strict)

            case "include_directories":
                handle_include_directories(ctx, cmd, args, strict)

            case "file":
                handle_file(ctx, cmd, args, strict)

            case "add_compile_options":
                # add_compile_options adds flags to all targets
                for arg in args:
                    expanded = ctx.expand_variables(arg, strict, cmd.line)
                    ctx.compile_options.append(expanded)

            case "add_compile_definitions":
                # add_compile_definitions adds preprocessor definitions to all targets
                for arg in args:
                    expanded = ctx.expand_variables(arg, strict, cmd.line)
                    ctx.compile_definitions.append(expanded)

            case "add_custom_command":
                # Minimal support: add_custom_command(OUTPUT ... COMMAND ... DEPENDS ... MAIN_DEPENDENCY ... WORKING_DIRECTORY ... VERBATIM)
                outputs: list[str] = []
                command_list: list[list[str]] = []
                depends: list[str] = []
                main_dependency: str | None = None
                working_directory: str | None = None
                verbatim = False
                arg_idx = 0
                current_section = None
                while arg_idx < len(args):
                    arg = args[arg_idx]
                    if arg in (
                        "OUTPUT",
                        "COMMAND",
                        "DEPENDS",
                        "MAIN_DEPENDENCY",
                        "WORKING_DIRECTORY",
                    ):
                        current_section = arg
                        if arg == "COMMAND":
                            command_list.append([])
                    elif arg == "VERBATIM":
                        verbatim = True
                    else:
                        arg = ctx.expand_variables(arg, strict, cmd.line)
                        if current_section == "OUTPUT":
                            # Make relative to build_dir or source_dir
                            rel = make_relative(arg, ctx.build_dir)
                            if rel == arg:
                                rel = ctx.resolve_path(arg)
                            outputs.append(rel)
                        elif current_section == "COMMAND":
                            command_list[-1].append(arg)
                        elif current_section == "DEPENDS":
                            # Make relative to build_dir or source_dir
                            rel = make_relative(arg, ctx.build_dir)
                            if rel == arg:
                                rel = ctx.resolve_path(arg)
                            depends.append(rel)
                        elif current_section == "MAIN_DEPENDENCY":
                            # Make relative to build_dir or source_dir
                            rel = make_relative(arg, ctx.build_dir)
                            if rel == arg:
                                rel = ctx.resolve_path(arg)
                            main_dependency = rel
                        elif current_section == "WORKING_DIRECTORY":
                            working_directory = arg
                    arg_idx += 1

                if outputs and command_list:
                    ctx.custom_commands.append(
                        CustomCommand(
                            outputs=outputs,
                            commands=command_list,
                            depends=depends,
                            main_dependency=main_dependency,
                            working_directory=working_directory,
                            verbatim=verbatim,
                            defined_file=ctx.current_list_file,
                            defined_line=cmd.line,
                        )
                    )

            case "add_test":
                # Support: add_test(NAME <name> COMMAND <command> ...)
                # Or: add_test(<name> <command> ...)
                if len(args) >= 2:
                    test_name = ""
                    test_command = []
                    if args[0] == "NAME":
                        # NAME ... COMMAND ...
                        test_name = ctx.expand_variables(args[1], strict, cmd.line)
                        if "COMMAND" in args:
                            cmd_idx = args.index("COMMAND")
                            test_command = [
                                ctx.expand_variables(a, strict, cmd.line)
                                for a in args[cmd_idx + 1 :]
                            ]
                    else:
                        # <name> <command> ...
                        test_name = ctx.expand_variables(args[0], strict, cmd.line)
                        test_command = [
                            ctx.expand_variables(a, strict, cmd.line) for a in args[1:]
                        ]

                    if test_name and test_command:
                        ctx.tests.append(Test(name=test_name, command=test_command))

            case "set_source_files_properties":
                if "PROPERTIES" in args:
                    prop_idx = args.index("PROPERTIES")
                    files = args[:prop_idx]
                    props = args[prop_idx + 1 :]

                    for filename in files:
                        expanded_filename = ctx.expand_variables(
                            filename, strict, cmd.line
                        )
                        if not Path(expanded_filename).is_absolute():
                            expanded_filename = str(
                                ctx.current_source_dir / expanded_filename
                            )

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
                                    ctx.expand_variables(v, strict, cmd.line)
                                    for v in values
                                ]

                                if prop_name == "OBJECT_DEPENDS":
                                    for v in expanded_values:
                                        if not Path(v).is_absolute():
                                            v = str(ctx.current_source_dir / v)
                                        v = make_relative(v, ctx.source_dir)
                                        file_props.object_depends.append(v)
                                elif prop_name == "INCLUDE_DIRECTORIES":
                                    for v in expanded_values:
                                        if not Path(v).is_absolute():
                                            v = str(ctx.current_source_dir / v)
                                        v = make_relative(v, ctx.source_dir)
                                        file_props.include_directories.append(v)
                                elif prop_name == "COMPILE_DEFINITIONS":
                                    file_props.compile_definitions.extend(
                                        expanded_values
                                    )
                            else:
                                ctx.print_warning(
                                    f"property '{prop_name}' has no value",
                                    cmd.line,
                                )

            case "source_group":
                # Visual Studio solution organization is not supported; ignore.
                pass

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

            case "find_path":
                if len(args) >= 2:
                    var_name = args[0]
                    names: list[str] = []
                    paths: list[str] = []
                    hints: list[str] = []
                    suffixes: list[str] = []
                    required = False

                    i = 1
                    while i < len(args):
                        arg = args[i]
                        if arg == "NAMES":
                            i += 1
                            while i < len(args) and args[i] not in (
                                "PATHS",
                                "HINTS",
                                "PATH_SUFFIXES",
                                "REQUIRED",
                            ):
                                names.append(args[i])
                                i += 1
                            continue
                        elif arg == "PATHS":
                            i += 1
                            while i < len(args) and args[i] not in (
                                "NAMES",
                                "HINTS",
                                "PATH_SUFFIXES",
                                "REQUIRED",
                            ):
                                paths.append(args[i])
                                i += 1
                            continue
                        elif arg == "HINTS":
                            i += 1
                            while i < len(args) and args[i] not in (
                                "NAMES",
                                "PATHS",
                                "PATH_SUFFIXES",
                                "REQUIRED",
                            ):
                                hints.append(args[i])
                                i += 1
                            continue
                        elif arg == "PATH_SUFFIXES":
                            i += 1
                            while i < len(args) and args[i] not in (
                                "NAMES",
                                "PATHS",
                                "HINTS",
                                "REQUIRED",
                            ):
                                suffixes.append(args[i])
                                i += 1
                            continue
                        elif arg == "REQUIRED":
                            required = True
                        else:
                            if not names:
                                names.append(arg)
                            else:
                                paths.append(arg)
                        i += 1

                    search_dirs = []
                    # HINTS come first
                    search_dirs.extend(hints)
                    # Then PATHS
                    search_dirs.extend(paths)
                    # Standard system paths if none found?
                    # For now just use provided paths

                    found_dir = None
                    for name in names:
                        # Check each search dir
                        for d in search_dirs:
                            # Try with suffixes
                            for suffix in [""] + suffixes:
                                base_path = Path(d) / suffix
                                if (base_path / name).exists():
                                    found_dir = str(base_path.absolute())
                                    break
                            if found_dir:
                                break
                        if found_dir:
                            break

                    if found_dir:
                        ctx.variables[var_name] = found_dir
                    else:
                        ctx.variables[var_name] = f"{var_name}-NOTFOUND"
                        if required:
                            raise FileNotFoundError(
                                f"Could not find path for: {', '.join(names)}"
                            )

            case "find_library":
                if len(args) >= 2:
                    var_name = args[0]
                    names: list[str] = []
                    paths: list[str] = []
                    hints: list[str] = []
                    suffixes: list[str] = []
                    required = False

                    j = 1
                    while j < len(args):
                        arg = args[j]
                        if arg == "NAMES":
                            j += 1
                            while j < len(args) and args[j] not in (
                                "PATHS",
                                "HINTS",
                                "PATH_SUFFIXES",
                                "REQUIRED",
                            ):
                                names.append(args[j])
                                j += 1
                            continue
                        elif arg == "PATHS":
                            j += 1
                            while j < len(args) and args[j] not in (
                                "NAMES",
                                "HINTS",
                                "PATH_SUFFIXES",
                                "REQUIRED",
                            ):
                                paths.append(args[j])
                                j += 1
                            continue
                        elif arg == "HINTS":
                            j += 1
                            while j < len(args) and args[j] not in (
                                "NAMES",
                                "PATHS",
                                "PATH_SUFFIXES",
                                "REQUIRED",
                            ):
                                hints.append(args[j])
                                j += 1
                            continue
                        elif arg == "PATH_SUFFIXES":
                            j += 1
                            while j < len(args) and args[j] not in (
                                "NAMES",
                                "PATHS",
                                "HINTS",
                                "REQUIRED",
                            ):
                                suffixes.append(args[j])
                                j += 1
                            continue
                        elif arg == "REQUIRED":
                            required = True
                        else:
                            if not names:
                                names.append(arg)
                            else:
                                paths.append(arg)
                        j += 1

                    search_dirs = []
                    search_dirs.extend(hints)
                    search_dirs.extend(paths)

                    if platform.system() == "Darwin":
                        default_framework_dirs = [
                            "/System/Library/Frameworks",
                            "/Library/Frameworks",
                        ]
                        for d in default_framework_dirs:
                            if d not in search_dirs:
                                search_dirs.append(d)

                    # Standard library extensions
                    if platform.system() == "Darwin":
                        extensions = [".dylib", ".tbd", ".a"]
                    elif platform.system() == "Windows":
                        extensions = [".lib", ".dll.a", ".a"]
                    else:
                        extensions = [".so", ".a"]

                    found_lib = None
                    for name in names:
                        if platform.system() == "Darwin":
                            framework_name = (
                                name
                                if name.endswith(".framework")
                                else f"{name}.framework"
                            )
                            for d in search_dirs:
                                for suffix in [""] + suffixes:
                                    base_path = Path(d) / suffix
                                    framework_path = base_path / framework_name
                                    if framework_path.exists():
                                        found_lib = str(framework_path.absolute())
                                        break
                                if found_lib:
                                    break
                            if found_lib:
                                break

                        # Construct potential filenames
                        lib_filenames = []
                        if name.startswith("lib") and (
                            name.endswith(".a")
                            or name.endswith(".so")
                            or name.endswith(".dylib")
                        ):
                            lib_filenames.append(name)
                        else:
                            for ext in extensions:
                                lib_filenames.append(f"lib{name}{ext}")
                                if platform.system() == "Windows":
                                    lib_filenames.append(f"{name}{ext}")

                        for d in search_dirs:
                            for suffix in [""] + suffixes:
                                base_path = Path(d) / suffix
                                for filename in lib_filenames:
                                    candidate = base_path / filename
                                    if candidate.exists():
                                        found_lib = str(candidate.absolute())
                                        break
                                if found_lib:
                                    break
                            if found_lib:
                                break
                        if found_lib:
                            break

                    if found_lib:
                        ctx.variables[var_name] = found_lib
                    else:
                        ctx.variables[var_name] = f"{var_name}-NOTFOUND"
                        if required:
                            raise FileNotFoundError(
                                f"Could not find library: {', '.join(names)}"
                            )

            case "find_package_handle_standard_args":
                if args:
                    package_name = args[0]
                    required_vars = []
                    found_var = f"{package_name}_FOUND"

                    if "REQUIRED_VARS" in args:
                        # Extended signature
                        idx = args.index("REQUIRED_VARS")
                        for arg in args[idx + 1 :]:
                            if arg in (
                                "VERSION_VAR",
                                "HANDLE_COMPONENTS",
                                "CONFIG_MODE",
                                "NAME_MISMATCH",
                                "REASON_FAILURE_MESSAGE",
                                "FOUND_VAR",
                            ):
                                break
                            required_vars.append(arg)

                        if "FOUND_VAR" in args:
                            f_idx = args.index("FOUND_VAR")
                            if f_idx + 1 < len(args):
                                found_var = args[f_idx + 1]
                    else:
                        # Basic signature
                        # args[1] is message, usually DEFAULT_MSG
                        required_vars = args[2:]

                    # Check if all required vars are set and not NOTFOUND
                    all_found = True
                    for var in required_vars:
                        val = ctx.variables.get(var, "")
                        if not val or val.endswith("-NOTFOUND") or val == "FALSE":
                            all_found = False
                            break

                    if all_found:
                        ctx.variables[found_var] = "TRUE"
                    else:
                        ctx.variables[found_var] = "FALSE"
                        # Check if package was REQUIRED
                        if ctx.variables.get(f"{package_name}_FIND_REQUIRED") == "TRUE":
                            ctx.print_error(
                                f"Could NOT find {package_name} (missing: {', '.join(required_vars)})",
                                cmd.line,
                            )
                            sys.exit(1)

            case "install":
                if len(args) >= 2 and args[0] == "TARGETS":
                    targets = []
                    destination = str(Path.home() / ".local" / "bin")
                    i = 1
                    while i < len(args):
                        if args[i] == "DESTINATION":
                            if i + 1 < len(args):
                                destination = ctx.expand_variables(
                                    args[i + 1], strict, cmd.line
                                )
                                i += 2
                            else:
                                i += 1
                        else:
                            targets.append(args[i])
                            i += 1
                    ctx.install_targets.append(
                        InstallTarget(targets=targets, destination=destination)
                    )

            case "find_package":
                if args:
                    package_name = args[0]
                    required = "REQUIRED" in args
                    quiet = "QUIET" in args
                    ctx.variables[f"{package_name}_FIND_REQUIRED"] = (
                        "TRUE" if required else "FALSE"
                    )

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
                            if not quiet:
                                print(f"{colored('✓', 'green')} {package_name}")
                        else:
                            ctx.variables["GTest_FOUND"] = "FALSE"
                            ctx.variables["GTEST_FOUND"] = "FALSE"
                            if required:
                                ctx.print_error(
                                    "could not find package: GTest", cmd.line
                                )
                                raise SystemExit(1)
                            if not quiet:
                                print(f"{colored('✗', 'red')} {package_name}")
                    elif package_name == "Threads":
                        # Threads is always available on Unix-like systems
                        ctx.variables["Threads_FOUND"] = "TRUE"
                        ctx.variables["CMAKE_THREAD_LIBS_INIT"] = "-pthread"
                        ctx.variables["CMAKE_USE_PTHREADS_INIT"] = "TRUE"
                        # Register the imported target
                        ctx.imported_targets["Threads::Threads"] = ImportedTarget(
                            libs="-pthread"
                        )
                        if not quiet:
                            print(f"{colored('✓', 'green')} {package_name}")
                    elif package_name == "PkgConfig":
                        ctx.variables["PkgConfig_FOUND"] = "TRUE"
                        ctx.variables["PKG_CONFIG_EXECUTABLE"] = "pkg-config"
                        if not quiet:
                            print(f"{colored('✓', 'green')} {package_name}")
                    elif package_name == "WebP":
                        found = False
                        pkg_name = None
                        try:
                            for candidate in ("libwebp", "webp"):
                                result = subprocess.run(
                                    ["pkg-config", "--exists", candidate],
                                    capture_output=True,
                                )
                                if result.returncode == 0:
                                    found = True
                                    pkg_name = candidate
                                    break
                        except FileNotFoundError:
                            found = False

                        if found and pkg_name:
                            cflags_result = subprocess.run(
                                ["pkg-config", "--cflags", pkg_name],
                                capture_output=True,
                                text=True,
                            )
                            libs_result = subprocess.run(
                                ["pkg-config", "--libs", pkg_name],
                                capture_output=True,
                                text=True,
                            )
                            version_result = subprocess.run(
                                ["pkg-config", "--modversion", pkg_name],
                                capture_output=True,
                                text=True,
                            )

                            webp_cflags = cflags_result.stdout.strip()
                            webp_libs = libs_result.stdout.strip()
                            webp_version = version_result.stdout.strip()

                            include_dirs = []
                            for entry in shlex.split(webp_cflags):
                                if entry.startswith("-I"):
                                    include_dirs.append(entry[2:])

                            ctx.variables["WebP_FOUND"] = "TRUE"
                            ctx.variables["WEBP_FOUND"] = "TRUE"
                            ctx.variables["WEBP_INCLUDE_DIRS"] = ";".join(include_dirs)
                            if include_dirs:
                                ctx.variables["WEBP_INCLUDE_DIR"] = include_dirs[0]
                            ctx.variables["WEBP_LIBRARIES"] = webp_libs
                            if webp_version:
                                ctx.variables["WEBP_VERSION"] = webp_version

                            ctx.imported_targets["WebP::webp"] = ImportedTarget(
                                cflags=webp_cflags,
                                libs=webp_libs,
                            )
                            if not quiet:
                                print(f"{colored('✓', 'green')} {package_name}")
                        else:
                            ctx.variables["WebP_FOUND"] = "FALSE"
                            ctx.variables["WEBP_FOUND"] = "FALSE"
                            if required:
                                ctx.print_error(
                                    "could not find package: WebP", cmd.line
                                )
                                raise SystemExit(1)
                            if not quiet:
                                print(f"{colored('✗', 'red')} {package_name}")
                    else:
                        # Search for Find<PackageName>.cmake in CMAKE_MODULE_PATH
                        module_path = ctx.variables.get("CMAKE_MODULE_PATH", "")
                        search_dirs = module_path.split(";") if module_path else []

                        found_file = None
                        for d in search_dirs:
                            # Resolve relative paths relative to current source dir or root?
                            # CMake usually expects them relative to root or absolute.
                            p = Path(d)
                            if not p.is_absolute():
                                p = ctx.source_dir / d

                            candidate = p / f"Find{package_name}.cmake"
                            if candidate.exists():
                                found_file = candidate
                                break

                        if found_file:
                            from .parser import parse_file

                            ctx.record_cmake_file(found_file)
                            find_commands = parse_file(found_file)

                            saved_list_file = ctx.current_list_file
                            ctx.current_list_file = found_file

                            def on_exit() -> None:
                                ctx.current_list_file = saved_list_file

                            stack.append(Frame(commands=find_commands, on_exit=on_exit))
                            frame.pc += 1
                            continue
                        else:
                            # Unknown package
                            ctx.variables[f"{package_name}_FOUND"] = "FALSE"
                            if required:
                                ctx.print_error(
                                    f"could not find package: {package_name}", cmd.line
                                )
                                raise SystemExit(1)
                            if not quiet:
                                print(f"{colored('✗', 'red')} {package_name}")

            case "pkg_check_modules":
                if args:
                    prefix = args[0]
                    pkg_args = args[1:]

                    is_required = "REQUIRED" in pkg_args
                    is_quiet = "QUIET" in pkg_args
                    is_imported_target = "IMPORTED_TARGET" in pkg_args

                    modules = [
                        arg
                        for arg in pkg_args
                        if arg
                        not in (
                            "REQUIRED",
                            "QUIET",
                            "NO_CMAKE_PATH",
                            "NO_CMAKE_ENVIRONMENT_PATH",
                            "IMPORTED_TARGET",
                        )
                    ]

                    if modules:
                        found_all = True
                        all_cflags = []
                        all_libs = []
                        all_include_dirs = []
                        all_lib_dirs = []
                        all_libraries = []
                        all_includedirs = []
                        all_libdirs = []
                        all_prefixes = []

                        for module in modules:
                            try:
                                result = subprocess.run(
                                    ["pkg-config", "--exists", module],
                                    capture_output=True,
                                )
                                if result.returncode != 0:
                                    found_all = False
                                    break

                                cflags_res = subprocess.run(
                                    ["pkg-config", "--cflags", module],
                                    capture_output=True,
                                    text=True,
                                )
                                cflags_out = cflags_res.stdout.strip()
                                all_cflags.append(cflags_out)
                                for entry in shlex.split(cflags_out):
                                    if entry.startswith("-I"):
                                        all_include_dirs.append(entry[2:])

                                libs_res = subprocess.run(
                                    ["pkg-config", "--libs", module],
                                    capture_output=True,
                                    text=True,
                                )
                                libs_out = libs_res.stdout.strip()
                                all_libs.append(libs_out)
                                for entry in shlex.split(libs_out):
                                    if entry.startswith("-l"):
                                        all_libraries.append(entry[2:])
                                    elif entry.startswith("-L"):
                                        all_lib_dirs.append(entry[2:])

                                # Fetch standard variables
                                for var_name, target_list in [
                                    ("includedir", all_includedirs),
                                    ("libdir", all_libdirs),
                                    ("prefix", all_prefixes),
                                ]:
                                    var_res = subprocess.run(
                                        [
                                            "pkg-config",
                                            f"--variable={var_name}",
                                            module,
                                        ],
                                        capture_output=True,
                                        text=True,
                                    )
                                    if var_res.returncode == 0:
                                        val = var_res.stdout.strip()
                                        if val:
                                            target_list.append(val)

                            except FileNotFoundError:
                                found_all = False
                                break

                        if found_all:
                            if not is_quiet:
                                print(f"{colored('✓', 'green')} {', '.join(modules)}")
                            ctx.variables[f"{prefix}_FOUND"] = "1"
                            cflags = " ".join(all_cflags)
                            libs = " ".join(all_libs)

                            ctx.variables[f"{prefix}_INCLUDE_DIRS"] = ";".join(
                                list(dict.fromkeys(all_include_dirs))
                            )
                            ctx.variables[f"{prefix}_LIBRARIES"] = ";".join(
                                list(dict.fromkeys(all_libraries))
                            )
                            ctx.variables[f"{prefix}_LINK_LIBRARIES"] = ";".join(
                                shlex.split(libs)
                            )
                            ctx.variables[f"{prefix}_LIBRARY_DIRS"] = ";".join(
                                list(dict.fromkeys(all_lib_dirs))
                            )
                            ctx.variables[f"{prefix}_INCLUDEDIR"] = ";".join(
                                list(dict.fromkeys(all_includedirs))
                            )
                            ctx.variables[f"{prefix}_LIBDIR"] = ";".join(
                                list(dict.fromkeys(all_libdirs))
                            )
                            ctx.variables[f"{prefix}_PREFIX"] = ";".join(
                                list(dict.fromkeys(all_prefixes))
                            )
                            ctx.variables[f"{prefix}_CFLAGS"] = cflags
                            ctx.variables[f"{prefix}_LDFLAGS"] = libs

                            if is_imported_target:
                                # Create imported target PkgConfig::<prefix>
                                ctx.imported_targets[f"PkgConfig::{prefix}"] = (
                                    ImportedTarget(
                                        cflags=cflags,
                                        libs=libs,
                                    )
                                )
                        else:
                            if not is_quiet:
                                print(f"{colored('✗', 'red')} {', '.join(modules)}")
                            ctx.variables[f"{prefix}_FOUND"] = "0"
                            if is_required:
                                raise FileNotFoundError(
                                    f"could not find modules: {', '.join(modules)}"
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
                        ctx.print_error(message, cmd.line)
                        raise SystemExit(1)
                    elif mode == "SEND_ERROR":
                        ctx.print_error(message, cmd.line)
                    elif mode in ("WARNING", "AUTHOR_WARNING", "DEPRECATION"):
                        ctx.print_warning(message, cmd.line)
                    elif mode == "STATUS":
                        print(f"{message}")
                    else:
                        print(message)

            case "enable_testing":
                assert len(args) == 0
                pass  # stub

            case "mark_as_advanced":
                pass  # not needed because we don't have a GUI (yet?)

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
                            working_directory = ctx.expand_variables(
                                args[arg_idx], strict, cmd.line
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
                            ctx.expand_variables(arg, strict, cmd.line)
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
                # Check if this is a user-defined function or macro call
                name = cmd.name.lower()
                if name in ctx.functions:
                    func_def = ctx.functions[name]
                    # Save current variables for function scope
                    saved_vars = ctx.variables.copy()
                    saved_current_list_file = ctx.current_list_file

                    # Set up function arguments
                    ctx.variables["ARGC"] = str(len(args))
                    ctx.variables["ARGV"] = ";".join(args)
                    for idx, arg in enumerate(args):
                        ctx.variables[f"ARGV{idx}"] = arg
                    for idx, param in enumerate(func_def.params):
                        if idx < len(args):
                            ctx.variables[param] = args[idx]
                        else:
                            ctx.variables[param] = ""
                    extra_args = args[len(func_def.params) :]
                    ctx.variables["ARGN"] = ";".join(extra_args)

                    ctx.parent_scope_vars.clear()

                    ctx.current_list_file = func_def.defining_file
                    ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(
                        func_def.defining_file
                    )
                    ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                        func_def.defining_file.parent
                    )

                    def on_exit() -> None:
                        for var_name, var_value in ctx.parent_scope_vars.items():
                            if var_value is None:
                                saved_vars.pop(var_name, None)
                            else:
                                saved_vars[var_name] = var_value
                        ctx.parent_scope_vars.clear()
                        ctx.current_list_file = saved_current_list_file
                        ctx.variables = saved_vars

                    frame.pc += 1
                    stack.append(
                        Frame(commands=func_def.body, on_exit=on_exit, kind="function")
                    )
                    continue
                elif name in ctx.macros:
                    macro_def = ctx.macros[name]
                    # Macros don't create a new scope - they operate in the caller's scope
                    # Save the special variables so we can restore them after
                    saved_argc = ctx.variables.get("ARGC", "")
                    saved_argv = ctx.variables.get("ARGV", "")
                    saved_argn = ctx.variables.get("ARGN", "")
                    saved_argv_vars = {}
                    saved_params = {}

                    # Save existing ARGVn variables
                    for idx in range(100):  # Reasonable upper limit
                        key = f"ARGV{idx}"
                        if key in ctx.variables:
                            saved_argv_vars[key] = ctx.variables[key]
                        else:
                            break

                    # Save existing parameter values
                    for param in macro_def.params:
                        if param in ctx.variables:
                            saved_params[param] = ctx.variables[param]

                    # Set up macro arguments
                    # ARGC = number of arguments
                    ctx.variables["ARGC"] = str(len(args))
                    # ARGV = all arguments as semicolon-separated list
                    ctx.variables["ARGV"] = ";".join(args)
                    # ARGVn = individual arguments
                    for idx, arg in enumerate(args):
                        ctx.variables[f"ARGV{idx}"] = arg
                    # Named parameters
                    for idx, param in enumerate(macro_def.params):
                        if idx < len(args):
                            ctx.variables[param] = args[idx]
                        else:
                            ctx.variables[param] = ""
                    # ARGN = arguments after named parameters
                    extra_args = args[len(macro_def.params) :]
                    ctx.variables["ARGN"] = ";".join(extra_args)

                    def on_exit() -> None:
                        if saved_argc:
                            ctx.variables["ARGC"] = saved_argc
                        else:
                            ctx.variables.pop("ARGC", None)

                        if saved_argv:
                            ctx.variables["ARGV"] = saved_argv
                        else:
                            ctx.variables.pop("ARGV", None)

                        if saved_argn:
                            ctx.variables["ARGN"] = saved_argn
                        else:
                            ctx.variables.pop("ARGN", None)

                        for idx in range(len(args)):
                            key = f"ARGV{idx}"
                            if key in saved_argv_vars:
                                ctx.variables[key] = saved_argv_vars[key]
                            else:
                                ctx.variables.pop(key, None)

                        for param in macro_def.params:
                            if param in saved_params:
                                ctx.variables[param] = saved_params[param]
                            else:
                                ctx.variables.pop(param, None)

                    frame.pc += 1
                    stack.append(Frame(commands=macro_def.body, on_exit=on_exit))
                    continue
                elif strict:
                    ctx.print_error(f"unsupported command: {cmd.name}()", cmd.line)
                    sys.exit(1)
                # Ignore unknown commands by default

        frame.pc += 1


def generate_ninja(
    ctx: BuildContext, output_path: Path, builddir: str, strict: bool = False
) -> None:
    """Generate ninja build file."""
    # Use compilers from context (set via CMAKE_C_COMPILER/CMAKE_CXX_COMPILER or defaults)
    cc = ctx.c_compiler
    cxx = ctx.cxx_compiler

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

        output_origins: dict[str, tuple[Path | None, int]] = {}
        warning_label = colored("warning:", "magenta", attrs=["bold"])
        error_label = colored("error:", "red", attrs=["bold"])

        def format_origin(path: Path | None, line: int) -> str:
            if path is None:
                return "<unknown>"
            rel = make_relative(str(path), ctx.source_dir)
            return f"{rel}:{line}" if line > 0 else rel

        def register_output(
            output: str, origin_file: Path | None, origin_line: int
        ) -> None:
            if output in output_origins:
                first_file, first_line = output_origins[output]
                loc = format_origin(origin_file, origin_line)
                first_loc = format_origin(first_file, first_line)
                label = error_label if strict else warning_label
                print(
                    f"{loc}: {label} multiple rules generate {output}; first defined at {first_loc}",
                    file=sys.stderr,
                )
                if strict:
                    raise SystemExit(1)
            else:
                output_origins[output] = (origin_file, origin_line)

        n.comment("Generated by cninja")
        n.newline()

        # Variables
        n.variable("builddir", builddir)
        n.variable("cc", cc)
        n.variable("cxx", cxx)
        default_ar = "llvm-ar" if platform.system() == "Windows" else "ar"
        n.variable("ar", default_ar)
        n.newline()

        cmake_deps: list[str] = []
        for cmake_path in sorted(ctx.cmake_files, key=lambda p: str(p)):
            if cmake_path.name == "CMakeLists.txt" or cmake_path.suffix == ".cmake":
                cmake_deps.append(make_relative(str(cmake_path), ctx.source_dir))

        if cmake_deps:

            def format_define(name: str, value: str) -> str:
                if value == "":
                    return f"-D{name}="
                return f"-D{name}={value}"

            reconfigure_cmd_parts = ["cninja"]
            if builddir != "build":
                reconfigure_cmd_parts += ["-B", "$builddir"]
            for var_name in sorted(ctx.cache_variables):
                if var_name in ctx.variables:
                    reconfigure_cmd_parts.append(
                        format_define(var_name, ctx.variables[var_name])
                    )

            def quote_part(part: str) -> str:
                if part == "$builddir":
                    return part
                return shlex.quote(part)

            reconfigure_cmd = " ".join(
                quote_part(part) for part in reconfigure_cmd_parts
            )

            n.rule(
                "reconfigure",
                command=reconfigure_cmd,
                generator=True,
                restat=True,
                pool="console",
            )
            n.newline()

            output_name = make_relative(str(output_path), ctx.source_dir)
            n.build(output_name, "reconfigure", cmake_deps)
            n.newline()

        # Compile rules - include build type flags
        base_cflags = f"-fdiagnostics-color {build_type_flags}".strip()
        c_flags = ctx.variables.get("CMAKE_C_FLAGS", "")
        cxx_flags = ctx.variables.get("CMAKE_CXX_FLAGS", "")

        n.rule(
            "cc",
            command=f"$cc -MMD -MF $out.d {base_cflags} {c_flags} $cflags -c $in -o $out".replace(
                "  ", " "
            ).strip(),
            depfile="$out.d",
            description="\x1b[32mCompiling $in\x1b[0m",
        )
        n.newline()

        n.rule(
            "cxx",
            command=f"$cxx -MMD -MF $out.d {base_cflags} {cxx_flags} $cflags -c $in -o $out".replace(
                "  ", " "
            ).strip(),
            depfile="$out.d",
            description="\x1b[32mCompiling $in\x1b[0m",
        )
        n.newline()

        # Archive rule for static libraries
        n.rule(
            "ar",
            command="$ar rcs $out $in",
            description="\x1b[32;1mArchiving $out\x1b[0m",
            # TODO: CMake shows "Linking C static library" or "Linking C++ static library" instead.
            # "static" is redundant info here, but we should also distinguish C vs C++.
        )
        n.newline()

        # Link rules
        n.rule(
            "link",
            command="$cc $in -o $out $libs",
            description="\x1b[32;1mLinking C executable $out\x1b[0m",
        )
        n.newline()

        n.rule(
            "link_cxx",
            command="$cxx $in -o $out $libs",
            description="\x1b[32;1mLinking C++ executable $out\x1b[0m",
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
            for o in custom_cmd.outputs:
                if not Path(o).is_absolute():
                    prefixed_o = f"$builddir/{o}"
                    outputs.append(prefixed_o)
                    custom_command_outputs.add(o)
                else:
                    outputs.append(o)

            # Process multiple commands
            cmd_parts: list[str] = []
            shell_operators = (
                ">",
                ">>",
                "2>",
                "2>&1",
                "<",
                "|",
                "&",
                "&&",
                "||",
                ";",
            )
            for command in custom_cmd.commands:
                if custom_cmd.verbatim:
                    parts = []
                    for arg in command:
                        if arg in shell_operators:
                            parts.append(str(arg))
                        else:
                            parts.append(shlex.quote(str(arg)))
                    cmd_parts.append(" ".join(parts))
                else:
                    cmd_parts.append(" ".join(str(c) for c in command))

            cmd_str = " && ".join(cmd_parts)

            depends = [
                f"$builddir/{d}"
                if d in custom_command_outputs and not Path(d).is_absolute()
                else d
                for d in custom_cmd.depends
            ]
            main_dep = custom_cmd.main_dependency
            if main_dep:
                if (
                    main_dep in custom_command_outputs
                    and not Path(main_dep).is_absolute()
                ):
                    main_dep = f"$builddir/{main_dep}"
                depends.insert(0, main_dep)

            working_dir = custom_cmd.working_directory
            if working_dir:
                cmd_str = f"cd {working_dir} && {cmd_str}"

            n.build(
                outputs,
                "custom_command",
                depends,
                variables={"cmd": cmd_str},
            )
            for out in outputs:
                register_output(out, custom_cmd.defined_file, custom_cmd.defined_line)
            n.newline()

        # Helper to expand link libraries recursively
        def expand_link_libraries(
            initial: list[str], follow_private_of_static: bool
        ) -> list[str]:
            expanded: list[str] = []
            seen: set[str] = set()
            queue = list(initial)
            while queue:
                name = queue.pop(0)
                if name in seen:
                    continue
                seen.add(name)
                expanded.append(name)
                lib = ctx.get_library(name)
                if lib:
                    # For static libraries, even private dependencies propagate to the consumer
                    # but only when we are expanding for linking, not for compile flags
                    if follow_private_of_static and lib.lib_type == "STATIC":
                        deps = list(
                            dict.fromkeys(
                                lib.link_libraries + lib.public_link_libraries
                            )
                        )
                    else:
                        deps = lib.public_link_libraries
                    for dep in deps:
                        if dep not in seen:
                            queue.append(dep)
            return expanded

        # Generate build statements for libraries
        for lib in ctx.libraries:
            if lib.is_alias:
                continue
            objects: list[str] = []

            # Collect compile flags from global options, compile definitions, compile features, include dirs, and linked libraries
            lib_compile_flags: list[str] = list(ctx.compile_options)
            for definition in ctx.compile_definitions:
                lib_compile_flags.append(f"-D{strip_generator_expressions(definition)}")
            for definition in lib.compile_definitions:
                lib_compile_flags.append(f"-D{strip_generator_expressions(definition)}")
            for feature in lib.compile_features:
                flag = compile_feature_to_flag(feature)
                if flag:
                    lib_compile_flags.append(flag)
            for inc_dir in lib.include_directories:
                inc = strip_generator_expressions(inc_dir)
                lib_compile_flags.append(f"-I{_ninja_flag_path(inc)}")

            # Propagate flags from dependencies
            # For compilation, we only follow public dependencies
            expanded_lib_link_libraries = expand_link_libraries(
                lib.link_libraries, follow_private_of_static=False
            )
            for dep_name in expanded_lib_link_libraries:
                dep_lib = ctx.get_library(dep_name)
                if dep_lib:
                    for feature in dep_lib.public_compile_features:
                        flag = compile_feature_to_flag(feature)
                        if flag and flag not in lib_compile_flags:
                            lib_compile_flags.append(flag)
                    for inc_dir in dep_lib.public_include_directories:
                        inc = strip_generator_expressions(inc_dir)
                        inc_flag = f"-I{_ninja_flag_path(inc)}"
                        if inc_flag not in lib_compile_flags:
                            lib_compile_flags.append(inc_flag)
                    for definition in dep_lib.public_compile_definitions:
                        def_flag = f"-D{strip_generator_expressions(definition)}"
                        if def_flag not in lib_compile_flags:
                            lib_compile_flags.append(def_flag)
                if dep_name in ctx.imported_targets:
                    imported = ctx.imported_targets[dep_name]
                    if imported.cflags:
                        lib_compile_flags.append(imported.cflags)

            # Filter out headers from compileable sources
            compileable_sources: list[str] = [
                s for s in lib.sources if not is_header(s)
            ]

            for source in compileable_sources:
                actual_source = source
                if source in custom_command_outputs:
                    actual_source = f"$builddir/{source}"

                source_rel = Path(source)
                obj_subdir = source_rel.parent.as_posix()
                obj_basename = f"{lib.name}_{source_rel.stem}.o"
                if obj_subdir and obj_subdir != ".":
                    obj_name = f"$builddir/{obj_subdir}/{obj_basename}"
                else:
                    obj_name = f"$builddir/{obj_basename}"
                register_output(obj_name, lib.defined_file, lib.defined_line)
                objects.append(obj_name)

                # Determine if C or C++
                if source.endswith((".cpp", ".cxx", ".cc", ".C", ".mm", ".MM")):
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
                        source_compile_flags.append(f"-I{_ninja_flag_path(inc_dir)}")
                    for d in file_props.object_depends:
                        if d in custom_command_outputs:
                            source_depends.append(f"$builddir/{d}")
                        else:
                            source_depends.append(d)

                if rule == "cc":
                    source_compile_flags = [
                        flag
                        for flag in source_compile_flags
                        if not flag.startswith("-std=c++")
                    ]
                else:
                    source_compile_flags = [
                        flag
                        for flag in source_compile_flags
                        if not (
                            flag.startswith("-std=c")
                            and not flag.startswith("-std=c++")
                        )
                    ]

                source_vars: dict[str, str | list[str] | None] | None = None
                if source_compile_flags:
                    source_vars = cast(
                        dict[str, str | list[str] | None],
                        {"cflags": " ".join(source_compile_flags)},
                    )

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
                register_output(lib_name, lib.defined_file, lib.defined_line)
                n.build(lib_name, "ar", objects)
                n.newline()
                lib_outputs[lib.name] = lib_name

        # Second pass for aliases to map them to original outputs
        for lib in ctx.libraries:
            if lib.is_alias and lib.alias_for in lib_outputs:
                lib_outputs[lib.name] = lib_outputs[lib.alias_for]

        # Generate build statements for executables
        default_targets: list[str] = []

        for exe in ctx.executables:
            objects: list[str] = []
            uses_cxx = False
            # For compile flags, we only follow public dependencies
            expanded_compile_libraries = expand_link_libraries(
                exe.link_libraries, follow_private_of_static=False
            )
            # For linking, static libraries propagate their private dependencies
            expanded_link_libraries = expand_link_libraries(
                exe.link_libraries, follow_private_of_static=True
            )

            # Collect cflags from global options, compile definitions, compile features, include dirs, linked libraries, and imported targets
            compile_flags: list[str] = list(ctx.compile_options)
            for definition in ctx.compile_definitions:
                compile_flags.append(f"-D{strip_generator_expressions(definition)}")
            for definition in exe.compile_definitions:
                compile_flags.append(f"-D{strip_generator_expressions(definition)}")
            for feature in exe.compile_features:
                flag = compile_feature_to_flag(feature)
                if flag:
                    compile_flags.append(flag)
            for inc_dir in exe.include_directories:
                inc = strip_generator_expressions(inc_dir)
                compile_flags.append(f"-I{_ninja_flag_path(inc)}")

            for lib_name in expanded_compile_libraries:
                # Check for public compile features from linked libraries
                linked_lib = ctx.get_library(lib_name)

                if linked_lib:
                    for feature in linked_lib.public_compile_features:
                        flag = compile_feature_to_flag(feature)
                        if flag and flag not in compile_flags:
                            compile_flags.append(flag)
                    # Check for public include directories from linked libraries
                    for inc_dir in linked_lib.public_include_directories:
                        inc = strip_generator_expressions(inc_dir)
                        inc_flag = f"-I{_ninja_flag_path(inc)}"
                        if inc_flag not in compile_flags:
                            compile_flags.append(inc_flag)
                    # Check for public compile definitions from linked libraries
                    for definition in linked_lib.public_compile_definitions:
                        def_flag = f"-D{strip_generator_expressions(definition)}"
                        if def_flag not in compile_flags:
                            compile_flags.append(def_flag)
                # Check for cflags from imported targets
                if lib_name in ctx.imported_targets:
                    imported = ctx.imported_targets[lib_name]
                    if imported.cflags:
                        compile_flags.append(imported.cflags)

            # Filter out headers from compileable sources
            compileable_sources: list[str] = [
                s for s in exe.sources if not is_header(s)
            ]

            for source in compileable_sources:
                actual_source = source
                if source in custom_command_outputs:
                    actual_source = f"$builddir/{source}"

                source_rel = Path(source)
                obj_subdir = source_rel.parent.as_posix()
                obj_basename = f"{exe.name}_{source_rel.stem}.o"
                if obj_subdir and obj_subdir != ".":
                    obj_name = f"$builddir/{obj_subdir}/{obj_basename}"
                else:
                    obj_name = f"$builddir/{obj_basename}"
                register_output(obj_name, exe.defined_file, exe.defined_line)
                objects.append(obj_name)

                # Determine if C or C++
                if source.endswith((".cpp", ".cxx", ".cc", ".C", ".mm", ".MM")):
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
                        source_compile_flags.append(f"-I{_ninja_flag_path(inc_dir)}")
                    for d in file_props.object_depends:
                        if d in custom_command_outputs:
                            source_depends.append(f"$builddir/{d}")
                        else:
                            source_depends.append(d)

                if rule == "cc":
                    source_compile_flags = [
                        flag
                        for flag in source_compile_flags
                        if not flag.startswith("-std=c++")
                    ]
                else:
                    source_compile_flags = [
                        flag
                        for flag in source_compile_flags
                        if not (
                            flag.startswith("-std=c")
                            and not flag.startswith("-std=c++")
                        )
                    ]

                source_vars: dict[str, str | list[str] | None] | None = None
                if source_compile_flags:
                    source_vars = cast(
                        dict[str, str | list[str] | None],
                        {"cflags": " ".join(source_compile_flags)},
                    )

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

            # Propagate link directories from dependencies
            for lib_name in expanded_link_libraries:
                linked_lib = ctx.get_library(lib_name)
                if linked_lib:
                    for link_dir in linked_lib.public_link_directories:
                        if link_dir not in exe.link_directories:
                            exe.link_directories.append(link_dir)

            for link_dir in exe.link_directories:
                link_flags.append(f"-L{_ninja_flag_path(link_dir)}")
            for lib_name in expanded_link_libraries:
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
                else:
                    # Generic library name or path
                    if (
                        lib_name.startswith("-")
                        or lib_name.startswith("/")
                        or lib_name.startswith("$")
                        or "." in lib_name
                    ):
                        framework_flags = framework_link_flags(lib_name)
                        if framework_flags:
                            link_flags.extend(framework_flags)
                        else:
                            link_flags.append(lib_name)
                    else:
                        link_flags.append(f"-l{lib_name}")

            # Link
            exe_name = f"$builddir/{exe.name}{exe_ext}"
            register_output(exe_name, exe.defined_file, exe.defined_line)
            link_rule = "link_cxx" if uses_cxx else "link"
            variables: dict[str, str | list[str] | None] = {}
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
                command="cd $builddir && $cmd",
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
                    if target_exe.startswith("$builddir/"):
                        cmd[0] = "./" + target_exe[len("$builddir/") :]
                    else:
                        cmd[0] = target_exe
                    depends.append(target_exe)

                test_target = f"test_{test.name}"
                register_output(test_target, None, 0)
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

        # Generate install runner
        if ctx.install_targets:
            n.rule(
                "install_file",
                command="mkdir -p $out_dir && cp $in $out",
                description="INSTALL $out",
            )
            n.newline()

            install_files: list[str] = []
            for install in ctx.install_targets:
                for target in install.targets:
                    src = None
                    if target in exe_outputs:
                        src = exe_outputs[target]
                    elif target in lib_outputs:
                        src = lib_outputs[target]

                    if src:
                        dest = f"{install.destination}/{Path(src).name.replace('$builddir/', '')}"
                        register_output(dest, None, 0)
                        n.build(
                            dest,
                            "install_file",
                            src,
                            variables={"out_dir": install.destination},
                        )
                        install_files.append(dest)

            n.newline()
            n.build("install", "phony", install_files)
            n.newline()

        # Generate run runner
        if ctx.executables:
            n.rule(
                "run_exe",
                command="$in",
                description="RUN $in",
                pool="console",
            )
            n.newline()
            run_target = ctx.executables[0].name

            # Check for VS_STARTUP_PROJECT property on the root directory
            root_dir = str(ctx.source_dir)
            if root_dir in ctx.directory_properties:
                startup_proj = ctx.directory_properties[root_dir].get(
                    "VS_STARTUP_PROJECT"
                )
                if startup_proj:
                    run_target = startup_proj

            if run_target in exe_outputs:
                n.build("run", "run_exe", exe_outputs[run_target])
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
) -> BuildContext:
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

    ctx = BuildContext(
        source_dir=source_dir,
        build_dir=source_dir / build_dir,
    )
    ctx.record_cmake_file(cmake_file)

    commands = parse_file(cmake_file)

    # Create build directory early (needed for variables that reference it)
    ctx.build_dir.mkdir(parents=True, exist_ok=True)

    # Set variables from command line (-D flags) first
    # These are cache variables that won't be overridden by set()
    if variables:
        ctx.variables.update(variables)
        ctx.cache_variables.update(variables.keys())

    # Set up standard CMake variables
    ctx.variables["CMAKE_SOURCE_DIR"] = str(ctx.source_dir)
    ctx.variables["CMAKE_BINARY_DIR"] = str(ctx.build_dir)
    ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] = str(ctx.source_dir)
    ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(ctx.build_dir)
    ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(ctx.current_list_file)
    ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(ctx.current_list_file.parent)
    ctx.variables["CMAKE_MODULE_PATH"] = ""
    ctx.variables["CMAKE_FIND_PACKAGE_REDIRECTS_DIR"] = str(
        ctx.build_dir / "CMakeFiles" / "pkgRedirects"
    )

    if platform.system() == "Darwin":
        ctx.variables["CMAKE_SYSTEM_NAME"] = "Darwin"
        ctx.variables["UNIX"] = "TRUE"
        ctx.variables["APPLE"] = "TRUE"
    elif platform.system() == "Windows":
        ctx.variables["CMAKE_SYSTEM_NAME"] = "Windows"
        ctx.variables["WIN32"] = "TRUE"
    else:
        ctx.variables["CMAKE_SYSTEM_NAME"] = "Linux"
        ctx.variables["UNIX"] = "TRUE"

    # Set up compilers from variables if provided
    if "CMAKE_C_COMPILER" in ctx.variables:
        ctx.c_compiler = ctx.variables["CMAKE_C_COMPILER"]
    if "CMAKE_CXX_COMPILER" in ctx.variables:
        ctx.cxx_compiler = ctx.variables["CMAKE_CXX_COMPILER"]

    process_commands(commands, ctx, trace, strict)

    # Generate ninja manifest in source directory (named after build dir)
    output_path = source_dir / f"{build_dir}.ninja"
    generate_ninja(ctx, output_path, build_dir, strict=strict)

    # Generate compilation database
    try:
        compdb = subprocess.check_output(
            ["ninja", "-f", str(output_path), "-t", "compdb"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        (ctx.build_dir / "compile_commands.json").write_text(compdb)
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Ignore errors if ninja is not found or fails
        pass

    print(f"{colored('Configured', 'green', attrs=['bold'])} {build_dir}.ninja")
    return ctx
