"""Tests for find_library command."""

from pathlib import Path
import pytest
import platform

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_find_library_basic(tmp_path: Path) -> None:
    """Test find_library basic usage."""
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()

    if platform.system() == "Darwin":
        lib_name = "libtest.dylib"
    elif platform.system() == "Windows":
        lib_name = "libtest.lib"
    else:
        lib_name = "libtest.so"

    lib_file = lib_dir / lib_name
    lib_file.touch()

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(name="find_library", args=["MY_LIB", "test", str(lib_dir)], line=1),
    ]

    process_commands(commands, ctx)

    assert ctx.variables["MY_LIB"] == str(lib_file.absolute())


def test_find_library_with_names(tmp_path: Path) -> None:
    """Test find_library with NAMES keyword."""
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()

    lib_file = lib_dir / "libother.a"
    lib_file.touch()

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(
            name="find_library",
            args=["MY_LIB", "NAMES", "test", "other", "PATHS", str(lib_dir)],
            line=1,
        ),
    ]

    process_commands(commands, ctx)

    assert ctx.variables["MY_LIB"] == str(lib_file.absolute())


def test_find_library_with_suffixes(tmp_path: Path) -> None:
    """Test find_library with PATH_SUFFIXES."""
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    lib_dir = base_dir / "lib" / "foo"
    lib_dir.mkdir(parents=True)

    lib_file = lib_dir / "libfoo.a"
    lib_file.touch()

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(
            name="find_library",
            args=["FOO_LIB", "foo", "PATHS", str(base_dir), "PATH_SUFFIXES", "lib/foo"],
            line=1,
        ),
    ]

    process_commands(commands, ctx)

    assert ctx.variables["FOO_LIB"] == str(lib_file.absolute())


def test_find_library_not_found(tmp_path: Path) -> None:
    """Test find_library when library is not found."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(
            name="find_library",
            args=["NOT_FOUND_VAR", "nonexistent", str(tmp_path)],
            line=1,
        ),
    ]

    process_commands(commands, ctx)

    assert ctx.variables["NOT_FOUND_VAR"] == "NOT_FOUND_VAR-NOTFOUND"


def test_find_library_required_fails(tmp_path: Path) -> None:
    """Test find_library with REQUIRED when library is not found."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(
            name="find_library",
            args=["NOT_FOUND_VAR", "nonexistent", "REQUIRED"],
            line=1,
        ),
    ]

    with pytest.raises(FileNotFoundError, match="Could not find library: nonexistent"):
        process_commands(commands, ctx)


def test_find_library_uses_cmake_prefix_path(tmp_path: Path) -> None:
    """Test find_library fallback search in CMAKE_PREFIX_PATH lib directories."""
    prefix = tmp_path / "prefix"
    lib_dir = prefix / "lib"
    lib_dir.mkdir(parents=True)

    if platform.system() == "Darwin":
        lib_name = "libpref.dylib"
    elif platform.system() == "Windows":
        lib_name = "pref.lib"
    else:
        lib_name = "libpref.so"

    lib_file = lib_dir / lib_name
    lib_file.touch()

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    ctx.variables["CMAKE_PREFIX_PATH"] = str(prefix)

    commands = [
        Command(name="find_library", args=["PREF_LIB", "pref"], line=1),
    ]

    process_commands(commands, ctx)

    assert ctx.variables["PREF_LIB"] == str(lib_file.absolute())


def test_find_library_persists_from_function_scope(tmp_path: Path) -> None:
    """Test find_library result survives function scope via cache semantics."""
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    lib_file = lib_dir / "libinside.a"
    lib_file.touch()

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="function", args=["probe"], line=1),
        Command(
            name="find_library",
            args=["INNER_LIB", "NAMES", "inside", "PATHS", str(lib_dir)],
            line=2,
        ),
        Command(name="endfunction", args=[], line=3),
        Command(name="probe", args=[], line=4),
    ]

    process_commands(commands, ctx)

    assert ctx.variables["INNER_LIB"] == str(lib_file.absolute())
