"""Tests for check_symbol_exists command."""

from pathlib import Path
from cja.generator import BuildContext
from cja.parser import Command
from cja.generator import process_commands


def test_check_symbol_exists_found():
    """Test check_symbol_exists with a symbol that exists."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_symbol_exists",
            args=["printf", "stdio.h", "RESULT_VAR"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT_VAR"] == "1"


def test_check_symbol_exists_not_found():
    """Test check_symbol_exists with a symbol that doesn't exist."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_symbol_exists",
            args=["nonexistent_symbol", "stdio.h", "RESULT_VAR"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT_VAR"] == ""


def test_check_symbol_exists_multiple_headers():
    """Test check_symbol_exists with multiple headers."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_symbol_exists",
            args=["printf", "stdio.h", "stdlib.h", "RESULT_VAR"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT_VAR"] == "1"


def test_check_symbol_exists_semicolon_list():
    """Test check_symbol_exists with semicolon-separated header list."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_symbol_exists",
            args=["printf", "stdio.h;stdlib.h", "RESULT_VAR"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT_VAR"] == "1"
