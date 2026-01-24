"""Tests for strict mode behavior."""

from pathlib import Path

import pytest

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


def test_include_unknown_module_strict() -> None:
    """Test that include(unknown_module) errors in strict mode."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="include", args=["NonExistentModule"], line=1),
    ]
    with pytest.raises(RuntimeError, match="Unknown module: NonExistentModule"):
        process_commands(commands, ctx, strict=True)


def test_include_unknown_module_non_strict() -> None:
    """Test that include(unknown_module) is ignored in non-strict mode."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="include", args=["NonExistentModule"], line=1),
    ]
    # Should not raise
    process_commands(commands, ctx, strict=False)


def test_include_known_module_strict() -> None:
    """Test that include(known_module) works in strict mode."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="include", args=["CheckIPOSupported"], line=1),
    ]
    # Should not raise
    process_commands(commands, ctx, strict=True)
