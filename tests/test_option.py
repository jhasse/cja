"""Tests for option command."""

from pathlib import Path

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


def test_option_default_off() -> None:
    """Test option with default value (OFF)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="option", args=["MY_OPTION", "Enable my feature"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["MY_OPTION"] == "OFF"


def test_option_explicit_on() -> None:
    """Test option with explicit ON value."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="option", args=["MY_OPTION", "Enable my feature", "ON"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["MY_OPTION"] == "ON"


def test_option_explicit_off() -> None:
    """Test option with explicit OFF value."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="option", args=["MY_OPTION", "Enable my feature", "OFF"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["MY_OPTION"] == "OFF"


def test_option_does_not_override() -> None:
    """Test that option does not override existing variable."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_OPTION"] = "ON"
    commands = [Command(name="option", args=["MY_OPTION", "Enable my feature", "OFF"], line=1)]
    process_commands(commands, ctx)

    # Should keep original value
    assert ctx.variables["MY_OPTION"] == "ON"


def test_option_with_if() -> None:
    """Test option used in if condition."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="option", args=["ENABLE_FEATURE", "Enable feature", "ON"], line=1),
        Command(name="if", args=["ENABLE_FEATURE"], line=2),
        Command(name="set", args=["RESULT", "enabled"], line=3),
        Command(name="endif", args=[], line=4),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["RESULT"] == "enabled"
