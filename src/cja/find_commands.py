"""Handlers for the simple CMake find_* commands.

Covers ``find_program``, ``find_path``, ``find_file`` and ``find_library``.
The richer ``find_package`` command lives in :mod:`cja.find_package`.
"""

import os
import platform
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .build_context import BuildContext
from .parser import Command
from .utils import (
    UNDEFINED_VAR_SENTINEL,
    is_truthy,
    split_unquoted_list_args,
    to_posix_path,
)


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


# Flags that only exclude search locations cja never looks in anyway (except
# NO_SYSTEM_ENVIRONMENT_PATH for find_program, which searches PATH).
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
# Flags that exclude search locations find_path(), find_file() and
# find_library() look in, but can't exclude yet. find_program() supports them.
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
    validator: str = ""
    # NO_*_PATH and *_FIND_ROOT_PATH flags
    flags: set[str] = field(default_factory=set[str])


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
            if i + 1 < len(args):
                result.validator = args[i + 1]
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
        elif arg in _NO_OP_FLAGS or arg in _UNSUPPORTED_FLAGS:
            result.flags.add(arg)
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


def _unsupported_find_args(parsed: _FindArgs) -> list[str]:
    """Return the arguments that find_path/find_file/find_library ignore."""
    unsupported = ["VALIDATOR"] if parsed.validator else []
    return unsupported + sorted(parsed.flags & _UNSUPPORTED_FLAGS)


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


def _program_search_dirs(ctx: BuildContext, parsed: _FindArgs) -> list[str]:
    """Return the directories find_program() searches, in CMake's order."""
    dirs: list[str] = []

    def add_prefixes(prefixes: list[str]) -> None:
        for prefix in prefixes:
            dirs.extend([f"{prefix}/bin", f"{prefix}/sbin", prefix])

    def variable(name: str) -> list[str]:
        value = ctx.variables.get(name, "")
        if not value or value == UNDEFINED_VAR_SENTINEL:
            return []
        return split_unquoted_list_args(value)

    def environment(name: str) -> list[str]:
        return [d for d in os.environ.get(name, "").split(os.pathsep) if d]

    use_defaults = not parsed.no_default_path
    if use_defaults and "NO_CMAKE_PATH" not in parsed.flags:
        add_prefixes(variable("CMAKE_PREFIX_PATH"))
        dirs.extend(variable("CMAKE_PROGRAM_PATH"))
    if use_defaults and "NO_CMAKE_ENVIRONMENT_PATH" not in parsed.flags:
        add_prefixes(environment("CMAKE_PREFIX_PATH"))
        dirs.extend(environment("CMAKE_PROGRAM_PATH"))
    dirs.extend(parsed.hints)
    if use_defaults and "NO_SYSTEM_ENVIRONMENT_PATH" not in parsed.flags:
        dirs.extend(environment("PATH"))
    if use_defaults and "NO_CMAKE_SYSTEM_PATH" not in parsed.flags:
        if platform.system() == "Windows":
            add_prefixes(["C:/Program Files", "C:/Program Files (x86)"])
        else:
            if platform.system() == "Darwin" and Path("/opt/homebrew").is_dir():
                add_prefixes(["/opt/homebrew"])
            add_prefixes(["/usr/local", "/usr"])
            dirs.extend(["/bin", "/sbin"])
        dirs.extend(variable("CMAKE_SYSTEM_PROGRAM_PATH"))
    dirs.extend(parsed.paths)

    # Each directory is tried with every suffix before the directory itself.
    result: list[str] = []
    for d in dirs:
        d = os.path.expanduser(d.strip())
        if not d:
            continue
        for candidate in [*(os.path.join(d, s) for s in parsed.suffixes), d]:
            if candidate not in result:
                result.append(candidate)
    return result


def _executable_in(directory: str, name: str) -> str | None:
    """Return the path of the program ``name`` in ``directory``, if it is one."""
    extensions = [""]
    if platform.system() == "Windows":
        extensions += os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(os.pathsep)
    for ext in extensions:
        candidate = os.path.join(directory, name + ext)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _is_valid_candidate(
    ctx: BuildContext, validator: str, candidate: str, strict: bool
) -> bool:
    """Call the VALIDATOR function, which sets its result variable to FALSE to reject."""
    if not validator:
        return True
    # Imported here to avoid a circular import.
    from .configurator import process_commands

    result_var = "__CJA_FIND_VALIDATOR_RESULT"
    ctx.variables[result_var] = "TRUE"
    call = Command(name=validator, args=[result_var, candidate], is_quoted=[True, True])
    process_commands([call], ctx, strict=strict)
    return is_truthy(ctx.variables.pop(result_var, "TRUE"))


def handle_find_program(
    ctx: BuildContext, cmd: Command, args: list[str], strict: bool
) -> None:
    """Handle find_program() command."""
    if len(args) < 2:
        return

    parsed = _parse_find_args(args)
    if parsed.validator and parsed.validator.lower() not in ctx.functions:
        ctx.check_unsupported_args(cmd, ["VALIDATOR"], strict)
        parsed.validator = ""

    var_name = args[0]
    if _is_already_resolved(ctx, var_name):
        return

    search_dirs = _program_search_dirs(ctx, parsed)
    found_path = None
    for name, d in _name_dir_pairs(parsed.names, search_dirs, parsed.names_per_dir):
        # A name with a directory part is checked as it is.
        candidate = _executable_in("" if os.path.dirname(name) else d, name)
        if candidate:
            candidate = to_posix_path(os.path.abspath(candidate))
            if _is_valid_candidate(ctx, parsed.validator, candidate, strict):
                found_path = candidate
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
    ctx.check_unsupported_args(cmd, _unsupported_find_args(parsed), strict)

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
    ctx.check_unsupported_args(cmd, _unsupported_find_args(parsed), strict)

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
    ctx.check_unsupported_args(cmd, _unsupported_find_args(parsed), strict)

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
