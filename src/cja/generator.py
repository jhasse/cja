"""Ninja build file generator."""

from dataclasses import dataclass, field
import hashlib
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, cast

from .utils import is_truthy, make_relative, strip_generator_expressions
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
    handle_configure_file,
    handle_file,
    handle_function,
    handle_get_directory_property,
    handle_get_filename_component,
    handle_get_property,
    handle_include_directories,
    handle_cmake_parse_arguments,
    handle_cmake_dependent_option,
    handle_list,
    handle_macro,
    handle_math,
    handle_option,
    handle_set,
    handle_set_property,
    handle_set_target_properties,
    handle_string,
    handle_target_compile_definitions,
    handle_target_compile_options,
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


def _infer_compiler_id(compiler: str) -> str:
    """Infer CMake-style compiler ID from a compiler command."""
    parts = shlex.split(compiler) if compiler else []
    if not parts:
        return "Unknown"
    tool = parts[0]
    if Path(tool).name.lower() in ("ccache", "sccache") and len(parts) > 1:
        tool = parts[1]
    base = Path(tool).name.lower()

    if base in ("clang", "clang++", "clang-cl") or "clang" in base:
        return "Clang"
    if base in ("gcc", "g++") or base.startswith("gcc-") or base.startswith("g++-"):
        return "GNU"
    if base in ("cl", "cl.exe"):
        return "MSVC"
    if base in ("icx", "icpx", "dpcpp"):
        return "IntelLLVM"
    if base in ("icc", "icpc"):
        return "Intel"

    # Fallback for generic compiler driver names like cc/c++.
    try:
        out = subprocess.check_output(
            parts + ["--version"],
            stderr=subprocess.STDOUT,
            text=True,
        ).lower()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "Unknown"

    if "clang" in out:
        return "Clang"
    if "gcc" in out or "gnu" in out:
        return "GNU"
    if "microsoft" in out or "msvc" in out:
        return "MSVC"
    if "intel" in out and ("llvm" in out or "oneapi" in out):
        return "IntelLLVM"
    if "intel" in out:
        return "Intel"

    return "Unknown"


def _detect_host_system_processor() -> str:
    """Detect host CPU architecture string for CMAKE_HOST_SYSTEM_PROCESSOR."""
    machine = platform.machine().strip()
    if machine:
        return machine
    processor = platform.processor().strip()
    if processor:
        return processor
    return "unknown"


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


def is_rc(filename: str) -> bool:
    """Check if a filename refers to a Windows resource script."""
    return filename.lower().endswith(".rc")


def is_manifest(filename: str) -> bool:
    """Check if a filename refers to a Windows manifest file."""
    return filename.lower().endswith(".manifest")


def _rc_manifest_deps(ctx: BuildContext, rc_path: str) -> list[str]:
    """Extract manifest file paths referenced by RT_MANIFEST in .rc file."""
    deps: list[str] = []
    abs_path = ctx.source_dir / rc_path
    if not abs_path.exists():
        return deps
    try:
        content = abs_path.read_text(encoding="utf-8", errors="replace")
        # Match RT_MANIFEST "filename" or RT_MANIFEST 'filename'
        for match in re.finditer(r"RT_MANIFEST\s+[\"']([^\"']+)[\"']", content, re.I):
            manifest_ref = match.group(1)
            rc_dir = Path(rc_path).parent
            if rc_dir and rc_dir != Path("."):
                manifest_path = (rc_dir / manifest_ref).as_posix()
            else:
                manifest_path = manifest_ref
            deps.append(manifest_path)
    except OSError, UnicodeDecodeError:
        pass
    return deps


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


def _is_windows_clangxx(cxx: str) -> bool:
    if platform.system() != "Windows":
        return False
    parts = shlex.split(cxx) if cxx else []
    tool = parts[0] if parts else cxx
    name = Path(tool).name.lower()
    return name in ("clang++", "clang++.exe")


def _normalize_windows_clang_cxx_std(flag: str, enabled: bool) -> str:
    if not enabled:
        return flag
    return re.sub(r"(?<!\S)-std=c\+\+11(?=\s|$)", "-std=c++14", flag)


def _format_compile_definition_flag(definition: str) -> str:
    """Format a compile definition as a compiler -D flag."""
    normalized = strip_generator_expressions(definition)
    escaped = re.sub(r'(?<!\\)"', r'\\"', normalized)
    return f"-D{escaped}"


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


_VERSION_RE = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def _version_components(version: str) -> tuple[str, str, str]:
    match = _VERSION_RE.match(version.strip())
    if not match:
        return "0", "0", "0"
    major = match.group(1) or "0"
    minor = match.group(2) or "0"
    patch = match.group(3) or "0"
    return major, minor, patch


def _render_basic_package_version_file(
    version: str,
    compatibility: str,
    arch_independent: bool,
    ctx: BuildContext,
) -> str:
    major, minor, _ = _version_components(version)
    arch_block = ""
    if arch_independent:
        arch_block = "set(PACKAGE_VERSION_UNSUITABLE FALSE)\n"
    else:
        sizeof_void_p = ctx.variables.get(
            "CMAKE_SIZEOF_VOID_P", "${CMAKE_SIZEOF_VOID_P}"
        )
        arch_block = (
            f'set(PACKAGE_VERSION_SIZEOF_VOID_P "{sizeof_void_p}")\n'
            "if(NOT CMAKE_SIZEOF_VOID_P STREQUAL PACKAGE_VERSION_SIZEOF_VOID_P)\n"
            "  set(PACKAGE_VERSION_UNSUITABLE TRUE)\n"
            "endif()\n"
        )

    return (
        f'set(PACKAGE_VERSION "{version}")\n'
        "set(PACKAGE_VERSION_COMPATIBLE FALSE)\n"
        "set(PACKAGE_VERSION_EXACT FALSE)\n"
        f"{arch_block}"
        "if(PACKAGE_VERSION VERSION_LESS PACKAGE_FIND_VERSION)\n"
        "  set(PACKAGE_VERSION_COMPATIBLE FALSE)\n"
        "else()\n"
        f'  if("{compatibility}" STREQUAL "AnyNewerVersion")\n'
        "    set(PACKAGE_VERSION_COMPATIBLE TRUE)\n"
        f'  elseif("{compatibility}" STREQUAL "SameMajorVersion")\n'
        f'    if(PACKAGE_FIND_VERSION_MAJOR STREQUAL "{major}")\n'
        "      set(PACKAGE_VERSION_COMPATIBLE TRUE)\n"
        "    endif()\n"
        f'  elseif("{compatibility}" STREQUAL "SameMinorVersion")\n'
        f'    if(PACKAGE_FIND_VERSION_MAJOR STREQUAL "{major}" AND '
        f'PACKAGE_FIND_VERSION_MINOR STREQUAL "{minor}")\n'
        "      set(PACKAGE_VERSION_COMPATIBLE TRUE)\n"
        "    endif()\n"
        f'  elseif("{compatibility}" STREQUAL "ExactVersion")\n'
        "    if(PACKAGE_FIND_VERSION STREQUAL PACKAGE_VERSION)\n"
        "      set(PACKAGE_VERSION_COMPATIBLE TRUE)\n"
        "    endif()\n"
        "  endif()\n"
        "endif()\n"
        "if(PACKAGE_VERSION_COMPATIBLE AND PACKAGE_FIND_VERSION STREQUAL PACKAGE_VERSION)\n"
        "  set(PACKAGE_VERSION_EXACT TRUE)\n"
        "endif()\n"
        "if(NOT DEFINED PACKAGE_VERSION_UNSUITABLE)\n"
        "  set(PACKAGE_VERSION_UNSUITABLE FALSE)\n"
        "endif()\n"
    )


def _render_package_init_block(
    install_destination: str,
    *,
    no_set_and_check_macro: bool,
    no_check_required_components_macro: bool,
) -> str:
    install_destination = install_destination.replace("\\", "/").strip()
    if install_destination.startswith("/"):
        prefix_expr = install_destination
    else:
        parts = [p for p in install_destination.split("/") if p and p != "."]
        up = "/".join([".."] * len(parts))
        prefix_expr = "${CMAKE_CURRENT_LIST_DIR}" if not up else f"${{CMAKE_CURRENT_LIST_DIR}}/{up}"

    lines = [
        "# Generated by cja: configure_package_config_file()",
        f'get_filename_component(PACKAGE_PREFIX_DIR "{prefix_expr}" ABSOLUTE)',
        "",
    ]

    if not no_set_and_check_macro:
        lines.extend(
            [
                "macro(set_and_check _var _file)",
                "  set(${_var} \"${_file}\")",
                "  if(NOT EXISTS \"${_file}\")",
                "    message(FATAL_ERROR \"File or directory ${_file} referenced by ${_var} does not exist\")",
                "  endif()",
                "endmacro()",
                "",
            ]
        )

    if not no_check_required_components_macro:
        lines.extend(
            [
                "macro(check_required_components _NAME)",
                "  foreach(comp ${${_NAME}_FIND_COMPONENTS})",
                "    if(NOT ${_NAME}_${comp}_FOUND)",
                "      if(${_NAME}_FIND_REQUIRED_${comp})",
                "        set(${_NAME}_FOUND FALSE)",
                "      endif()",
                "    endif()",
                "  endforeach()",
                "endmacro()",
                "",
            ]
        )

    return "\n".join(lines)


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
            saved_parent_scope_vars = ctx.parent_scope_vars
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
                ctx.parent_scope_vars = saved_parent_scope_vars

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
                ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] = str(
                    saved_current_source_dir
                )
                ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(saved_current_list_file)
                ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                    saved_current_list_file.parent
                )
                ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(ctx.build_dir)
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
            or (token.startswith('"${') and token.endswith('}"'))
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
        if_args.append(
            ctx.expand_variables(
                arg,
                strict,
                cmd.line,
                allow_undefined_empty=allow_undefined,
                allow_undefined_warning="${${" in arg,
            )
        )
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
                        arg,
                        strict,
                        commands[block_idx].line,
                        allow_undefined_empty=allow_undefined,
                        allow_undefined_warning="${${" in arg,
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
    ctx.variables["CMAKE_COMMAND"] = "cja"
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
            git_repo = None
            git_tag = None
            src_dir: Path | None = None
            arg_idx = 0
            while arg_idx < len(info.args):
                if info.args[arg_idx] == "URL" and arg_idx + 1 < len(info.args):
                    url = info.args[arg_idx + 1]
                    arg_idx += 2
                elif info.args[arg_idx] == "URL_HASH" and arg_idx + 1 < len(info.args):
                    url_hash = info.args[arg_idx + 1]
                    arg_idx += 2
                elif info.args[arg_idx] == "GIT_REPOSITORY" and arg_idx + 1 < len(
                    info.args
                ):
                    git_repo = info.args[arg_idx + 1]
                    arg_idx += 2
                elif info.args[arg_idx] == "GIT_TAG" and arg_idx + 1 < len(info.args):
                    git_tag = info.args[arg_idx + 1]
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
            elif git_repo:
                deps_dir = ctx.build_dir / "_deps"
                deps_dir.mkdir(parents=True, exist_ok=True)
                src_dir = deps_dir / f"{name.lower()}-src"

                if not src_dir.exists():
                    print(f"Cloning {name} from {git_repo}")
                    fetch_cmd_line = frame.fetchcontent_cmd.line if frame.fetchcontent_cmd else 0
                    try:
                        clone_cmd = ["git", "clone"]
                        if git_tag:
                            clone_cmd.extend(["--branch", git_tag])
                        clone_cmd.extend([git_repo, str(src_dir)])
                        subprocess.run(clone_cmd, check=True)
                    except FileNotFoundError:
                        if strict:
                            ctx.print_error(
                                "git is required for FetchContent GIT_REPOSITORY",
                                fetch_cmd_line,
                            )
                            sys.exit(1)
                    except subprocess.CalledProcessError:
                        if strict:
                            ctx.print_error(
                                f"git clone failed for {git_repo}", fetch_cmd_line
                            )
                            sys.exit(1)
                elif git_tag:
                    fetch_cmd_line = frame.fetchcontent_cmd.line if frame.fetchcontent_cmd else 0
                    try:
                        subprocess.run(
                            ["git", "-C", str(src_dir), "checkout", git_tag], check=True
                        )
                    except FileNotFoundError, subprocess.CalledProcessError:
                        if strict:
                            ctx.print_error(
                                f"git checkout failed for {git_repo} ({git_tag})",
                                fetch_cmd_line,
                            )
                            sys.exit(1)

            if (url or git_repo) and src_dir is not None:
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
                        saved_parent_directory = ctx.parent_directory
                        saved_vars = ctx.variables.copy()
                        saved_parent_scope_vars = ctx.parent_scope_vars
                        ctx.parent_scope_vars = {}

                        ctx.current_source_dir = actual_src_dir
                        ctx.current_list_file = sub_cmakelists
                        ctx.parent_directory = str(saved_current_source_dir)
                        ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] = str(actual_src_dir)
                        ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(sub_cmakelists)
                        ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                            sub_cmakelists.parent
                        )
                        ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(ctx.build_dir)

                        def on_exit_fetchcontent(
                            saved_current_source_dir: Path = saved_current_source_dir,
                            saved_current_list_file: Path = saved_current_list_file,
                            saved_parent_directory: str = saved_parent_directory,
                            saved_vars: dict[str, str] = saved_vars,
                            saved_parent_scope_vars: dict[str, str | None] = saved_parent_scope_vars,
                        ) -> None:
                            cache_updates = {
                                k: v for k, v in ctx.variables.items() if k in ctx.cache_variables
                            }
                            parent_scope_updates = ctx.parent_scope_vars
                            ctx.parent_scope_vars = saved_parent_scope_vars
                            ctx.current_source_dir = saved_current_source_dir
                            ctx.current_list_file = saved_current_list_file
                            ctx.parent_directory = saved_parent_directory
                            ctx.variables = saved_vars
                            ctx.variables.update(cache_updates)
                            for var, val in parent_scope_updates.items():
                                if val is None:
                                    ctx.variables.pop(var, None)
                                else:
                                    ctx.variables[var] = val
                            ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] = str(
                                saved_current_source_dir
                            )
                            ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(
                                saved_current_list_file
                            )
                            ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                                saved_current_list_file.parent
                            )
                            ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(
                                ctx.build_dir
                            )

                        stack.append(
                            Frame(commands=sub_commands, on_exit=on_exit_fetchcontent)
                        )
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
            allow_undefined_warning = "${${" in arg
            if cmd.name in ("if", "elseif"):
                allow_undefined = (
                    idx + 2 < len(cmd.args)
                    and cmd.args[idx + 1] == "STREQUAL"
                    and cmd.args[idx + 2] in ("", '""', "''")
                    and (
                        (arg.startswith("${") and arg.endswith("}"))
                        or (arg.startswith('"${') and arg.endswith('}"'))
                        or (arg.startswith("'${") and arg.endswith("}'"))
                    )
                )
            expanded = ctx.expand_variables(
                arg,
                strict,
                cmd.line,
                allow_undefined_empty=allow_undefined,
                allow_undefined_warning=allow_undefined_warning,
            )
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
                if func_index is not None:
                    while len(stack) > func_index:
                        popped = stack.pop()
                        if popped.on_exit:
                            popped.on_exit()
                    continue

                include_index = next(
                    (
                        i
                        for i in range(len(stack) - 1, -1, -1)
                        if stack[i].kind == "include"
                    ),
                    None,
                )
                if include_index is not None:
                    while len(stack) > include_index:
                        popped = stack.pop()
                        if popped.on_exit:
                            popped.on_exit()
                    continue

                raise ReturnFromFunction()
                continue

            case "cmake_policy":
                if args:
                    subcommand = args[0].upper()
                    if subcommand == "SET" and len(args) >= 3:
                        policy = args[1]
                        value = args[2].upper()
                        if value == "OLD":
                            ctx.print_warning(
                                f"cmake_policy(SET {policy} OLD) is called, but cja always uses NEW behavior for all policies",
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
                if not args:
                    if strict:
                        ctx.print_error(
                            "cmake_minimum_required requires VERSION argument",
                            cmd.line,
                        )
                        sys.exit(1)
                    frame.pc += 1
                    continue

                version = ""
                i = 0
                while i < len(args):
                    arg = args[i]
                    if arg == "VERSION" and i + 1 < len(args):
                        version = args[i + 1]
                        break
                    i += 1

                if not version:
                    if strict:
                        ctx.print_error(
                            "cmake_minimum_required missing VERSION argument",
                            cmd.line,
                        )
                        sys.exit(1)
                    frame.pc += 1
                    continue

                # CMake accepts a policy max range in the form "x.y...a.b".
                minimum_version = version.split("...", 1)[0]
                ctx.variables["CMAKE_MINIMUM_REQUIRED_VERSION"] = minimum_version

            case "project":
                if args:
                    project_name = args[0]
                    ctx.project_name = project_name
                    ctx.variables["PROJECT_NAME"] = project_name
                    ctx.variables["CMAKE_PROJECT_NAME"] = project_name
                    ctx.variables["CMAKE_C_FLAGS"] = (
                        ""  # TODO: Only set when C is enabled
                    )
                    ctx.variables["CMAKE_CXX_FLAGS"] = (
                        ""  # TODO: Only set when CXX is enabled
                    )
                    ctx.variables["PROJECT_SOURCE_DIR"] = str(ctx.current_source_dir)
                    ctx.variables["PROJECT_BINARY_DIR"] = str(ctx.build_dir)
                    source_var = f"{project_name}_SOURCE_DIR"
                    binary_var = f"{project_name}_BINARY_DIR"
                    ctx.variables[source_var] = str(ctx.current_source_dir)
                    ctx.variables[binary_var] = str(ctx.build_dir)
                    # Keep project source/binary dirs globally visible across scopes
                    # (e.g. when project() is called in add_subdirectory()).
                    ctx.cache_variables.add(source_var)
                    ctx.cache_variables.add(binary_var)

                    if "VERSION" in args:
                        ver_idx = args.index("VERSION")
                        if ver_idx + 1 < len(args):
                            version = args[ver_idx + 1]
                            ctx.variables["PROJECT_VERSION"] = version
                            ctx.variables[f"{project_name}_VERSION"] = version

                            # Workaround for https://github.com/erincatto/box2d/pull/1033:
                            ctx.variables[f"{project_name.upper()}_VERSION"] = version

                            ctx.variables["CMAKE_PROJECT_VERSION"] = version
                            parts = version.split(".")
                            for i, suffix in enumerate(
                                ("MAJOR", "MINOR", "PATCH", "TWEAK")
                            ):
                                val = parts[i] if i < len(parts) else ""
                                ctx.variables[f"PROJECT_VERSION_{suffix}"] = val
                                ctx.variables[f"{project_name}_VERSION_{suffix}"] = val
                                ctx.variables[f"CMAKE_PROJECT_VERSION_{suffix}"] = val

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
                        saved_parent_scope_vars = ctx.parent_scope_vars
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

                        def on_exit_add_subdirectory(
                            saved_current_source_dir: Path = saved_current_source_dir,
                            saved_current_list_file: Path = saved_current_list_file,
                            saved_parent_directory: str = saved_parent_directory,
                            saved_vars: dict[str, str] = saved_vars,
                            saved_parent_scope_vars: dict[str, str | None] = saved_parent_scope_vars,
                        ) -> None:
                            cache_updates = {
                                k: v for k, v in ctx.variables.items() if k in ctx.cache_variables
                            }
                            parent_scope_updates = ctx.parent_scope_vars
                            ctx.parent_scope_vars = saved_parent_scope_vars
                            ctx.current_source_dir = saved_current_source_dir
                            ctx.current_list_file = saved_current_list_file
                            ctx.parent_directory = saved_parent_directory
                            ctx.variables = saved_vars
                            ctx.variables.update(cache_updates)
                            for var, val in parent_scope_updates.items():
                                if val is None:
                                    ctx.variables.pop(var, None)
                                else:
                                    ctx.variables[var] = val
                            ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] = str(
                                saved_current_source_dir
                            )
                            ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(
                                saved_current_list_file
                            )
                            ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                                saved_current_list_file.parent
                            )
                            ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(
                                ctx.build_dir
                            )

                        stack.append(
                            Frame(commands=sub_commands, on_exit=on_exit_add_subdirectory)
                        )
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

            case "cmake_dependent_option":
                handle_cmake_dependent_option(ctx, cmd, args, strict)

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
                    include_options = {arg.upper() for arg in args[1:]}
                    optional_include = "OPTIONAL" in include_options
                    known_modules = {
                        "CMakePackageConfigHelpers",
                        "CMakeParseArguments",
                        "CTest",
                        "CheckIPOSupported",
                        "CheckCXXCompilerFlag",
                        "CheckCCompilerFlag",
                        "CheckCXXSymbolExists",
                        "CheckSymbolExists",
                        "CMakeDependentOption",
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

                            def on_exit_include(
                                saved_list_file: Path = saved_list_file,
                            ) -> None:
                                ctx.current_list_file = saved_list_file
                                ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(
                                    saved_list_file
                                )
                                ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                                    saved_list_file.parent
                                )

                            stack.append(
                                Frame(
                                    commands=inc_commands,
                                    on_exit=on_exit_include,
                                    kind="include",
                                )
                            )
                            frame.pc += 1
                            continue
                        elif strict and not optional_include:
                            ctx.print_error(
                                f"include() could not find file: {module_name}",
                                cmd.line,
                            )
                            sys.exit(1)
                    elif module_name not in known_modules:
                        # Resolve bare module names from CMAKE_MODULE_PATH.
                        module_path = ctx.variables.get("CMAKE_MODULE_PATH", "")
                        search_dirs = module_path.split(";") if module_path else []
                        found_file: Path | None = None
                        for d in search_dirs:
                            if not d:
                                continue
                            path = Path(d)
                            if not path.is_absolute():
                                path = ctx.current_source_dir / path
                            candidate = path / f"{module_name}.cmake"
                            if candidate.exists():
                                found_file = candidate
                                break

                        if found_file:
                            from .parser import parse_file

                            ctx.record_cmake_file(found_file)
                            inc_commands = parse_file(found_file)
                            saved_list_file = ctx.current_list_file
                            ctx.current_list_file = found_file
                            ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(found_file)
                            ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                                found_file.parent
                            )

                            def on_exit_include(
                                saved_list_file: Path = saved_list_file,
                            ) -> None:
                                ctx.current_list_file = saved_list_file
                                ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(
                                    saved_list_file
                                )
                                ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                                    saved_list_file.parent
                                )

                            stack.append(
                                Frame(
                                    commands=inc_commands,
                                    on_exit=on_exit_include,
                                    kind="include",
                                )
                            )
                            frame.pc += 1
                            continue
                        elif strict and not optional_include:
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

            case "try_compile":
                # Minimal support for:
                # try_compile(<result> <bindir> SOURCES <src>... [OUTPUT_VARIABLE <var>])
                if len(args) >= 2:
                    result_var = args[0]
                    bindir = Path(args[1])
                    if not bindir.is_absolute():
                        bindir = ctx.current_source_dir / bindir
                    bindir.mkdir(parents=True, exist_ok=True)

                    sources: list[str] = []
                    output_var = ""
                    option_tokens = {
                        "SOURCES",
                        "OUTPUT_VARIABLE",
                        "CMAKE_FLAGS",
                        "COMPILE_DEFINITIONS",
                        "LINK_LIBRARIES",
                        "COPY_FILE",
                        "COPY_FILE_ERROR",
                        "LINK_OPTIONS",
                        "LINKER_LANGUAGE",
                    }
                    i = 2
                    while i < len(args):
                        token = args[i]
                        if token == "SOURCES":
                            i += 1
                            while i < len(args) and args[i] not in option_tokens:
                                sources.append(args[i])
                                i += 1
                            continue
                        if token == "OUTPUT_VARIABLE" and i + 1 < len(args):
                            output_var = args[i + 1]
                            i += 2
                            continue
                        # Ignore unsupported options for now.
                        i += 1

                    success = True
                    compile_output = ""
                    if not sources:
                        success = False
                    for source in sources:
                        src_path = Path(source)
                        if not src_path.is_absolute():
                            src_path = ctx.current_source_dir / src_path
                        obj_name = f"{src_path.stem}.o"
                        obj_path = bindir / obj_name
                        compiler = (
                            ctx.cxx_compiler
                            if src_path.suffix.lower()
                            in (".cpp", ".cxx", ".cc", ".c++", ".mm", ".mpp")
                            else ctx.c_compiler
                        )
                        result = subprocess.run(
                            [compiler, "-c", str(src_path), "-o", str(obj_path)],
                            capture_output=True,
                            text=True,
                        )
                        compile_output += result.stdout
                        compile_output += result.stderr
                        if result.returncode != 0:
                            success = False

                    ctx.variables[result_var] = "TRUE" if success else "FALSE"
                    if output_var:
                        ctx.variables[output_var] = compile_output.strip()

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

            case "target_compile_options":
                handle_target_compile_options(ctx, cmd, args, strict)

            case "include_directories":
                handle_include_directories(ctx, cmd, args, strict)

            case "write_basic_package_version_file":
                if not args:
                    frame.pc += 1
                    continue
                filename = args[0]
                version = None
                compatibility = None
                arch_independent = False
                arg_idx = 1
                while arg_idx < len(args):
                    token = args[arg_idx]
                    if token == "VERSION" and arg_idx + 1 < len(args):
                        version = args[arg_idx + 1]
                        arg_idx += 2
                    elif token == "COMPATIBILITY" and arg_idx + 1 < len(args):
                        compatibility = args[arg_idx + 1]
                        arg_idx += 2
                    elif token == "ARCH_INDEPENDENT":
                        arch_independent = True
                        arg_idx += 1
                    else:
                        arg_idx += 1

                if not version:
                    version = ctx.variables.get("PROJECT_VERSION")
                if not version or not compatibility:
                    if strict:
                        ctx.print_error(
                            "write_basic_package_version_file requires VERSION and COMPATIBILITY",
                            cmd.line,
                        )
                        sys.exit(1)
                    ctx.print_warning(
                        "write_basic_package_version_file missing VERSION or COMPATIBILITY",
                        cmd.line,
                    )
                    frame.pc += 1
                    continue

                output_path = Path(filename)
                if not output_path.is_absolute():
                    current_binary_dir = Path(
                        ctx.variables.get(
                            "CMAKE_CURRENT_BINARY_DIR", str(ctx.build_dir)
                        )
                    )
                    output_path = current_binary_dir / output_path
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    _render_basic_package_version_file(
                        version,
                        compatibility,
                        arch_independent,
                        ctx,
                    )
                )

            case "file":
                handle_file(ctx, cmd, args, strict)

            case "configure_file":
                handle_configure_file(ctx, cmd, args, strict)

            case "configure_package_config_file":
                # configure_package_config_file(<input> <output> INSTALL_DESTINATION <path> [PATH_VARS ...]
                #   [NO_SET_AND_CHECK_MACRO] [NO_CHECK_REQUIRED_COMPONENTS_MACRO])
                if len(args) < 2:
                    if strict:
                        ctx.print_error(
                            "configure_package_config_file requires input and output",
                            cmd.line,
                        )
                        sys.exit(1)
                    frame.pc += 1
                    continue

                input_path = args[0]
                output_path = args[1]
                install_destination = ""
                path_vars: list[str] = []
                no_set_and_check_macro = False
                no_check_required_components_macro = False

                option_tokens = {
                    "INSTALL_DESTINATION",
                    "PATH_VARS",
                    "NO_SET_AND_CHECK_MACRO",
                    "NO_CHECK_REQUIRED_COMPONENTS_MACRO",
                    "INSTALL_PREFIX",
                }
                idx = 2
                while idx < len(args):
                    token = args[idx]
                    if token == "INSTALL_DESTINATION" and idx + 1 < len(args):
                        install_destination = ctx.expand_variables(
                            args[idx + 1], strict, cmd.line
                        )
                        idx += 2
                        continue
                    if token == "PATH_VARS":
                        idx += 1
                        while idx < len(args) and args[idx] not in option_tokens:
                            path_vars.append(args[idx])
                            idx += 1
                        continue
                    if token == "NO_SET_AND_CHECK_MACRO":
                        no_set_and_check_macro = True
                        idx += 1
                        continue
                    if token == "NO_CHECK_REQUIRED_COMPONENTS_MACRO":
                        no_check_required_components_macro = True
                        idx += 1
                        continue
                    if token == "INSTALL_PREFIX":
                        # Accepted for compatibility, currently ignored.
                        idx += 2 if idx + 1 < len(args) else 1
                        continue
                    idx += 1

                if not install_destination:
                    if strict:
                        ctx.print_error(
                            "configure_package_config_file requires INSTALL_DESTINATION",
                            cmd.line,
                        )
                        sys.exit(1)
                    frame.pc += 1
                    continue

                temp_vars: dict[str, str] = {
                    "PACKAGE_INIT": _render_package_init_block(
                        install_destination,
                        no_set_and_check_macro=no_set_and_check_macro,
                        no_check_required_components_macro=no_check_required_components_macro,
                    )
                }
                for var_name in path_vars:
                    temp_vars[f"PACKAGE_{var_name}"] = ctx.variables.get(var_name, "")

                saved_vars: dict[str, str] = {}
                missing_vars: set[str] = set()
                for var_name, value in temp_vars.items():
                    if var_name in ctx.variables:
                        saved_vars[var_name] = ctx.variables[var_name]
                    else:
                        missing_vars.add(var_name)
                    ctx.variables[var_name] = value

                try:
                    handle_configure_file(
                        ctx,
                        cmd,
                        [input_path, output_path, "@ONLY"],
                        strict,
                    )
                finally:
                    for var_name, value in saved_vars.items():
                        ctx.variables[var_name] = value
                    for var_name in missing_vars:
                        ctx.variables.pop(var_name, None)

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

            case "export":
                # Support export(TARGETS ... FILE <file> [NAMESPACE <ns>]) as a no-op
                # that materializes the requested export file.
                if "FILE" in args:
                    file_idx = args.index("FILE")
                    if file_idx + 1 < len(args):
                        export_file = Path(args[file_idx + 1])
                        if not export_file.is_absolute():
                            current_binary_dir = Path(
                                ctx.variables.get(
                                    "CMAKE_CURRENT_BINARY_DIR", str(ctx.build_dir)
                                )
                            )
                            export_file = current_binary_dir / export_file
                        export_file.parent.mkdir(parents=True, exist_ok=True)
                        if not export_file.exists():
                            export_file.write_text(
                                "# Generated by cja: export() is partially supported.\n"
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
                    elif package_name in ("Python", "Python3"):
                        # Minimal support for find_package(Python COMPONENTS Interpreter)
                        components: list[str] = []
                        i = 1
                        while i < len(args):
                            token = args[i]
                            if token in ("COMPONENTS", "OPTIONAL_COMPONENTS"):
                                i += 1
                                while i < len(args) and args[i] not in (
                                    "REQUIRED",
                                    "QUIET",
                                    "COMPONENTS",
                                    "OPTIONAL_COMPONENTS",
                                    "EXACT",
                                    "MODULE",
                                    "CONFIG",
                                    "NO_MODULE",
                                ):
                                    components.append(args[i])
                                    i += 1
                                continue
                            i += 1

                        requested_components = set(components)
                        needs_interpreter = (
                            not requested_components
                            or "Interpreter" in requested_components
                        )
                        interpreter_path = sys.executable if needs_interpreter else ""
                        interpreter_found = bool(interpreter_path)
                        unsupported_components = requested_components - {"Interpreter"}
                        found = interpreter_found and not unsupported_components

                        ctx.variables[f"{package_name}_FOUND"] = (
                            "TRUE" if found else "FALSE"
                        )
                        if needs_interpreter:
                            ctx.variables[f"{package_name}_Interpreter_FOUND"] = (
                                "TRUE" if interpreter_found else "FALSE"
                            )
                            if interpreter_found:
                                ctx.variables[f"{package_name}_EXECUTABLE"] = (
                                    interpreter_path
                                )
                                ctx.imported_targets[
                                    f"{package_name}::Interpreter"
                                ] = ImportedTarget()

                        if required and not found:
                            ctx.print_error(
                                f"could not find package: {package_name}", cmd.line
                            )
                            raise SystemExit(1)
                        if not quiet:
                            if found:
                                print(f"{colored('?', 'green')} {package_name}")
                            else:
                                print(f"{colored('?', 'red')} {package_name}")

                    elif package_name == "PkgConfig":
                        ctx.variables["PkgConfig_FOUND"] = "TRUE"
                        ctx.variables["PKG_CONFIG_EXECUTABLE"] = "pkg-config"
                        if not quiet:
                            print(f"{colored('✓', 'green')} {package_name}")
                    elif package_name == "Fontconfig":
                        found = False
                        try:
                            result = subprocess.run(
                                ["pkg-config", "--exists", "fontconfig"],
                                capture_output=True,
                            )
                            if result.returncode == 0:
                                found = True
                                cflags_result = subprocess.run(
                                    ["pkg-config", "--cflags", "fontconfig"],
                                    capture_output=True,
                                    text=True,
                                )
                                libs_result = subprocess.run(
                                    ["pkg-config", "--libs", "fontconfig"],
                                    capture_output=True,
                                    text=True,
                                )
                                version_result = subprocess.run(
                                    ["pkg-config", "--modversion", "fontconfig"],
                                    capture_output=True,
                                    text=True,
                                )

                                fc_cflags = cflags_result.stdout.strip()
                                fc_libs = libs_result.stdout.strip()
                                fc_version = version_result.stdout.strip()

                                include_dirs = []
                                for entry in shlex.split(fc_cflags):
                                    if entry.startswith("-I"):
                                        include_dirs.append(entry[2:])

                                ctx.variables["Fontconfig_FOUND"] = "TRUE"
                                ctx.variables["FONTCONFIG_FOUND"] = "TRUE"
                                if include_dirs:
                                    ctx.variables["Fontconfig_INCLUDE_DIR"] = (
                                        include_dirs[0]
                                    )
                                    ctx.variables["Fontconfig_INCLUDE_DIRS"] = ";".join(
                                        include_dirs
                                    )
                                ctx.variables["Fontconfig_LIBRARIES"] = fc_libs
                                if fc_version:
                                    ctx.variables["Fontconfig_VERSION"] = fc_version
                                ctx.variables["Fontconfig_COMPILE_OPTIONS"] = fc_cflags

                                ctx.imported_targets["Fontconfig::Fontconfig"] = (
                                    ImportedTarget(
                                        cflags=fc_cflags,
                                        libs=fc_libs,
                                    )
                                )
                        except FileNotFoundError:
                            pass

                        if found:
                            if not quiet:
                                print(f"{colored('✓', 'green')} {package_name}")
                        else:
                            ctx.variables["Fontconfig_FOUND"] = "FALSE"
                            ctx.variables["FONTCONFIG_FOUND"] = "FALSE"
                            if required:
                                ctx.print_error(
                                    "could not find package: Fontconfig", cmd.line
                                )
                                raise SystemExit(1)
                            if not quiet:
                                print(f"{colored('✗', 'red')} {package_name}")
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
                    elif package_name == "Boost":
                        keywords = {
                            "REQUIRED",
                            "QUIET",
                            "COMPONENTS",
                            "OPTIONAL_COMPONENTS",
                            "EXACT",
                            "MODULE",
                            "CONFIG",
                            "NO_MODULE",
                        }
                        required_components: list[str] = []
                        optional_components: list[str] = []
                        i = 1
                        while i < len(args):
                            token = args[i]
                            if token == "COMPONENTS":
                                i += 1
                                while i < len(args) and args[i] not in keywords:
                                    required_components.append(args[i])
                                    i += 1
                                continue
                            if token == "OPTIONAL_COMPONENTS":
                                i += 1
                                while i < len(args) and args[i] not in keywords:
                                    optional_components.append(args[i])
                                    i += 1
                                continue
                            i += 1

                        found = False
                        boost_cflags = ""
                        boost_libs = ""
                        boost_version = ""
                        include_dirs: list[str] = []
                        missing_required_components: list[str] = []

                        pkg_base = None
                        try:
                            for candidate in ("boost", "boost_headers"):
                                result = subprocess.run(
                                    ["pkg-config", "--exists", candidate],
                                    capture_output=True,
                                )
                                if result.returncode == 0:
                                    pkg_base = candidate
                                    break
                        except FileNotFoundError:
                            pkg_base = None

                        if pkg_base:
                            cflags_result = subprocess.run(
                                ["pkg-config", "--cflags", pkg_base],
                                capture_output=True,
                                text=True,
                            )
                            libs_result = subprocess.run(
                                ["pkg-config", "--libs", pkg_base],
                                capture_output=True,
                                text=True,
                            )
                            version_result = subprocess.run(
                                ["pkg-config", "--modversion", pkg_base],
                                capture_output=True,
                                text=True,
                            )
                            boost_cflags = cflags_result.stdout.strip()
                            boost_libs = libs_result.stdout.strip()
                            boost_version = version_result.stdout.strip()
                            found = True

                        if not found:
                            for include_root in (
                                "/usr/include",
                                "/usr/local/include",
                                "/opt/homebrew/include",
                            ):
                                version_header = (
                                    Path(include_root) / "boost/version.hpp"
                                )
                                if version_header.exists():
                                    include_dirs = [include_root]
                                    boost_cflags = f"-I{include_root}"
                                    found = True
                                    break

                        if boost_cflags:
                            for entry in shlex.split(boost_cflags):
                                if entry.startswith("-I"):
                                    include_dirs.append(entry[2:])

                        if found and not boost_version and include_dirs:
                            version_header = Path(include_dirs[0]) / "boost/version.hpp"
                            if version_header.exists():
                                try:
                                    header_text = version_header.read_text(
                                        encoding="utf-8"
                                    )
                                except UnicodeDecodeError:
                                    header_text = version_header.read_text(
                                        encoding="latin-1"
                                    )
                                version_match = re.search(
                                    r'#define\s+BOOST_LIB_VERSION\s+"([^"]+)"',
                                    header_text,
                                )
                                if version_match:
                                    boost_version = version_match.group(1).replace(
                                        "_", "."
                                    )

                        component_libs: list[str] = []
                        for component in required_components + optional_components:
                            pkg_component = f"boost_{component.lower()}"
                            component_found = False
                            component_cflags = ""
                            component_link_flags = ""
                            try:
                                result = subprocess.run(
                                    ["pkg-config", "--exists", pkg_component],
                                    capture_output=True,
                                )
                                component_found = result.returncode == 0
                            except FileNotFoundError:
                                component_found = False

                            var_name = f"Boost_{component}_FOUND"
                            upper_var_name = f"Boost_{component.upper()}_FOUND"
                            if component_found:
                                cflags_result = subprocess.run(
                                    ["pkg-config", "--cflags", pkg_component],
                                    capture_output=True,
                                    text=True,
                                )
                                libs_result = subprocess.run(
                                    ["pkg-config", "--libs", pkg_component],
                                    capture_output=True,
                                    text=True,
                                )
                                component_cflags = cflags_result.stdout.strip()
                                component_link_flags = libs_result.stdout.strip()
                                if component_link_flags:
                                    component_libs.append(component_link_flags)
                                ctx.imported_targets[f"Boost::{component}"] = (
                                    ImportedTarget(
                                        cflags=component_cflags,
                                        libs=component_link_flags,
                                    )
                                )
                                ctx.variables[var_name] = "TRUE"
                                ctx.variables[upper_var_name] = "TRUE"
                            else:
                                ctx.variables[var_name] = "FALSE"
                                ctx.variables[upper_var_name] = "FALSE"
                                if component in required_components:
                                    missing_required_components.append(component)

                        found = found and not missing_required_components
                        ctx.variables["Boost_FOUND"] = "TRUE" if found else "FALSE"
                        ctx.variables["BOOST_FOUND"] = "TRUE" if found else "FALSE"

                        if include_dirs:
                            unique_include_dirs = list(dict.fromkeys(include_dirs))
                            ctx.variables["Boost_INCLUDE_DIRS"] = ";".join(
                                unique_include_dirs
                            )
                            ctx.variables["BOOST_INCLUDE_DIRS"] = ";".join(
                                unique_include_dirs
                            )
                            ctx.variables["Boost_INCLUDE_DIR"] = unique_include_dirs[0]
                            ctx.variables["BOOST_INCLUDE_DIR"] = unique_include_dirs[0]

                        all_libs = " ".join(
                            value for value in [boost_libs, *component_libs] if value
                        )
                        if all_libs:
                            ctx.variables["Boost_LIBRARIES"] = all_libs
                            ctx.variables["BOOST_LIBRARIES"] = all_libs
                        if boost_version:
                            ctx.variables["Boost_VERSION"] = boost_version
                            ctx.variables["BOOST_VERSION"] = boost_version

                        if found:
                            ctx.imported_targets["Boost::headers"] = ImportedTarget(
                                cflags=boost_cflags
                            )
                            ctx.imported_targets["Boost::boost"] = ImportedTarget(
                                cflags=boost_cflags
                            )

                        if required and not found:
                            ctx.print_error("could not find package: Boost", cmd.line)
                            raise SystemExit(1)
                        if not quiet:
                            if found:
                                print(f"{colored('✓', 'green')} {package_name}")
                            else:
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

                            def on_exit_find_package(
                                saved_list_file: Path = saved_list_file,
                            ) -> None:
                                ctx.current_list_file = saved_list_file

                            stack.append(
                                Frame(
                                    commands=find_commands,
                                    on_exit=on_exit_find_package,
                                    kind="include",
                                )
                            )
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
                output_quiet = False
                error_quiet = False
                output_strip = False
                error_strip = False
                command_error_is_fatal: str | None = None

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
                    elif arg == "OUTPUT_QUIET":
                        output_quiet = True
                    elif arg == "ERROR_QUIET":
                        error_quiet = True
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
                        "ENCODING",
                    ):
                        # Skip unsupported options and their values
                        arg_idx += 1
                    elif arg == "COMMAND_ERROR_IS_FATAL":
                        arg_idx += 1
                        if arg_idx < len(args):
                            command_error_is_fatal = args[arg_idx]
                    else:
                        # Part of current command
                        current_command.append(
                            ctx.expand_variables(arg, strict, cmd.line)
                        )
                    arg_idx += 1

                if current_command:
                    commands_list.append(current_command)

                # Execute the commands (sequentially if multiple)
                if commands_list:
                    try:
                        last_result = None
                        for idx, exec_cmd in enumerate(commands_list):
                            stdout_setting = None
                            stderr_setting = None
                            if output_quiet:
                                stdout_setting = subprocess.DEVNULL
                            elif output_variable:
                                stdout_setting = subprocess.PIPE
                            if error_quiet:
                                stderr_setting = subprocess.DEVNULL
                            elif error_variable:
                                stderr_setting = subprocess.PIPE

                            result = subprocess.run(
                                exec_cmd,
                                stdout=stdout_setting,
                                stderr=stderr_setting,
                                text=True,
                                cwd=working_directory,
                            )
                            last_result = result

                            is_last = idx == len(commands_list) - 1
                            if command_error_is_fatal:
                                fatal_kind = command_error_is_fatal.upper()
                                fatal_now = False
                                if fatal_kind == "ANY" and result.returncode != 0:
                                    fatal_now = True
                                elif (
                                    fatal_kind == "LAST"
                                    and is_last
                                    and result.returncode != 0
                                ):
                                    fatal_now = True
                                if fatal_now:
                                    ctx.print_error(
                                        f"execute_process failed with exit code {result.returncode}",
                                        cmd.line,
                                    )
                                    raise SystemExit(1)

                        if last_result is not None:
                            if result_variable:
                                ctx.variables[result_variable] = str(
                                    last_result.returncode
                                )

                            if output_variable:
                                output = (
                                    "" if output_quiet else (last_result.stdout or "")
                                )
                                if output_strip:
                                    output = output.rstrip()
                                ctx.variables[output_variable] = output

                            if error_variable:
                                error = (
                                    "" if error_quiet else (last_result.stderr or "")
                                )
                                if error_strip:
                                    error = error.rstrip()
                                ctx.variables[error_variable] = error
                    except FileNotFoundError:
                        if result_variable:
                            ctx.variables[result_variable] = "1"
                        if command_error_is_fatal:
                            ctx.print_error(
                                "execute_process failed: command not found",
                                cmd.line,
                            )
                            raise SystemExit(1)

            case _:
                # Check if this is a user-defined function or macro call
                name = cmd.name.lower()
                if name in ctx.functions:
                    func_def = ctx.functions[name]
                    # Save current variables for function scope
                    saved_vars = ctx.variables.copy()
                    saved_current_source_dir = ctx.current_source_dir
                    saved_current_list_file = ctx.current_list_file
                    saved_parent_directory = ctx.parent_directory

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

                    saved_parent_scope_vars = ctx.parent_scope_vars
                    ctx.parent_scope_vars = {}

                    # In CMake, CMAKE_CURRENT_LIST_* inside a function reflects
                    # the caller's currently processed list file, not the file
                    # where the function was originally defined.
                    ctx.current_list_file = func_def.defining_file
                    ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(
                        saved_current_list_file
                    )
                    ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                        saved_current_list_file.parent
                    )

                    def on_exit_function(
                        saved_vars: dict[str, str] = saved_vars,
                        saved_current_source_dir: Path = saved_current_source_dir,
                        saved_current_list_file: Path = saved_current_list_file,
                        saved_parent_directory: str = saved_parent_directory,
                        saved_parent_scope_vars: dict[
                            str, str | None
                        ] = saved_parent_scope_vars,
                    ) -> None:
                        cache_updates = {
                            k: v
                            for k, v in ctx.variables.items()
                            if k in ctx.cache_variables
                        }
                        for var_name, var_value in ctx.parent_scope_vars.items():
                            if var_value is None:
                                saved_vars.pop(var_name, None)
                            else:
                                saved_vars[var_name] = var_value
                        ctx.parent_scope_vars = saved_parent_scope_vars
                        ctx.current_source_dir = saved_current_source_dir
                        ctx.current_list_file = saved_current_list_file
                        ctx.parent_directory = saved_parent_directory
                        ctx.variables = saved_vars
                        ctx.variables.update(cache_updates)
                        ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] = str(
                            saved_current_source_dir
                        )
                        ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(
                            saved_current_list_file
                        )
                        ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                            saved_current_list_file.parent
                        )
                        ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(ctx.build_dir)

                    frame.pc += 1
                    stack.append(
                        Frame(
                            commands=func_def.body,
                            on_exit=on_exit_function,
                            kind="function",
                        )
                    )
                    continue
                elif name in ctx.macros:
                    macro_def = ctx.macros[name]
                    # Macros don't create a new scope - they operate in the caller's scope
                    # Save the special variables so we can restore them after
                    saved_current_source_dir = ctx.current_source_dir
                    saved_current_list_file = ctx.current_list_file
                    saved_parent_directory = ctx.parent_directory
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

                    def on_exit(
                        saved_current_source_dir: Path = saved_current_source_dir,
                        saved_current_list_file: Path = saved_current_list_file,
                        saved_parent_directory: str = saved_parent_directory,
                        saved_argc: str = saved_argc,
                        saved_argv: str = saved_argv,
                        saved_argn: str = saved_argn,
                        saved_argv_vars: dict[str, str] = saved_argv_vars,
                        saved_params: dict[str, str] = saved_params,
                    ) -> None:
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

                        ctx.current_source_dir = saved_current_source_dir
                        ctx.current_list_file = saved_current_list_file
                        ctx.parent_directory = saved_parent_directory
                        ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] = str(
                            saved_current_source_dir
                        )
                        ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(
                            saved_current_list_file
                        )
                        ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                            saved_current_list_file.parent
                        )
                        ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(ctx.build_dir)

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
    windows_clangxx = _is_windows_clangxx(cxx)

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

    # Interprocedural optimization flags (LTO), including config-specific override.
    ipo_enabled = False
    ipo_config_var = f"CMAKE_INTERPROCEDURAL_OPTIMIZATION_{build_type}"
    if ipo_config_var in ctx.variables:
        ipo_enabled = is_truthy(ctx.variables[ipo_config_var])
    elif "CMAKE_INTERPROCEDURAL_OPTIMIZATION" in ctx.variables:
        ipo_enabled = is_truthy(ctx.variables["CMAKE_INTERPROCEDURAL_OPTIMIZATION"])
    ipo_flags = ""
    if ipo_enabled:
        c_id = ctx.variables.get("CMAKE_C_COMPILER_ID", "")
        cxx_id = ctx.variables.get("CMAKE_CXX_COMPILER_ID", "")
        # GCC supports parallel LTO partitioning with -flto=auto.
        if c_id == "GNU" or cxx_id == "GNU":
            ipo_flags = "-flto=auto"
        else:
            ipo_flags = "-flto"

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

        n.comment("Generated by cja")
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

            reconfigure_cmd_parts = ["cja", "--regenerate-during-build"]
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
                pool="console",
            )
            n.newline()

            output_name = make_relative(str(output_path), ctx.source_dir)
            n.build(output_name, "reconfigure", cmake_deps)
            n.newline()

        # Compile rules - include build type flags
        base_cflags = f"-fdiagnostics-color {build_type_flags} {ipo_flags}".strip()
        c_flags = ctx.variables.get("CMAKE_C_FLAGS", "")
        cxx_flags = ctx.variables.get("CMAKE_CXX_FLAGS", "")
        cxx_flags = _normalize_windows_clang_cxx_std(cxx_flags, windows_clangxx)
        linker_flags = f"{ctx.variables.get('CMAKE_LINKER_FLAGS', '')} {ipo_flags}".strip()
        n.variable("ldflags", linker_flags)

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
            command="$cc -fdiagnostics-color $in -o $out $ldflags $libs",
            description="\x1b[32;1mLinking C executable $out\x1b[0m",
        )
        n.newline()

        n.rule(
            "link_cxx",
            command="$cxx -fdiagnostics-color $in -o $out $ldflags $libs",
            description="\x1b[32;1mLinking C++ executable $out\x1b[0m",
        )
        n.newline()

        # Windows resource compilation (llvm-rc, clang-only, no mt.exe)
        if platform.system() == "Windows":
            default_rc = "llvm-rc"
            n.variable("rc", default_rc)
            n.rule(
                "rc",
                command="$rc /FO $out $in",
                description="\x1b[32mCompiling resources $in\x1b[0m",
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
                lib_compile_flags.append(_format_compile_definition_flag(definition))
            for definition in lib.compile_definitions:
                lib_compile_flags.append(_format_compile_definition_flag(definition))
            for option in lib.compile_options:
                opt = strip_generator_expressions(option)
                if opt:
                    lib_compile_flags.append(opt)
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
                        def_flag = _format_compile_definition_flag(definition)
                        if def_flag not in lib_compile_flags:
                            lib_compile_flags.append(def_flag)
                    for option in dep_lib.public_compile_options:
                        opt = strip_generator_expressions(option)
                        if opt and opt not in lib_compile_flags:
                            lib_compile_flags.append(opt)
                if dep_name in ctx.imported_targets:
                    imported = ctx.imported_targets[dep_name]
                    if imported.cflags:
                        lib_compile_flags.append(imported.cflags)

            # Filter out headers, .rc, and .manifest files from compileable sources
            compileable_sources: list[str] = [
                s
                for s in lib.sources
                if not is_header(s) and not is_rc(s) and not is_manifest(s)
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
                        source_compile_flags.append(
                            _format_compile_definition_flag(definition)
                        )
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
                    source_compile_flags = [
                        _normalize_windows_clang_cxx_std(flag, windows_clangxx)
                        for flag in source_compile_flags
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
                compile_flags.append(_format_compile_definition_flag(definition))
            for definition in exe.compile_definitions:
                compile_flags.append(_format_compile_definition_flag(definition))
            for option in exe.compile_options:
                opt = strip_generator_expressions(option)
                if opt:
                    compile_flags.append(opt)
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
                        def_flag = _format_compile_definition_flag(definition)
                        if def_flag not in compile_flags:
                            compile_flags.append(def_flag)
                    for option in linked_lib.public_compile_options:
                        opt = strip_generator_expressions(option)
                        if opt and opt not in compile_flags:
                            compile_flags.append(opt)
                # Check for cflags from imported targets
                if lib_name in ctx.imported_targets:
                    imported = ctx.imported_targets[lib_name]
                    if imported.cflags:
                        compile_flags.append(imported.cflags)

            # Filter out headers, .rc, and .manifest files from compileable sources
            compileable_sources: list[str] = [
                s
                for s in exe.sources
                if not is_header(s) and not is_rc(s) and not is_manifest(s)
            ]
            rc_sources: list[str] = [s for s in exe.sources if is_rc(s)]
            manifest_sources: list[str] = [s for s in exe.sources if is_manifest(s)]

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
                        source_compile_flags.append(
                            _format_compile_definition_flag(definition)
                        )
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
                    source_compile_flags = [
                        _normalize_windows_clang_cxx_std(flag, windows_clangxx)
                        for flag in source_compile_flags
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

            # On Windows, compile .rc files to .res and add to link inputs
            if rc_sources and platform.system() == "Windows":
                for rc_source in rc_sources:
                    actual_rc = rc_source
                    if rc_source in custom_command_outputs:
                        actual_rc = f"$builddir/{rc_source}"
                    rc_rel = Path(rc_source)
                    res_name = f"$builddir/{exe.name}_{rc_rel.stem}.res"
                    register_output(res_name, exe.defined_file, exe.defined_line)
                    rc_deps = _rc_manifest_deps(ctx, rc_source)
                    n.build(
                        res_name,
                        "rc",
                        actual_rc,
                        implicit=rc_deps if rc_deps else None,
                    )
                    link_inputs.append(res_name)

            # On Windows, .manifest as source: auto-generate .rc and use llvm-rc workflow
            if manifest_sources and platform.system() == "Windows":
                for manifest in manifest_sources:
                    manifest_rel = Path(manifest)
                    rc_stem = f"{exe.name}_{manifest_rel.stem}"
                    rc_name = f"{rc_stem}.rc"
                    res_name = f"$builddir/{rc_stem}.res"
                    rc_path = ctx.build_dir / rc_name
                    # Path from build dir to manifest (llvm-rc resolves relative to .rc)
                    rc_manifest_path = Path("..") / manifest
                    rc_content = (
                        "#ifndef RT_MANIFEST\n#define RT_MANIFEST 24\n#endif\n"
                        f'1 RT_MANIFEST "{rc_manifest_path.as_posix()}"\n'
                    )
                    rc_path.parent.mkdir(parents=True, exist_ok=True)
                    rc_path.write_text(rc_content, encoding="utf-8")
                    register_output(res_name, exe.defined_file, exe.defined_line)
                    n.build(
                        res_name,
                        "rc",
                        f"$builddir/{rc_name}",
                        implicit=manifest,
                    )
                    link_inputs.append(res_name)

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
                destination = install.destination
                try:
                    source_dir = ctx.source_dir.resolve()
                    destination_path = Path(destination).resolve()
                    if destination_path.is_relative_to(source_dir):
                        destination = str(destination_path.relative_to(source_dir))
                except OSError, RuntimeError, ValueError:
                    pass

                for target in install.targets:
                    src = None
                    if target in exe_outputs:
                        src = exe_outputs[target]
                    elif target in lib_outputs:
                        src = lib_outputs[target]

                    if src:
                        dest = (
                            f"{destination}/{Path(src).name.replace('$builddir/', '')}"
                        )
                        register_output(dest, None, 0)
                        n.build(
                            dest,
                            "install_file",
                            src,
                            variables={"out_dir": destination},
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
    regenerate_during_build: bool = False,
) -> BuildContext:
    """Configure a CMake project and generate build.ninja.

    Args:
        source_dir: Path to source directory containing CMakeLists.txt
        build_dir: Relative path for build directory (e.g., "build")
        variables: Optional dict of variables to set (e.g., from -D flags)
        trace: If True, print each command as it's processed
        strict: If True, error on unsupported commands instead of ignoring them
        regenerate_during_build: If True, we were triggered during build
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
    ctx.variables.setdefault("CMAKE_BUILD_TYPE", "Debug")
    ctx.variables["CMAKE_FIND_PACKAGE_REDIRECTS_DIR"] = str(
        ctx.build_dir / "CMakeFiles" / "pkgRedirects"
    )
    ctx.variables.setdefault("CMAKE_INSTALL_PREFIX", str(ctx.build_dir / "install"))
    ctx.variables["CMAKE_HOST_SYSTEM_PROCESSOR"] = _detect_host_system_processor()

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
    ctx.variables["CMAKE_C_COMPILER"] = ctx.c_compiler
    ctx.variables["CMAKE_CXX_COMPILER"] = ctx.cxx_compiler
    ctx.variables["CMAKE_C_COMPILER_ID"] = _infer_compiler_id(ctx.c_compiler)
    ctx.variables["CMAKE_CXX_COMPILER_ID"] = _infer_compiler_id(ctx.cxx_compiler)

    process_commands(commands, ctx, trace, strict)

    # Generate ninja manifest in source directory (named after build dir)
    output_path = source_dir / f"{build_dir}.ninja"
    manifest_existed = output_path.exists()
    generate_ninja(ctx, output_path, build_dir, strict=strict)

    # Generate compilation database
    try:
        compdb = subprocess.check_output(
            ["ninja", "-f", str(output_path), "-t", "compdb"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        (ctx.build_dir / "compile_commands.json").write_text(compdb)
    except subprocess.CalledProcessError, FileNotFoundError:
        # Ignore errors if ninja is not found or fails
        pass

    # Don't cause unnecessary rebuilds when we the users runs cja explicitly:
    if not regenerate_during_build and manifest_existed:
        restat_cmd = [
            "ninja",
            "-t",
            "restat",
            f"--builddir={build_dir}",
            f"{build_dir}.ninja",
        ]
        try:
            subprocess.check_output(restat_cmd, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            print(
                f"{colored('warning:', 'magenta', attrs=['bold'])} `{' '.join(restat_cmd)}` failed with exit code {e.returncode}:\n{e.output.decode().rstrip()}"
            )

    print(f"{colored('Configured', 'green', attrs=['bold'])} {build_dir}.ninja")
    return ctx
