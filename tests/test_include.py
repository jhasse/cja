"""Tests for include command."""

from pathlib import Path

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


def test_include_ctest() -> None:
    """Test include(CTest) sets BUILD_TESTING to ON."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="include", args=["CTest"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["BUILD_TESTING"] == "ON"


def test_include_ctest_respects_existing() -> None:
    """Test include(CTest) does not override existing BUILD_TESTING."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["BUILD_TESTING"] = "OFF"
    commands = [Command(name="include", args=["CTest"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["BUILD_TESTING"] == "OFF"


def test_include_unknown_module() -> None:
    """Test include with unknown module (should be ignored)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="include", args=["UnknownModule"], line=1)]
    process_commands(commands, ctx)

    # Should not crash, just ignore
    assert "BUILD_TESTING" not in ctx.variables
