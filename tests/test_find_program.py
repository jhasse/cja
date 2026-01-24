"""Tests for find_program command."""

from pathlib import Path

import pytest

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


def test_find_program_basic() -> None:
    """Test finding a program that exists."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_program", args=["PYTHON", "python3", "python"], line=1)]
    process_commands(commands, ctx)

    assert "PYTHON" in ctx.variables
    assert ctx.variables["PYTHON"].endswith(("python3", "python"))
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
