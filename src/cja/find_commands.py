"""Handlers for the simple CMake find_* commands.

Covers ``find_program``, ``find_path``, ``find_file`` and ``find_library``.
The richer ``find_package`` command lives in :mod:`cja.find_package`.
"""

import os
import platform
import shutil
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .build_context import BuildContext
from .parser import Command
from .utils import UNDEFINED_VAR_SENTINEL, split_unquoted_list_args, to_posix_path


def _search_dirs_with_defaults(
    ctx: BuildContext,
    kind: str,
    hints: list[str],
    paths: list[str],
    no_default_path: bool = False,
) -> list[str]:
    """Build search dirs in CMake-like order: hints, paths, then defaults.

    With ``no_default_path`` only the explicit hints and paths are searched.
    """
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

    if no_default_path:
        return dirs

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


def _name_dir_pairs(
    names: list[str], search_dirs: list[str], names_per_dir: bool
) -> Iterator[tuple[str, str]]:
    """Yield ``(name, directory)`` candidates in CMake's search order.

    By default every directory is tried for the first name before moving on to
    the next name; ``NAMES_PER_DIR`` flips that to all names per directory.
    """
    if names_per_dir:
        for d in search_dirs:
            for name in names:
                yield name, d
    else:
        for name in names:
            for d in search_dirs:
                yield name, d


# Flags that only exclude search locations cja never looks in anyway.
_NO_OP_FLAGS = frozenset(
    {
        "OPTIONAL",
        "NO_PACKAGE_ROOT_PATH",
        "NO_SYSTEM_ENVIRONMENT_PATH",
        "NO_CMAKE_INSTALL_PREFIX",
        "CMAKE_FIND_ROOT_PATH_BOTH",
        "ONLY_CMAKE_FIND_ROOT_PATH",
        "NO_CMAKE_FIND_ROOT_PATH",
    }
)
# Flags that exclude search locations cja does look in, but can't exclude yet.
_UNSUPPORTED_FLAGS = frozenset(
    {"NO_CMAKE_PATH", "NO_CMAKE_ENVIRONMENT_PATH", "NO_CMAKE_SYSTEM_PATH"}
)


@dataclass
class _FindArgs:
    names: list[str] = field(default_factory=list[str])
    paths: list[str] = field(default_factory=list[str])
    hints: list[str] = field(default_factory=list[str])
    suffixes: list[str] = field(default_factory=list[str])
    required: bool = False
    no_cache: bool = False
    no_default_path: bool = False
    names_per_dir: bool = False
    # Arguments that would change the result in CMake but are ignored by cja.
    unsupported: list[str] = field(default_factory=list[str])


def _parse_find_args(args: list[str]) -> _FindArgs:
    """Parse the arguments shared by the find_* commands like CMake does.

    Arguments before the first keyword are names. Without any of the NAMES,
    PATHS, HINTS or PATH_SUFFIXES keywords the short signature is used: the
    first name is the name and the rest are paths.
    """
    result = _FindArgs()
    lists = {
        "NAMES": result.names,
        "PATHS": result.paths,
        "HINTS": result.hints,
        "PATH_SUFFIXES": result.suffixes,
    }
    current: list[str] | None = result.names
    new_style = False
    i = 1
    while i < len(args):
        arg = args[i]
        if arg in lists:
            current = lists[arg]
            new_style = True
        elif arg in ("DOC", "REGISTRY_VIEW"):
            current = None
            i += 1
        elif arg == "VALIDATOR":
            current = None
            result.unsupported.append(arg)
            i += 1
        elif arg == "REQUIRED":
            result.required = True
            current = None
        elif arg == "NO_CACHE":
            result.no_cache = True
            current = None
        elif arg == "NO_DEFAULT_PATH":
            result.no_default_path = True
            current = None
        elif arg == "NAMES_PER_DIR":
            result.names_per_dir = True
            current = None
        elif arg in _NO_OP_FLAGS:
            current = None
        elif arg in _UNSUPPORTED_FLAGS:
            result.unsupported.append(arg)
            current = None
        elif current is not None:
            current.append(arg)
        i += 1

    if not new_style and result.names:
        result.paths[:0] = result.names[1:]
        del result.names[1:]
    result.paths[:] = _expand_env(result.paths)
    result.hints[:] = _expand_env(result.hints)
    return result


def _expand_env(dirs: list[str]) -> list[str]:
    """Replace ``ENV <var>`` with the directories listed in that variable."""
    result: list[str] = []
    i = 0
    while i < len(dirs):
        if dirs[i] == "ENV" and i + 1 < len(dirs):
            env_value = os.environ.get(dirs[i + 1], "")
            result.extend(d for d in env_value.split(os.pathsep) if d)
            i += 2
        else:
            result.append(dirs[i])
            i += 1
    return result


def _is_already_resolved(ctx: BuildContext, var_name: str) -> bool:
    """Return True if the variable is set to a non-NOTFOUND value, so the search is skipped.

    Like CMake, this looks at the visible value (normal or cache) and treats an
    empty value as found.
    """
    existing = ctx.variables.get(var_name)
    if existing is None or existing == UNDEFINED_VAR_SENTINEL:
        return False
    return existing != "NOTFOUND" and not existing.endswith("-NOTFOUND")


def _store_find_result(
    ctx: BuildContext, var_name: str, value: str, no_cache: bool
) -> None:
    """Store a find result in the cache, or as a normal variable with NO_CACHE.

    Like CMake, found paths always use forward slashes, even on Windows.
    """
    value = to_posix_path(value)
    if no_cache:
        ctx.variables[var_name] = value
        return
    ctx.set_cache(var_name, value)
    # CMake also updates an existing normal binding (CMP0125 NEW)
    if var_name in ctx.variables.normal_bindings:
        ctx.variables[var_name] = value


def handle_find_program(
    ctx: BuildContext, cmd: Command, args: list[str], strict: bool
) -> None:
    """Handle find_program() command.

    Only PATH is searched, so the options that change where to look aren't
    supported.
    """
    if len(args) < 2:
        return

    parsed = _parse_find_args(args)
    unsupported = parsed.unsupported
    for keyword, values in (
        ("HINTS", parsed.hints),
        ("PATHS", parsed.paths),
        ("PATH_SUFFIXES", parsed.suffixes),
    ):
        if values:
            unsupported.append(keyword)
    if parsed.no_default_path:
        unsupported.append("NO_DEFAULT_PATH")
    if "NO_SYSTEM_ENVIRONMENT_PATH" in args:
        unsupported.append("NO_SYSTEM_ENVIRONMENT_PATH")
    if parsed.names_per_dir and len(parsed.names) > 1:
        unsupported.append("NAMES_PER_DIR")
    ctx.check_unsupported_args(cmd, unsupported, strict)

    var_name = args[0]
    if _is_already_resolved(ctx, var_name):
        return

    found_path = None
    for name in parsed.names:
        found_path = shutil.which(name)
        if found_path:
            break

    if found_path:
        _store_find_result(ctx, var_name, found_path, parsed.no_cache)
    else:
        _store_find_result(ctx, var_name, f"{var_name}-NOTFOUND", parsed.no_cache)
        if parsed.required:
            raise FileNotFoundError(
                f"Could not find program: {' or '.join(parsed.names)}"
            )


def handle_find_path(
    ctx: BuildContext, cmd: Command, args: list[str], strict: bool
) -> None:
    """Handle find_path() command."""
    if len(args) < 2:
        return

    parsed = _parse_find_args(args)
    ctx.check_unsupported_args(cmd, parsed.unsupported, strict)

    var_name = args[0]
    if _is_already_resolved(ctx, var_name):
        return

    search_dirs = _search_dirs_with_defaults(
        ctx, "path", parsed.hints, parsed.paths, parsed.no_default_path
    )

    found_dir = None
    for name, d in _name_dir_pairs(parsed.names, search_dirs, parsed.names_per_dir):
        for suffix in [""] + parsed.suffixes:
            base_path = Path(d) / suffix
            if (base_path / name).exists():
                found_dir = str(base_path.absolute())
                break
        if found_dir:
            break

    if found_dir:
        _store_find_result(ctx, var_name, found_dir, parsed.no_cache)
    else:
        _store_find_result(ctx, var_name, f"{var_name}-NOTFOUND", parsed.no_cache)
        if parsed.required:
            raise FileNotFoundError(f"Could not find path for: {', '.join(parsed.names)}")


def handle_find_file(
    ctx: BuildContext, cmd: Command, args: list[str], strict: bool
) -> None:
    """Handle find_file() command.

    Like find_path but stores the full path to the file (including its name).
    """
    if len(args) < 2:
        return

    parsed = _parse_find_args(args)
    ctx.check_unsupported_args(cmd, parsed.unsupported, strict)

    var_name = args[0]
    if _is_already_resolved(ctx, var_name):
        return

    search_dirs = _search_dirs_with_defaults(
        ctx, "path", parsed.hints, parsed.paths, parsed.no_default_path
    )

    found_file = None
    for name, d in _name_dir_pairs(parsed.names, search_dirs, parsed.names_per_dir):
        for suffix in [""] + parsed.suffixes:
            candidate = Path(d) / suffix / name
            if candidate.exists():
                found_file = str(candidate.absolute())
                break
        if found_file:
            break

    if found_file:
        _store_find_result(ctx, var_name, found_file, parsed.no_cache)
    else:
        _store_find_result(ctx, var_name, f"{var_name}-NOTFOUND", parsed.no_cache)
        if parsed.required:
            raise FileNotFoundError(f"Could not find file for: {', '.join(parsed.names)}")


def _library_extensions(ctx: BuildContext) -> list[str]:
    """Return the library file suffixes to try, in order of preference.

    ``CMAKE_FIND_LIBRARY_SUFFIXES`` (e.g. set to ``.a`` by Find modules that
    prefer static libraries) overrides the platform defaults.
    """
    configured = ctx.variables.get("CMAKE_FIND_LIBRARY_SUFFIXES", "")
    if configured and configured != UNDEFINED_VAR_SENTINEL:
        return [s for s in split_unquoted_list_args(configured) if s]
    if platform.system() == "Darwin":
        return [".dylib", ".tbd", ".a"]
    if platform.system() == "Windows":
        return [".lib", ".dll.a", ".a"]
    return [".so", ".a"]


def _find_library_file(
    search_dirs: list[str],
    suffixes: list[str],
    extensions: list[str],
    name: str,
) -> str | None:
    """Look for the library ``name`` (or a framework) in ``search_dirs``."""
    if platform.system() == "Darwin":
        framework_name = name if name.endswith(".framework") else f"{name}.framework"
        for d in search_dirs:
            for suffix in [""] + suffixes:
                framework_path = Path(d) / suffix / framework_name
                if framework_path.exists():
                    return str(framework_path.absolute())

    lib_filenames: list[str] = []
    if name.startswith("lib") and name.endswith((".a", ".so", ".dylib")):
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
                    return str(candidate.absolute())
    return None


def handle_find_library(
    ctx: BuildContext, cmd: Command, args: list[str], strict: bool
) -> None:
    """Handle find_library() command."""
    if len(args) < 2:
        return

    parsed = _parse_find_args(args)
    ctx.check_unsupported_args(cmd, parsed.unsupported, strict)

    var_name = args[0]
    if _is_already_resolved(ctx, var_name):
        return

    search_dirs = _search_dirs_with_defaults(ctx, "lib", parsed.hints, parsed.paths, parsed.no_default_path)

    if platform.system() == "Darwin" and not parsed.no_default_path:
        default_framework_dirs = [
            "/System/Library/Frameworks",
            "/Library/Frameworks",
        ]
        for d in default_framework_dirs:
            if d not in search_dirs:
                search_dirs.append(d)

    extensions = _library_extensions(ctx)

    found_lib: str | None = None
    if parsed.names_per_dir:
        for d in search_dirs:
            for name in parsed.names:
                found_lib = _find_library_file([d], parsed.suffixes, extensions, name)
                if found_lib:
                    break
            if found_lib:
                break
    else:
        for name in parsed.names:
            found_lib = _find_library_file(search_dirs, parsed.suffixes, extensions, name)
            if found_lib:
                break

    if found_lib:
        _store_find_result(ctx, var_name, found_lib, parsed.no_cache)
    else:
        _store_find_result(ctx, var_name, f"{var_name}-NOTFOUND", parsed.no_cache)
        if parsed.required:
            raise FileNotFoundError(f"Could not find library: {', '.join(parsed.names)}")
