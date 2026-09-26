"""Tests for find_program command."""

import os
from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_find_program_basic() -> None:
    """Test finding a program that exists."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_program", args=["PYTHON", "python3", "python"], line=1)]
    process_commands(commands, ctx)

    assert "PYTHON" in ctx.variables
    assert os.path.basename(ctx.variables["PYTHON"]).lower().startswith(("python3", "python"))
    assert "NOTFOUND" not in ctx.variables["PYTHON"]


def test_find_program_with_names() -> None:
    """Test find_program with NAMES keyword."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_program", args=["SH", "NAMES", "sh", "bash"], line=1)]
    process_commands(commands, ctx)

    assert "SH" in ctx.variables
    assert "NOTFOUND" not in ctx.variables["SH"]


def test_find_program_not_found() -> None:
    """Test find_program when program doesn't exist."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_program", args=["NONEXISTENT", "nonexistent_xyz_123"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["NONEXISTENT"] == "NONEXISTENT-NOTFOUND"


def test_find_program_required_not_found() -> None:
    """Test find_program with REQUIRED when program doesn't exist."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_program", args=["NONEXISTENT", "nonexistent_xyz_123", "REQUIRED"], line=1)]

    with pytest.raises(FileNotFoundError, match="Could not find program"):
        process_commands(commands, ctx)


def test_find_program_followed_by_if(capsys: pytest.CaptureFixture[str]) -> None:
    """Test find_program followed by if statement (regression test for variable shadowing bug)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_VERSION"] = "0"
    commands = [
        Command(name="find_program", args=["MY_PROG", "nonexistent_xyz_123"], line=1),
        Command(name="if", args=["MY_VERSION", "GREATER", "1"], line=2),
        Command(name="message", args=["STATUS", "version is greater"], line=3),
        Command(name="else", args=[], line=4),
        Command(name="message", args=["STATUS", "version is not greater"], line=5),
        Command(name="endif", args=[], line=6),
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert "version is not greater" in captured.out
    assert ctx.variables["MY_PROG"] == "MY_PROG-NOTFOUND"


def _run(commands: list[Command]) -> BuildContext:
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(commands, ctx)
    return ctx


def test_find_program_searches_again_after_notfound() -> None:
    """A NOTFOUND cache entry doesn't stop a later search, like in CMake."""
    ctx = _run(
        [
            Command(name="find_program", args=["PY", "nonexistent_prog_xyz"], line=1),
            Command(name="find_program", args=["PY", "python3", "python"], line=2),
        ]
    )
    assert "NOTFOUND" not in ctx.variables["PY"]
    assert ctx.cache_values["PY"] == ctx.variables["PY"]


def test_find_program_skips_when_already_set() -> None:
    """An existing non-NOTFOUND value (cache, normal or empty) skips the search."""
    ctx = _run(
        [
            Command(name="set", args=["P1", "/custom", "CACHE", "FILEPATH", ""], line=1),
            Command(name="find_program", args=["P1", "python3"], line=2),
            Command(name="set", args=["P2", "/normal"], line=3),
            Command(name="find_program", args=["P2", "python3"], line=4),
            Command(name="set", args=["P3", "", "CACHE", "FILEPATH", ""], line=5),
            Command(name="find_program", args=["P3", "python3"], line=6),
        ]
    )
    assert ctx.variables["P1"] == "/custom"
    assert ctx.variables["P2"] == "/normal"
    assert "P2" not in ctx.cache_values
    assert ctx.variables["P3"] == ""


def test_find_program_updates_notfound_normal_variable() -> None:
    """A result is cached and also replaces a NOTFOUND normal variable (CMP0125)."""
    ctx = _run(
        [
            Command(name="set", args=["PY", "PY-NOTFOUND"], line=1),
            Command(name="find_program", args=["PY", "python3", "python"], line=2),
        ]
    )
    assert "NOTFOUND" not in ctx.variables["PY"]
    assert ctx.cache_values["PY"] == ctx.variables["PY"]


def test_find_program_no_cache() -> None:
    """NO_CACHE stores the result as a normal variable only."""
    ctx = _run(
        [Command(name="find_program", args=["PY", "python3", "python", "NO_CACHE"], line=1)]
    )
    assert "NOTFOUND" not in ctx.variables["PY"]
    assert "PY" not in ctx.cache_values
