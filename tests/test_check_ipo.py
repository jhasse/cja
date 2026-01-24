"""Tests for check_ipo_supported command."""

from pathlib import Path

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


def test_check_ipo_supported_result() -> None:
    """Test check_ipo_supported sets RESULT variable."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="check_ipo_supported", args=["RESULT", "IPO_SUPPORTED"], line=1),
    ]
    process_commands(commands, ctx)

    assert "IPO_SUPPORTED" in ctx.variables
    # Should be TRUE or FALSE
    assert ctx.variables["IPO_SUPPORTED"] in ("TRUE", "FALSE")


def test_check_ipo_supported_with_output() -> None:
    """Test check_ipo_supported sets OUTPUT variable on failure."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_ipo_supported",
            args=["RESULT", "IPO_SUPPORTED", "OUTPUT", "IPO_ERROR"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert "IPO_SUPPORTED" in ctx.variables
    assert "IPO_ERROR" in ctx.variables
    # If supported, error should be empty; if not, it should have a message
    if ctx.variables["IPO_SUPPORTED"] == "TRUE":
        assert ctx.variables["IPO_ERROR"] == ""
