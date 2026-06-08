"""Handlers for the simple CMake find_* commands.

Covers ``find_program``, ``find_path``, ``find_file`` and ``find_library``.
The richer ``find_package`` command lives in :mod:`cja.find_package`.
"""

import os
import platform
import shutil
from pathlib import Path

from .build_context import BuildContext
from .parser import Command
from .utils import split_unquoted_list_args


def _search_dirs_with_defaults(
    ctx: BuildContext, kind: str, hints: list[str], paths: list[str]
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


def _parse_find_args(
    args: list[str],
) -> tuple[list[str], list[str], list[str], list[str], bool]:
    """Parse the common keyword arguments shared by find_path/find_file/find_library.

    Returns ``(names, paths, hints, suffixes, required)``.
    """
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
                        paths.extend(p for p in env_value.split(os.pathsep) if p)
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
                        hints.extend(p for p in env_value.split(os.pathsep) if p)
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

    return names, paths, hints, suffixes, required


def _is_already_resolved(ctx: BuildContext, var_name: str) -> bool:
    """Return True if a cache var has already been resolved to a non-NOTFOUND value."""
    existing = ctx.variables.get(var_name, "")
    return var_name in ctx.cache_variables or (
        bool(existing) and not existing.endswith("-NOTFOUND")
    )


def handle_find_program(ctx: BuildContext, cmd: Command, args: list[str]) -> None:
    """Handle find_program() command."""
    if len(args) < 2:
        return

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
            raise FileNotFoundError(f"Could not find program: {' or '.join(names)}")


def handle_find_path(ctx: BuildContext, cmd: Command, args: list[str]) -> None:
    """Handle find_path() command."""
    if len(args) < 2:
        return

    var_name = args[0]
    if _is_already_resolved(ctx, var_name):
        return
    ctx.cache_variables.add(var_name)

    names, paths, hints, suffixes, required = _parse_find_args(args)

    search_dirs = _search_dirs_with_defaults(ctx, "path", hints, paths)

    found_dir = None
    for name in names:
        for d in search_dirs:
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
            raise FileNotFoundError(f"Could not find path for: {', '.join(names)}")


def handle_find_file(ctx: BuildContext, cmd: Command, args: list[str]) -> None:
    """Handle find_file() command.

    Like find_path but stores the full path to the file (including its name).
    """
    if len(args) < 2:
        return

    var_name = args[0]
    if _is_already_resolved(ctx, var_name):
        return
    ctx.cache_variables.add(var_name)

    names, paths, hints, suffixes, required = _parse_find_args(args)

    search_dirs = _search_dirs_with_defaults(ctx, "path", hints, paths)

    found_file = None
    for name in names:
        for d in search_dirs:
            for suffix in [""] + suffixes:
                candidate = Path(d) / suffix / name
                if candidate.exists():
                    found_file = str(candidate.absolute())
                    break
            if found_file:
                break
        if found_file:
            break

    if found_file:
        ctx.variables[var_name] = found_file
    else:
        ctx.variables[var_name] = f"{var_name}-NOTFOUND"
        if required:
            raise FileNotFoundError(f"Could not find file for: {', '.join(names)}")


def handle_find_library(ctx: BuildContext, cmd: Command, args: list[str]) -> None:
    """Handle find_library() command."""
    if len(args) < 2:
        return

    var_name = args[0]
    if _is_already_resolved(ctx, var_name):
        return
    ctx.cache_variables.add(var_name)

    names, paths, hints, suffixes, required = _parse_find_args(args)

    search_dirs = _search_dirs_with_defaults(ctx, "lib", hints, paths)

    if platform.system() == "Darwin":
        default_framework_dirs = [
            "/System/Library/Frameworks",
            "/Library/Frameworks",
        ]
        for d in default_framework_dirs:
            if d not in search_dirs:
                search_dirs.append(d)

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
                name if name.endswith(".framework") else f"{name}.framework"
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

        lib_filenames: list[str] = []
        if name.startswith("lib") and (
            name.endswith(".a") or name.endswith(".so") or name.endswith(".dylib")
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
            raise FileNotFoundError(f"Could not find library: {', '.join(names)}")
