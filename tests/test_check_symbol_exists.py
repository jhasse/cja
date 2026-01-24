"""Tests for check_cxx_symbol_exists command."""

from pathlib import Path

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


def test_check_cxx_symbol_exists_found() -> None:
    """Test check_cxx_symbol_exists with a symbol that exists."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_cxx_symbol_exists",
            args=["std::cout", "iostream", "HAS_COUT"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert "HAS_COUT" in ctx.variables
    assert ctx.variables["HAS_COUT"] == "1"


def test_check_cxx_symbol_exists_not_found() -> None:
    """Test check_cxx_symbol_exists with a symbol that doesn't exist."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_cxx_symbol_exists",
            args=["nonexistent_symbol_12345", "cstdio", "HAS_FAKE"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert "HAS_FAKE" in ctx.variables
    assert ctx.variables["HAS_FAKE"] == ""


def test_check_cxx_symbol_exists_multiple_headers() -> None:
    """Test check_cxx_symbol_exists with multiple headers."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_cxx_symbol_exists",
            args=["printf", "cstdio", "cstdlib", "HAS_PRINTF"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert "HAS_PRINTF" in ctx.variables
    assert ctx.variables["HAS_PRINTF"] == "1"


def test_check_cxx_symbol_exists_semicolon_list() -> None:
    """Test check_cxx_symbol_exists with semicolon-separated header list."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_cxx_symbol_exists",
            args=["printf", "cstdio;cstdlib", "HAS_PRINTF"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert "HAS_PRINTF" in ctx.variables
    assert ctx.variables["HAS_PRINTF"] == "1"
