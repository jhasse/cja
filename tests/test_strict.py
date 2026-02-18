"""Tests for strict mode behavior."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_include_unknown_module_strict(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that include(unknown_module) errors in strict mode."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="include", args=["NonExistentModule"], line=1),
    ]
    with pytest.raises(SystemExit) as exc_info:
        process_commands(commands, ctx, strict=True)
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "CMakeLists.txt:1:" in captured.err
    assert "error:" in captured.err
    assert "unknown module: NonExistentModule" in captured.err


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

def test_include_check_symbol_exists_strict() -> None:
    """Test that include(CheckSymbolExists) works in strict mode."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="include", args=["CheckSymbolExists"], line=1),
    ]
    # Should not raise
    process_commands(commands, ctx, strict=True)


def test_unsupported_command_strict(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that unsupported commands error in strict mode."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="unsupported_command", args=["arg1"], line=33),
    ]
    with pytest.raises(SystemExit) as exc_info:
        process_commands(commands, ctx, strict=True)
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "CMakeLists.txt:33:" in captured.err
    assert "error:" in captured.err
    assert "unsupported command: unsupported_command()" in captured.err


def test_unsupported_command_non_strict() -> None:
    """Test that unsupported commands are ignored in non-strict mode."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="unsupported_command", args=["arg1"], line=33),
    ]
    # Should not raise
    process_commands(commands, ctx, strict=False)
