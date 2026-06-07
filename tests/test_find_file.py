"""Tests for find_file command."""

from pathlib import Path
import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_find_file_basic(tmp_path: Path) -> None:
    include_dir = tmp_path / "include"
    include_dir.mkdir()
    header_file = include_dir / "my_header.h"
    header_file.touch()

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(
            name="find_file",
            args=["MY_HEADER", "my_header.h", str(include_dir)],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    # find_file returns the full path including the file name (unlike find_path).
    assert ctx.variables["MY_HEADER"] == str(header_file.absolute())


def test_find_file_with_names(tmp_path: Path) -> None:
    include_dir = tmp_path / "include"
    include_dir.mkdir()
    header_file = include_dir / "other.h"
    header_file.touch()

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(
            name="find_file",
            args=[
                "HDR",
                "NAMES",
                "missing.h",
                "other.h",
                "PATHS",
                str(include_dir),
            ],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["HDR"] == str(header_file.absolute())


def test_find_file_with_suffixes(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    inc = base_dir / "include" / "X11"
    inc.mkdir(parents=True)
    header = inc / "Xlib.h"
    header.touch()

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(
            name="find_file",
            args=[
                "XLIB",
                "NAMES",
                "X11/Xlib.h",
                "PATHS",
                str(base_dir),
                "PATH_SUFFIXES",
                "include",
            ],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["XLIB"] == str(header.absolute())


def test_find_file_not_found(tmp_path: Path) -> None:
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(
            name="find_file",
            args=["NOPE", "nonexistent.h", str(tmp_path)],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["NOPE"] == "NOPE-NOTFOUND"


def test_find_file_required_fails(tmp_path: Path) -> None:
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(
            name="find_file",
            args=["NOPE", "nonexistent.h", "REQUIRED"],
            line=1,
        ),
    ]
    with pytest.raises(
        FileNotFoundError, match="Could not find file for: nonexistent.h"
    ):
        process_commands(commands, ctx)
