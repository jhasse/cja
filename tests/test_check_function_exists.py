"""Tests for check_function_exists command."""

from pathlib import Path

import pytest
import termcolor

from cja.configurator import process_commands
from cja.generator import BuildContext
from cja.parser import Command


def test_check_function_exists_found():
    """Test check_function_exists with a function that exists in libc."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_function_exists",
            args=["printf", "RESULT_VAR"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT_VAR"] == "1"


def test_check_function_exists_not_found():
    """Test check_function_exists with a function that doesn't exist."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_function_exists",
            args=["this_function_does_not_exist_anywhere", "RESULT_VAR"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT_VAR"] == ""


def test_check_function_exists_with_required_library():
    """Test check_function_exists resolving a symbol via CMAKE_REQUIRED_LIBRARIES.

    On glibc 2.34+ dlopen lives in libc, but specifying libdl must not break the
    check (passing -ldl remains valid). This mirrors LuaJIT's dlopen probe.
    """
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["CMAKE_REQUIRED_LIBRARIES"] = "dl"
    commands = [
        Command(
            name="check_function_exists",
            args=["dlopen", "HAVE_DLOPEN"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["HAVE_DLOPEN"] == "1"


def test_check_function_exists_prints_status_output(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test check_function_exists prints a single status line per check."""
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    termcolor.can_colorize.cache_clear()

    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_function_exists",
            args=["printf", "HAVE_PRINTF"],
            line=1,
        ),
        Command(
            name="check_function_exists",
            args=["this_function_does_not_exist_anywhere", "HAVE_NOPE"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)
    captured = capsys.readouterr()
    assert "✓ printf" in captured.out
    assert "✗ this_function_does_not_exist_anywhere" in captured.out


def test_check_function_exists_quiet_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that quiet mode suppresses check_function_exists status output."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.quiet = True
    commands = [
        Command(
            name="check_function_exists",
            args=["printf", "HAVE_PRINTF"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)
    captured = capsys.readouterr()
    assert "✓ printf" not in captured.out
