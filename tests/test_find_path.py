"""Tests for find_path command."""

from pathlib import Path
import pytest

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


def test_find_path_basic(tmp_path: Path) -> None:
    """Test find_path basic usage."""
    include_dir = tmp_path / "include"
    include_dir.mkdir()
    header_file = include_dir / "my_header.h"
    header_file.touch()

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(
            name="find_path",
            args=["MY_HEADER_PATH", "my_header.h", str(include_dir)],
            line=1,
        ),
    ]

    process_commands(commands, ctx)

    assert ctx.variables["MY_HEADER_PATH"] == str(include_dir.absolute())


def test_find_path_with_names(tmp_path: Path) -> None:
    """Test find_path with NAMES keyword."""
    include_dir = tmp_path / "include"
    include_dir.mkdir()
    header_file = include_dir / "other_header.h"
    header_file.touch()

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(
            name="find_path",
            args=[
                "MY_HEADER_PATH",
                "NAMES",
                "my_header.h",
                "other_header.h",
                "PATHS",
                str(include_dir),
            ],
            line=1,
        ),
    ]

    process_commands(commands, ctx)

    assert ctx.variables["MY_HEADER_PATH"] == str(include_dir.absolute())


def test_find_path_with_suffixes(tmp_path: Path) -> None:
    """Test find_path with PATH_SUFFIXES."""
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    include_dir = base_dir / "include" / "foo"
    include_dir.mkdir(parents=True)
    header_file = include_dir / "foo.h"
    header_file.touch()

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(
            name="find_path",
            args=[
                "FOO_PATH",
                "foo.h",
                "PATHS",
                str(base_dir),
                "PATH_SUFFIXES",
                "include/foo",
            ],
            line=1,
        ),
    ]

    process_commands(commands, ctx)

    assert ctx.variables["FOO_PATH"] == str(include_dir.absolute())


def test_find_path_not_found(tmp_path: Path) -> None:
    """Test find_path when file is not found."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(
            name="find_path",
            args=["NOT_FOUND_VAR", "nonexistent.h", str(tmp_path)],
            line=1,
        ),
    ]

    process_commands(commands, ctx)

    assert ctx.variables["NOT_FOUND_VAR"] == "NOT_FOUND_VAR-NOTFOUND"


def test_find_path_required_fails(tmp_path: Path) -> None:
    """Test find_path with REQUIRED when file is not found."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(
            name="find_path",
            args=["NOT_FOUND_VAR", "nonexistent.h", "REQUIRED"],
            line=1,
        ),
    ]

    with pytest.raises(
        FileNotFoundError, match="Could not find path for: nonexistent.h"
    ):
        process_commands(commands, ctx)
