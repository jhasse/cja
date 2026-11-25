"""The CMake files of a project, for ``cja format`` and the language server."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from itertools import islice
from pathlib import Path

from .format import decode, source_command_specs
from .format_specs import CmdSpec

# Directories that are never searched for CMake files
_SKIPPED_DIRS = frozenset({"node_modules", "__pycache__", "CMakeFiles", "_deps"})
MAX_FILES = 10000
_PROJECT_CALL = re.compile(rb"^[ \t]*project[ \t]*\(", re.IGNORECASE | re.MULTILINE)


def is_cmake_file(path: Path) -> bool:
    name = path.name.lower()
    return name == "cmakelists.txt" or name.endswith(".cmake")


def cmake_files(root: Path) -> Iterator[Path]:
    """The CMake files below root, in the same order every time."""
    for dirpath, dirnames, filenames in os.walk(root):
        # Build directories (configured by CMake or cja) and hidden ones
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not d.startswith((".", "build"))
            and d not in _SKIPPED_DIRS
            and not (Path(dirpath) / d / "CMakeCache.txt").exists()
        )
        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            if is_cmake_file(path):
                yield path


def _calls_project(cmakelists: Path) -> bool:
    try:
        return _PROJECT_CALL.search(cmakelists.read_bytes()) is not None
    except OSError:
        return False


def project_root(directory: Path) -> Path | None:
    """The directory of the project that the CMake files of a directory belong to.

    That's the Git repository it's in. Without one, it's the outermost directory
    above whose CMakeLists.txt calls project(), or if there's none, the nearest
    one with a CMakeLists.txt, or else the directory itself.

    The home directory, what's above it and the root of a file system are never
    a project, as searching them for CMake files would take forever. A
    directory that isn't below any of them has none.
    """
    directory = Path(os.path.abspath(directory))
    try:
        home = Path.home()
    except RuntimeError:
        home = None
    if home is not None and (directory == home or directory in home.parents):
        return None
    candidates: list[Path] = []
    for candidate in (directory, *directory.parents):
        if candidate == home or candidate == candidate.parent:
            break
        candidates.append(candidate)
    if not candidates:
        return None
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    with_cmakelists = [c for c in candidates if (c / "CMakeLists.txt").is_file()]
    for candidate in reversed(with_cmakelists):
        if _calls_project(candidate / "CMakeLists.txt"):
            return candidate
    return with_cmakelists[0] if with_cmakelists else directory


def project_command_specs(root: Path) -> dict[str, CmdSpec]:
    """Formatter specs of the user commands defined in the CMake files below root.

    Like in the language server, these are the functions and macros that use
    cmake_parse_arguments(). If several have the same name, the last one wins.
    """
    specs: dict[str, CmdSpec] = {}
    for path in islice(cmake_files(root), MAX_FILES):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        # Lexing is what takes time, and most files don't define such commands
        if b"cmake_parse_arguments" not in data.lower():
            continue
        try:
            specs.update(source_command_specs(decode(data)[0], str(path)))
        except SyntaxError:
            pass
    return specs
