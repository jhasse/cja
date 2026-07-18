"""Tests for check_library_exists command."""

import platform
from pathlib import Path

import pytest

from cja.configurator import process_commands
from cja.generator import BuildContext
from cja.parser import Command


def test_check_library_exists_found(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A system library should be found when the symbol exists in it.

    libm is Unix-only; on Windows use ws2_32 as an equivalent probe.
    """
    if platform.system() == "Windows":
        library, function, var = "ws2_32", "WSAStartup", "HAVE_WS2_32"
    else:
        library, function, var = "m", "pow", "HAVE_LIBM"

    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_library_exists",
            args=[library, function, "", var],
            line=1,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables[var] == "1"
    assert f"✓ {library}" in capsys.readouterr().out


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
