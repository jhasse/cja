"""Tests for check_symbol_exists command."""

import platform
from pathlib import Path

import pytest
import termcolor

from cja.configurator import process_commands
from cja.generator import BuildContext
from cja.parser import Command


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


def test_check_symbol_exists_x86_64_macro(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test check_symbol_exists for the compiler macro __x86_64__."""
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    termcolor.can_colorize.cache_clear()

    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_symbol_exists",
            args=["__x86_64__", "", "HAVE_X86_64"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    on_x86_64 = platform.machine().lower() in ("x86_64", "amd64")
    if on_x86_64:
        assert ctx.variables["HAVE_X86_64"] == "1"
        assert "✓ __x86_64__" in capsys.readouterr().out
    else:
        assert ctx.variables["HAVE_X86_64"] == ""
        assert "✗ __x86_64__" in capsys.readouterr().out


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


def test_check_symbol_exists_prints_status_output(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test check_symbol_exists prints a single status line per check."""
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    termcolor.can_colorize.cache_clear()

    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_symbol_exists",
            args=["printf", "stdio.h", "HAVE_PRINTF"],
            line=1,
        ),
        Command(
            name="check_symbol_exists",
            args=["nonexistent_symbol", "stdio.h", "HAVE_NOPE"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)
    captured = capsys.readouterr()
    assert "✓ printf" in captured.out
    assert "✗ nonexistent_symbol" in captured.out


def test_check_symbol_exists_quiet_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that quiet mode suppresses check_symbol_exists status output."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.quiet = True
    commands = [
        Command(
            name="check_symbol_exists",
            args=["printf", "stdio.h", "HAVE_PRINTF"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)
    captured = capsys.readouterr()
    assert "✓ printf" not in captured.out


def test_check_symbol_exists_cmake_required_quiet(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that CMAKE_REQUIRED_QUIET suppresses status output."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["CMAKE_REQUIRED_QUIET"] = "TRUE"
    commands = [
        Command(
            name="check_symbol_exists",
            args=["printf", "stdio.h", "HAVE_PRINTF"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)
    captured = capsys.readouterr()
    assert "✓ printf" not in captured.out
