"""Tests for check_library_exists command."""

from pathlib import Path

import pytest

from cja.configurator import process_commands
from cja.generator import BuildContext
from cja.parser import Command


def test_check_library_exists_libm(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """libm should be found on Unix systems."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_library_exists",
            args=["m", "pow", "", "HAVE_LIBM"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["HAVE_LIBM"] == "1"
    assert "✓ m" in capsys.readouterr().out


def test_check_library_exists_missing() -> None:
    """A nonexistent library should leave the result variable empty."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_library_exists",
            args=["definitely_not_a_real_lib_xyz", "pow", "", "HAVE_NOPE"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["HAVE_NOPE"] == ""
