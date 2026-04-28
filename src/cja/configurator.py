"""CMake command processor and build context population."""

from pathlib import Path
import hashlib
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile
import typing
import urllib.request
import zipfile

from termcolor import colored

from .config_utils import (
    build_foreach_info,
    select_if_block,
    _render_basic_package_version_file,
    _render_package_init_block,
)
from .frame import Frame
from .build_context import (
    BuildContext,
)
from .parser import Command
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
from .syntax import (
    FetchContentInfo,
    SourceFileProperties,
    Test,
)
from .utils import (
    make_relative,
    status_marker,
    to_posix_path,
)
from .build_context import (
    CustomCommand,
    CustomTarget,
)
from rich.progress import (
    Progress,
    DownloadColumn,
    TransferSpeedColumn,
    BarColumn,
    TextColumn,
    TimeRemainingColumn,
)
from .targets import ImportedTarget, InstallTarget
from .find_package import handle_builtin_find_package


class ReturnFromFunction(Exception):
    """Exception raised to exit early from a function."""

    pass


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

    def split_unquoted_list_args(value: str) -> list[str]:
        """Split list arguments on semicolons outside generator expressions."""
        if ";" not in value:
            return [value]
        result: list[str] = []
        current: list[str] = []
        genex_depth = 0
        i = 0
        while i < len(value):
            if value.startswith("$<", i):
                genex_depth += 1
                current.append("$<")
                i += 2
                continue
            ch = value[i]
            if ch == ">" and genex_depth > 0:
                genex_depth -= 1
                current.append(ch)
                i += 1
                continue
            if ch == ";" and genex_depth == 0:
                result.append("".join(current))
                current = []
                i += 1
                continue
            current.append(ch)
            i += 1
        result.append("".join(current))
        return result

    def _search_dirs_with_defaults(
        kind: str, hints: list[str], paths: list[str]
    ) -> list[str]:
        """Build search dirs in CMake-like order: hints, paths, then defaults."""
        dirs: list[str] = []
        seen: set[str] = set()

        def add_dir(candidate: str) -> None:
            if not candidate:
                return
            path = candidate.strip()
            if not path:
                return
            # Expand user-home paths to align with shell/env behavior.
            path = os.path.expanduser(path)
            if path in seen:
                return
            seen.add(path)
            dirs.append(path)

        for d in hints:
            add_dir(d)
        for d in paths:
            add_dir(d)

        cmake_prefix_path = ctx.variables.get("CMAKE_PREFIX_PATH", "")
        for prefix in (
            split_unquoted_list_args(cmake_prefix_path) if cmake_prefix_path else []
        ):
            if kind == "path":
                add_dir(str(Path(prefix) / "include"))
                add_dir(prefix)
            else:
                add_dir(str(Path(prefix) / "lib"))
                add_dir(str(Path(prefix) / "lib64"))
                add_dir(prefix)

        env_prefix_path = os.environ.get("CMAKE_PREFIX_PATH", "")
        for prefix in env_prefix_path.split(os.pathsep) if env_prefix_path else []:
            if kind == "path":
                add_dir(str(Path(prefix) / "include"))
                add_dir(prefix)
            else:
                add_dir(str(Path(prefix) / "lib"))
                add_dir(str(Path(prefix) / "lib64"))
                add_dir(prefix)

        if platform.system() == "Windows":
            windows_roots = ["C:/Program Files", "C:/Program Files (x86)"]
            for root in windows_roots:
                if kind == "path":
                    add_dir(str(Path(root) / "include"))
                else:
                    add_dir(str(Path(root) / "lib"))
                add_dir(root)
        else:
            unix_defaults = ["/usr/local", "/usr"]
            if platform.system() == "Darwin" and Path("/opt/homebrew").is_dir():
                unix_defaults.insert(0, "/opt/homebrew")
            for root in unix_defaults:
                if kind == "path":
                    add_dir(str(Path(root) / "include"))
                else:
                    add_dir(str(Path(root) / "lib"))
                    add_dir(str(Path(root) / "lib64"))
                    add_dir(str(Path(root) / "lib/x86_64-linux-gnu"))
                    add_dir(str(Path(root) / "lib/aarch64-linux-gnu"))
                add_dir(root)
            if kind == "lib":
                add_dir("/lib")
                add_dir("/lib64")

        return dirs

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
                    fetch_cmd_line = (
                        frame.fetchcontent_cmd.line if frame.fetchcontent_cmd else 0
                    )
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
                    fetch_cmd_line = (
                        frame.fetchcontent_cmd.line if frame.fetchcontent_cmd else 0
                    )
                    try:
                        subprocess.run(
                            ["git", "-C", str(src_dir), "checkout", git_tag], check=True
                        )
                    except (FileNotFoundError, subprocess.CalledProcessError):
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
                        sub_commands = parse_file(sub_cmakelists)

                        saved_current_source_dir = ctx.current_source_dir
                        saved_current_list_file = ctx.current_list_file
                        saved_parent_directory = ctx.parent_directory
                        saved_binary_dir = ctx.variables.get(
                            "CMAKE_CURRENT_BINARY_DIR", str(ctx.build_dir)
                        )
                        saved_vars = ctx.variables.copy()
                        saved_parent_scope_vars = ctx.parent_scope_vars
                        ctx.parent_scope_vars = {}

                        fc_binary_dir = (
                            ctx.build_dir / "_deps" / f"{name.lower()}-build"
                        )
                        fc_binary_dir.mkdir(parents=True, exist_ok=True)

                        ctx.current_source_dir = actual_src_dir
                        ctx.current_list_file = sub_cmakelists
                        ctx.parent_directory = str(saved_current_source_dir)
                        ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] = str(actual_src_dir)
                        ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(sub_cmakelists)
                        ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                            sub_cmakelists.parent
                        )
                        ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(fc_binary_dir)

                        def on_exit_fetchcontent(
                            saved_current_source_dir: Path = saved_current_source_dir,
                            saved_current_list_file: Path = saved_current_list_file,
                            saved_parent_directory: str = saved_parent_directory,
                            saved_binary_dir: str = saved_binary_dir,
                            saved_vars: dict[str, str] = saved_vars,
                            saved_parent_scope_vars: dict[
                                str, str | None
                            ] = saved_parent_scope_vars,
                        ) -> None:
                            cache_updates = {
                                k: v
                                for k, v in ctx.variables.items()
                                if k in ctx.cache_variables
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
                            ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = saved_binary_dir

                        stack.append(
                            Frame(commands=sub_commands, on_exit=on_exit_fetchcontent)
                        )
            continue

        current_commands = typing.cast(list[Command], frame.commands)
        if frame.pc >= len(current_commands):
            if frame.on_exit:
                frame.on_exit()
            stack.pop()
            continue

        cmd = current_commands[frame.pc]
        ctx.variables["CMAKE_CURRENT_LIST_LINE"] = str(cmd.line)
        expanded_args: list[str] = []
        for idx, arg in enumerate(cmd.args):
            allow_undefined = False
            allow_undefined_warning = "${${" in arg
            is_exact_var = (
                (arg.startswith("${") and arg.endswith("}"))
                or (arg.startswith('"${') and arg.endswith('}"'))
                or (arg.startswith("'${") and arg.endswith("}'"))
            )
            if cmd.name in ("if", "elseif"):
                allow_undefined = (
                    idx + 2 < len(cmd.args)
                    and cmd.args[idx + 1] == "STREQUAL"
                    and cmd.args[idx + 2] in ("", '""', "''")
                    and is_exact_var
                )
                # In CMake conditions, unresolved ${VAR} tokens are treated
                # as empty and should not raise undefined-variable warnings.
                allow_undefined = allow_undefined or is_exact_var
            elif cmd.name == "option":
                # Common CMake pattern:
                #   option(FOO "help" ${SOME_DEFAULT})
                # where SOME_DEFAULT can be undefined and should evaluate empty.
                allow_undefined = idx == 2 and is_exact_var
            expanded = ctx.expand_variables(
                arg,
                strict,
                cmd.line,
                allow_undefined_empty=allow_undefined,
                allow_undefined_warning=allow_undefined_warning,
            )
            quoted = cmd.is_quoted[idx] if idx < len(cmd.is_quoted) else False
            if ";" in expanded and not quoted:
                expanded_args.extend(split_unquoted_list_args(expanded))
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
                    ctx.variables["CMAKE_C_FLAGS_DEBUG"] = ""
                    ctx.variables["CMAKE_C_FLAGS_RELEASE"] = ""
                    ctx.variables["CMAKE_C_FLAGS_RELWITHDEBINFO"] = ""
                    ctx.variables["CMAKE_C_FLAGS_MINSIZEREL"] = ""
                    ctx.variables["CMAKE_CXX_FLAGS"] = (
                        ""  # TODO: Only set when CXX is enabled
                    )
                    ctx.variables["CMAKE_CXX_FLAGS_DEBUG"] = ""
                    ctx.variables["CMAKE_CXX_FLAGS_RELEASE"] = ""
                    ctx.variables["CMAKE_CXX_FLAGS_RELWITHDEBINFO"] = ""
                    ctx.variables["CMAKE_CXX_FLAGS_MINSIZEREL"] = ""
                    ctx.variables["CMAKE_EXE_LINKER_FLAGS"] = ""
                    ctx.variables["CMAKE_LINKER_FLAGS"] = ""
                    current_binary_dir = ctx.variables.get(
                        "CMAKE_CURRENT_BINARY_DIR", str(ctx.build_dir)
                    )
                    ctx.variables["PROJECT_SOURCE_DIR"] = str(ctx.current_source_dir)
                    ctx.variables["PROJECT_BINARY_DIR"] = current_binary_dir
                    source_var = f"{project_name}_SOURCE_DIR"
                    binary_var = f"{project_name}_BINARY_DIR"
                    ctx.variables[source_var] = str(ctx.current_source_dir)
                    ctx.variables[binary_var] = current_binary_dir
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

                    # Like CMake, include these files as the final step of project().
                    project_include = ctx.variables.get("CMAKE_PROJECT_INCLUDE", "")
                    if project_include:
                        for include_item in split_unquoted_list_args(project_include):
                            include_target = include_item.strip()
                            if not include_target:
                                continue
                            process_commands(
                                [
                                    Command(
                                        name="include",
                                        args=[include_target],
                                        line=cmd.line,
                                    )
                                ],
                                ctx,
                                trace=trace,
                                strict=strict,
                            )

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

                        ctx.record_cmake_file(sub_cmakelists)
                        sub_commands = parse_file(sub_cmakelists)

                        saved_current_source_dir = ctx.current_source_dir
                        saved_current_list_file = ctx.current_list_file
                        saved_parent_directory = ctx.parent_directory
                        saved_binary_dir = ctx.variables.get(
                            "CMAKE_CURRENT_BINARY_DIR", str(ctx.build_dir)
                        )
                        saved_vars = ctx.variables.copy()
                        saved_parent_scope_vars = ctx.parent_scope_vars
                        ctx.parent_scope_vars = {}

                        sub_binary_dir = Path(saved_binary_dir) / sub_dir_name
                        sub_binary_dir.mkdir(parents=True, exist_ok=True)

                        ctx.current_source_dir = sub_source_dir
                        ctx.current_list_file = sub_cmakelists
                        ctx.parent_directory = str(saved_current_source_dir)
                        ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] = str(sub_source_dir)
                        ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(sub_cmakelists)
                        ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                            sub_cmakelists.parent
                        )
                        ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(sub_binary_dir)

                        def on_exit_add_subdirectory(
                            saved_current_source_dir: Path = saved_current_source_dir,
                            saved_current_list_file: Path = saved_current_list_file,
                            saved_parent_directory: str = saved_parent_directory,
                            saved_binary_dir: str = saved_binary_dir,
                            saved_vars: dict[str, str] = saved_vars,
                            saved_parent_scope_vars: dict[
                                str, str | None
                            ] = saved_parent_scope_vars,
                        ) -> None:
                            cache_updates = {
                                k: v
                                for k, v in ctx.variables.items()
                                if k in ctx.cache_variables
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
                            ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = saved_binary_dir

                        stack.append(
                            Frame(
                                commands=sub_commands, on_exit=on_exit_add_subdirectory
                            )
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
                        "ExternalProject",
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
                        ctx.variables.setdefault("CMAKE_INSTALL_BINDIR", "bin")
                        ctx.variables.setdefault("CMAKE_INSTALL_SBINDIR", "sbin")
                        ctx.variables.setdefault("CMAKE_INSTALL_LIBEXECDIR", "libexec")
                        ctx.variables.setdefault("CMAKE_INSTALL_SYSCONFDIR", "etc")
                        ctx.variables.setdefault("CMAKE_INSTALL_SHAREDSTATEDIR", "com")
                        ctx.variables.setdefault("CMAKE_INSTALL_LOCALSTATEDIR", "var")
                        ctx.variables.setdefault("CMAKE_INSTALL_LIBDIR", "lib")
                        ctx.variables.setdefault("CMAKE_INSTALL_INCLUDEDIR", "include")
                        ctx.variables.setdefault(
                            "CMAKE_INSTALL_OLDINCLUDEDIR", "/usr/include"
                        )
                        ctx.variables.setdefault("CMAKE_INSTALL_DATAROOTDIR", "share")
                        ctx.variables.setdefault("CMAKE_INSTALL_DATADIR", "share")
                        ctx.variables.setdefault("CMAKE_INSTALL_INFODIR", "share/info")
                        ctx.variables.setdefault(
                            "CMAKE_INSTALL_LOCALEDIR", "share/locale"
                        )
                        ctx.variables.setdefault("CMAKE_INSTALL_MANDIR", "share/man")
                        project_name = ctx.variables.get("PROJECT_NAME", "")
                        ctx.variables.setdefault(
                            "CMAKE_INSTALL_DOCDIR", f"share/doc/{project_name}"
                        )

                        install_prefix = to_posix_path(
                            ctx.variables.get("CMAKE_INSTALL_PREFIX", "")
                        )
                        if install_prefix:
                            ctx.variables["CMAKE_INSTALL_PREFIX"] = install_prefix

                        include_dir = ctx.variables.get("CMAKE_INSTALL_INCLUDEDIR", "")
                        if include_dir:
                            if Path(include_dir).is_absolute():
                                full_include_dir = include_dir
                            else:
                                full_include_dir = str(
                                    Path(install_prefix) / include_dir
                                )
                            ctx.variables["CMAKE_INSTALL_FULL_INCLUDEDIR"] = (
                                to_posix_path(full_include_dir)
                            )

                        lib_dir = ctx.variables.get("CMAKE_INSTALL_LIBDIR", "")
                        if lib_dir:
                            if Path(lib_dir).is_absolute():
                                full_lib_dir = lib_dir
                            else:
                                full_lib_dir = str(Path(install_prefix) / lib_dir)
                            ctx.variables["CMAKE_INSTALL_FULL_LIBDIR"] = to_posix_path(
                                full_lib_dir
                            )
                    elif (
                        module_name.endswith(".cmake")
                        or "/" in module_name
                        or "." in module_name
                    ):
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
                # Directory-scoped compile options (inherit to subdirs, not parents).
                for arg in args:
                    expanded = ctx.expand_variables(arg, strict, cmd.line)
                    ctx.compile_options.append(expanded)
                    try:
                        abs_dir = str(ctx.current_source_dir.resolve())
                    except FileNotFoundError:
                        abs_dir = str(ctx.current_source_dir.absolute())
                    if abs_dir not in ctx.directory_properties:
                        ctx.directory_properties[abs_dir] = {}
                    existing = ctx.directory_properties[abs_dir].get("COMPILE_OPTIONS")
                    if existing:
                        ctx.directory_properties[abs_dir]["COMPILE_OPTIONS"] = (
                            existing + ";" + expanded
                        )
                    else:
                        ctx.directory_properties[abs_dir]["COMPILE_OPTIONS"] = expanded

            case "add_compile_definitions":
                # Directory-scoped compile definitions (inherit to subdirs, not parents).
                for arg in args:
                    expanded = ctx.expand_variables(arg, strict, cmd.line)
                    ctx.compile_definitions.append(expanded)
                    try:
                        abs_dir = str(ctx.current_source_dir.resolve())
                    except FileNotFoundError:
                        abs_dir = str(ctx.current_source_dir.absolute())
                    if abs_dir not in ctx.directory_properties:
                        ctx.directory_properties[abs_dir] = {}
                    existing = ctx.directory_properties[abs_dir].get(
                        "COMPILE_DEFINITIONS"
                    )
                    if existing:
                        ctx.directory_properties[abs_dir]["COMPILE_DEFINITIONS"] = (
                            existing + ";" + expanded
                        )
                    else:
                        ctx.directory_properties[abs_dir]["COMPILE_DEFINITIONS"] = (
                            expanded
                        )

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

            case "add_custom_target":
                # Support: add_custom_target(<name> [ALL] [COMMAND cmd ...] [DEPENDS ...] [WORKING_DIRECTORY ...] [VERBATIM] [COMMENT ...])
                if not args:
                    break
                target_name = ctx.expand_variables(args[0], strict, cmd.line)
                ct_commands: list[list[str]] = []
                ct_depends: list[str] = []
                ct_all = False
                ct_working_directory: str | None = None
                ct_verbatim = False
                ct_comment = ""
                ct_section: str | None = None
                ct_idx = 1
                while ct_idx < len(args):
                    arg = args[ct_idx]
                    if arg == "ALL":
                        ct_all = True
                    elif arg in ("COMMAND", "DEPENDS", "WORKING_DIRECTORY", "COMMENT"):
                        ct_section = arg
                        if arg == "COMMAND":
                            ct_commands.append([])
                    elif arg in ("VERBATIM", "USES_TERMINAL", "COMMAND_EXPAND_LISTS"):
                        if arg == "VERBATIM":
                            ct_verbatim = True
                        ct_section = None
                    elif arg == "SOURCES":
                        ct_section = "SOURCES"
                    else:
                        arg = ctx.expand_variables(arg, strict, cmd.line)
                        if ct_section == "COMMAND":
                            ct_commands[-1].append(arg)
                        elif ct_section == "DEPENDS":
                            rel = make_relative(arg, ctx.build_dir)
                            if rel == arg:
                                rel = ctx.resolve_path(arg)
                            ct_depends.append(rel)
                        elif ct_section == "WORKING_DIRECTORY":
                            ct_working_directory = arg
                        elif ct_section == "COMMENT":
                            ct_comment = arg
                        elif ct_section == "SOURCES":
                            pass  # Ignored, only for IDE integration
                    ct_idx += 1

                ctx.custom_targets.append(
                    CustomTarget(
                        name=target_name,
                        commands=ct_commands,
                        depends=ct_depends,
                        all=ct_all,
                        working_directory=ct_working_directory,
                        verbatim=ct_verbatim,
                        comment=ct_comment,
                        defined_file=ctx.current_list_file,
                        defined_line=cmd.line,
                    )
                )

            case "add_dependencies":
                # add_dependencies(<target> [<target-dep>]...)
                if len(args) >= 2:
                    dep_target_name = ctx.expand_variables(
                        args[0], strict, cmd.line
                    )
                    dep_names = [
                        ctx.expand_variables(a, strict, cmd.line) for a in args[1:]
                    ]
                    target_exe = ctx.get_executable(dep_target_name)
                    target_lib = ctx.get_library(dep_target_name)
                    target_ct = next(
                        (ct for ct in ctx.custom_targets if ct.name == dep_target_name),
                        None,
                    )
                    if target_exe is not None:
                        for dep in dep_names:
                            if dep not in target_exe.dependencies:
                                target_exe.dependencies.append(dep)
                    elif target_lib is not None:
                        for dep in dep_names:
                            if dep not in target_lib.dependencies:
                                target_lib.dependencies.append(dep)
                    elif target_ct is not None:
                        for dep in dep_names:
                            if dep not in target_ct.dependencies:
                                target_ct.dependencies.append(dep)
                    elif strict:
                        ctx.print_error(
                            f"add_dependencies called on unknown target \"{dep_target_name}\"",
                            cmd.line,
                        )
                        sys.exit(1)
                    else:
                        ctx.print_warning(
                            f"add_dependencies called on unknown target \"{dep_target_name}\"",
                            cmd.line,
                        )

            case "add_test":
                # Support: add_test(NAME <name> COMMAND <command> ...
                #                   [WORKING_DIRECTORY <dir>])
                # Or: add_test(<name> <command> ...)
                if len(args) >= 2:
                    test_name = ""
                    test_command = []
                    test_working_directory: str | None = None
                    if args[0] == "NAME":
                        # NAME ... COMMAND ... [WORKING_DIRECTORY ...]
                        test_name = ctx.expand_variables(args[1], strict, cmd.line)
                        if "COMMAND" in args:
                            cmd_idx = args.index("COMMAND")
                            # Collect command args until next keyword
                            cmd_args = []
                            for a in args[cmd_idx + 1 :]:
                                if a == "WORKING_DIRECTORY":
                                    break
                                cmd_args.append(a)
                            test_command = [
                                ctx.expand_variables(a, strict, cmd.line)
                                for a in cmd_args
                            ]
                        if "WORKING_DIRECTORY" in args:
                            wd_idx = args.index("WORKING_DIRECTORY")
                            if wd_idx + 1 < len(args):
                                test_working_directory = ctx.expand_variables(
                                    args[wd_idx + 1], strict, cmd.line
                                )
                    else:
                        # <name> <command> ...
                        test_name = ctx.expand_variables(args[0], strict, cmd.line)
                        test_command = [
                            ctx.expand_variables(a, strict, cmd.line) for a in args[1:]
                        ]

                    if test_name and test_command:
                        ctx.tests.append(
                            Test(
                                name=test_name,
                                command=test_command,
                                working_directory=test_working_directory,
                            )
                        )

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
                    ctx.cache_variables.add(var_name)
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
                    existing = ctx.variables.get(var_name, "")
                    if var_name in ctx.cache_variables or (
                        existing and not existing.endswith("-NOTFOUND")
                    ):
                        frame.pc += 1
                        continue
                    ctx.cache_variables.add(var_name)
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
                                if args[i] == "ENV" and i + 1 < len(args):
                                    env_value = os.environ.get(args[i + 1], "")
                                    if env_value:
                                        paths.extend(
                                            p for p in env_value.split(os.pathsep) if p
                                        )
                                    i += 2
                                else:
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
                                if args[i] == "ENV" and i + 1 < len(args):
                                    env_value = os.environ.get(args[i + 1], "")
                                    if env_value:
                                        hints.extend(
                                            p for p in env_value.split(os.pathsep) if p
                                        )
                                    i += 2
                                else:
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

                    search_dirs = _search_dirs_with_defaults("path", hints, paths)

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
                    existing = ctx.variables.get(var_name, "")
                    if var_name in ctx.cache_variables or (
                        existing and not existing.endswith("-NOTFOUND")
                    ):
                        frame.pc += 1
                        continue
                    ctx.cache_variables.add(var_name)
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
                                if args[j] == "ENV" and j + 1 < len(args):
                                    env_value = os.environ.get(args[j + 1], "")
                                    if env_value:
                                        paths.extend(
                                            p for p in env_value.split(os.pathsep) if p
                                        )
                                    j += 2
                                else:
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
                                if args[j] == "ENV" and j + 1 < len(args):
                                    env_value = os.environ.get(args[j + 1], "")
                                    if env_value:
                                        hints.extend(
                                            p for p in env_value.split(os.pathsep) if p
                                        )
                                    j += 2
                                else:
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

                    search_dirs = _search_dirs_with_defaults("lib", hints, paths)

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
                # Minimal implementation modeled after CMake's
                # FindPackageHandleStandardArgs. Supports the signatures used in
                # our tests and in common Find<Package>.cmake modules.
                if not args:
                    frame.pc += 1
                    continue

                pkg_name = args[0]
                extended_keywords = {
                    "REQUIRED_VARS",
                    "FOUND_VAR",
                    "HANDLE_COMPONENTS",
                    "CONFIG_MODE",
                    "FAIL_MESSAGE",
                    "REQUIRED_VERSIONS",
                    "NAME_MISMATCHED",
                    "REASON_FAILURE_MESSAGE",
                    "VERSION_VAR",
                }
                # Basic signature:
                #   find_package_handle_standard_args(Pkg DEFAULT_MSG VAR1 VAR2 ...)
                # Detected when arg[1] is not an extended-signature keyword.
                is_basic = len(args) >= 3 and args[1] not in extended_keywords
                if is_basic:
                    required_vars = args[2:]
                    found = True
                    for var in required_vars:
                        value = ctx.variables.get(var, "")
                        if not value or value.endswith("-NOTFOUND"):
                            found = False
                            break
                    ctx.variables[f"{pkg_name}_FOUND"] = "TRUE" if found else "FALSE"

                # Extended signature:
                #   find_package_handle_standard_args(Pkg
                #       REQUIRED_VARS VAR1 VAR2 ...
                #       FOUND_VAR <var-name>
                #       [...])
                required_vars_ext: list[str] = []
                found_var_name = ""
                idx_fph = 1
                while idx_fph < len(args):
                    token = args[idx_fph]
                    if token == "REQUIRED_VARS":
                        idx_fph += 1
                        while (
                            idx_fph < len(args)
                            and args[idx_fph] not in extended_keywords
                        ):
                            required_vars_ext.append(args[idx_fph])
                            idx_fph += 1
                        continue
                    if token == "FOUND_VAR" and idx_fph + 1 < len(args):
                        found_var_name = args[idx_fph + 1]
                        idx_fph += 2
                        continue
                    idx_fph += 1

                if required_vars_ext:
                    found_ext = True
                    for var in required_vars_ext:
                        value = ctx.variables.get(var, "")
                        if not value or value.endswith("-NOTFOUND"):
                            found_ext = False
                            break
                    if found_var_name:
                        ctx.variables[found_var_name] = "TRUE" if found_ext else "FALSE"
                    # If no basic signature was used, also populate <Pkg>_FOUND.
                    if f"{pkg_name}_FOUND" not in ctx.variables:
                        ctx.variables[f"{pkg_name}_FOUND"] = (
                            "TRUE" if found_ext else "FALSE"
                        )

                # If the package was required and not found, fail the configure step.
                pkg_required_var = f"{pkg_name}_FIND_REQUIRED"
                if (
                    ctx.variables.get(pkg_required_var) == "TRUE"
                    and ctx.variables.get(f"{pkg_name}_FOUND") != "TRUE"
                ):
                    ctx.print_error(
                        f"could not find package: {pkg_name}",
                        cmd.line,
                    )
                    raise SystemExit(1)

            case "install":
                if len(args) >= 2 and args[0] == "TARGETS":
                    targets = []
                    destination = str(Path.home() / ".local" / "bin")

                    # install(TARGETS ...) syntax has a target-name list first,
                    # followed by option groups (LIBRARY/ARCHIVE/RUNTIME/FILE_SET/etc).
                    # Only names before the first option keyword are real targets.
                    install_target_keywords = {
                        "ARCHIVE",
                        "LIBRARY",
                        "RUNTIME",
                        "OBJECTS",
                        "FRAMEWORK",
                        "BUNDLE",
                        "PUBLIC_HEADER",
                        "PRIVATE_HEADER",
                        "RESOURCE",
                        "FILE_SET",
                        "INCLUDES",
                        "DESTINATION",
                        "PERMISSIONS",
                        "CONFIGURATIONS",
                        "COMPONENT",
                        "NAMELINK_COMPONENT",
                        "OPTIONAL",
                        "EXCLUDE_FROM_ALL",
                        "NAMELINK_ONLY",
                        "NAMELINK_SKIP",
                        "EXPORT",
                    }

                    i = 1
                    while i < len(args):
                        token = args[i]
                        if token in install_target_keywords:
                            break
                        targets.append(token)
                        i += 1

                    # Keep current simplified behavior: use the last DESTINATION seen.
                    i = 1
                    while i < len(args):
                        if args[i] == "DESTINATION" and i + 1 < len(args):
                            destination = ctx.expand_variables(
                                args[i + 1], strict, cmd.line
                            )
                            i += 2
                        else:
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
                    upper_args = {arg.upper() for arg in args[1:]}
                    required = "REQUIRED" in upper_args
                    no_module = "NO_MODULE" in upper_args
                    quiet = "QUIET" in upper_args or ctx.quiet
                    find_required_var = f"{package_name}_FIND_REQUIRED"
                    prev_required = ctx.variables.get(find_required_var) == "TRUE"
                    ctx.variables[find_required_var] = (
                        "TRUE" if (required or prev_required) else "FALSE"
                    )
                    if not handle_builtin_find_package(
                        ctx=ctx,
                        cmd=cmd,
                        args=args,
                        package_name=package_name,
                        required=required,
                        quiet=quiet,
                    ):
                        # NO_MODULE requests config-mode lookup only; do not load
                        # Find<Package>.cmake from CMAKE_MODULE_PATH to avoid recursion.
                        if no_module:
                            ctx.variables[f"{package_name}_FOUND"] = "FALSE"
                            if required:
                                ctx.print_error(
                                    f"could not find package: {package_name}", cmd.line
                                )
                                raise SystemExit(1)
                            frame.pc += 1
                            continue

                        # Search for Find<PackageName>.cmake in CMAKE_MODULE_PATH
                        module_path = ctx.variables.get("CMAKE_MODULE_PATH", "")
                        search_dirs = module_path.split(";") if module_path else []

                        # Also search built-in CJA modules (e.g. bundled FindGTest.cmake)
                        builtin_modules_dir = (
                            Path(__file__).parent / "cmake" / "Modules"
                        )
                        if builtin_modules_dir.exists():
                            search_dirs.append(str(builtin_modules_dir))

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

                        # Avoid infinite recursion when a Find module calls
                        # find_package(<Pkg> NO_MODULE) and we would otherwise
                        # include the same Find<Pkg>.cmake again.
                        if found_file:
                            try:
                                same_file = (
                                    found_file.resolve()
                                    == ctx.current_list_file.resolve()
                                )
                            except FileNotFoundError:
                                same_file = found_file == ctx.current_list_file
                            if same_file:
                                found_file = None

                        if found_file:
                            from .parser import parse_file

                            ctx.record_cmake_file(found_file)
                            find_commands = parse_file(found_file)

                            saved_list_file = ctx.current_list_file
                            saved_list_dir = str(saved_list_file.parent)
                            ctx.current_list_file = found_file
                            ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(found_file)
                            ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(
                                found_file.parent
                            )

                            def on_exit_find_package(
                                saved_list_file: Path = saved_list_file,
                                saved_list_dir: str = saved_list_dir,
                            ) -> None:
                                ctx.current_list_file = saved_list_file
                                ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(
                                    saved_list_file
                                )
                                ctx.variables["CMAKE_CURRENT_LIST_DIR"] = saved_list_dir

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
                                print(
                                    f"{colored(status_marker(False), 'red')} {package_name}"
                                )

            case "pkg_check_modules":
                if args:
                    prefix = args[0]
                    pkg_args = args[1:]

                    is_required = "REQUIRED" in pkg_args
                    is_quiet = "QUIET" in pkg_args or ctx.quiet
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
                            # Split version constraint: "foo>=1.0" -> ("foo", ">= 1.0")
                            import re as _re

                            ver_match = _re.match(
                                r"^([A-Za-z0-9_.+-]+)\s*(>=|<=|=)\s*(.+)$", module
                            )
                            if ver_match:
                                mod_name = ver_match.group(1)
                                exists_arg = f"{mod_name} {ver_match.group(2)} {ver_match.group(3)}"
                            else:
                                mod_name = module
                                exists_arg = module
                            try:
                                result = subprocess.run(
                                    ["pkg-config", "--exists", exists_arg],
                                    capture_output=True,
                                )
                                if result.returncode != 0:
                                    found_all = False
                                    break

                                cflags_res = subprocess.run(
                                    ["pkg-config", "--cflags", mod_name],
                                    capture_output=True,
                                    text=True,
                                )
                                cflags_out = cflags_res.stdout.strip()
                                all_cflags.append(cflags_out)
                                for entry in shlex.split(cflags_out):
                                    if entry.startswith("-I"):
                                        all_include_dirs.append(entry[2:])

                                libs_res = subprocess.run(
                                    ["pkg-config", "--libs", mod_name],
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
                                            mod_name,
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
                                print(
                                    f"{colored(status_marker(True), 'green')} {', '.join(modules)}"
                                )
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
                                print(
                                    f"{colored(status_marker(False), 'red')} {', '.join(modules)}"
                                )
                            ctx.variables[f"{prefix}_FOUND"] = "0"
                            if is_required:
                                ctx.print_error(
                                    f"could not find modules: {', '.join(modules)}",
                                    cmd.line,
                                )
                                raise SystemExit(1)

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
                    last_returncode: int | None = None
                    last_stdout: str = ""
                    last_stderr: str = ""
                    for idx, exec_cmd in enumerate(commands_list):
                        # Match CMake: unquoted variable references that
                        # expand to empty produce no argument. Drop empty
                        # entries so we don't pass an empty string to
                        # subprocess (which raises WinError 87 on Windows
                        # when used as the executable).
                        exec_cmd = [a for a in exec_cmd if a != ""]

                        is_last = idx == len(commands_list) - 1

                        # An empty command (e.g. only undefined variables
                        # were referenced) is treated like "command not
                        # found" rather than crashing.
                        if not exec_cmd:
                            last_returncode = 1
                            last_stdout = ""
                            last_stderr = ""
                            if command_error_is_fatal:
                                fatal_kind = command_error_is_fatal.upper()
                                if fatal_kind == "ANY" or (
                                    fatal_kind == "LAST" and is_last
                                ):
                                    ctx.print_error(
                                        "execute_process failed: empty command",
                                        cmd.line,
                                    )
                                    raise SystemExit(1)
                            continue

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

                        try:
                            result = subprocess.run(
                                exec_cmd,
                                stdout=stdout_setting,
                                stderr=stderr_setting,
                                text=True,
                                cwd=working_directory,
                            )
                        except (FileNotFoundError, OSError):
                            # FileNotFoundError covers the usual missing-
                            # executable case on POSIX. On Windows, an
                            # invalid executable path can also surface as
                            # a generic OSError (e.g. WinError 87).
                            last_returncode = 1
                            last_stdout = ""
                            last_stderr = ""
                            if command_error_is_fatal:
                                fatal_kind = command_error_is_fatal.upper()
                                if fatal_kind == "ANY" or (
                                    fatal_kind == "LAST" and is_last
                                ):
                                    ctx.print_error(
                                        "execute_process failed: command not found",
                                        cmd.line,
                                    )
                                    raise SystemExit(1)
                            continue

                        last_returncode = result.returncode
                        last_stdout = result.stdout or ""
                        last_stderr = result.stderr or ""

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

                    if last_returncode is not None:
                        if result_variable:
                            ctx.variables[result_variable] = str(last_returncode)

                        if output_variable:
                            output = "" if output_quiet else last_stdout
                            if output_strip:
                                output = output.rstrip()
                            ctx.variables[output_variable] = output

                        if error_variable:
                            error = "" if error_quiet else last_stderr
                            if error_strip:
                                error = error.rstrip()
                            ctx.variables[error_variable] = error

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
                    saved_binary_dir = ctx.variables.get(
                        "CMAKE_CURRENT_BINARY_DIR", str(ctx.build_dir)
                    )

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
                        saved_binary_dir: str = saved_binary_dir,
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
                        ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = saved_binary_dir

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
                    saved_binary_dir = ctx.variables.get(
                        "CMAKE_CURRENT_BINARY_DIR", str(ctx.build_dir)
                    )
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
                        saved_binary_dir: str = saved_binary_dir,
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
                        ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = saved_binary_dir

                    frame.pc += 1
                    stack.append(Frame(commands=macro_def.body, on_exit=on_exit))
                    continue
                elif strict:
                    ctx.print_error(f"unsupported command: {cmd.name}()", cmd.line)
                    sys.exit(1)
                # Ignore unknown commands by default

        frame.pc += 1
