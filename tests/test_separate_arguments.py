"""Tests for the separate_arguments command."""

import shutil
import sys
from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command
from cja.utils import to_posix_path


def _separate(*args: str, strict: bool = True) -> str | None:
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    # The command line is a quoted argument, as it may have semicolons.
    quoted = [False, *(len(args) > 1 and arg is args[-1] for arg in args)]
    command = Command(
        name="separate_arguments", args=["RESULT", *args], is_quoted=quoted, line=1
    )
    process_commands([command], ctx, strict=strict)
    return ctx.variables.get("RESULT")


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("a b  c", "a;b;c"),
        ("a\tb\nc", "a;b;c"),
        ("", ""),
        ("  ", ""),
        ("'c d' \"e f\" g\"h i\"j", "c d;e f;gh ij"),
        ("a '' b", "a;;b"),
        # A backslash makes any character a literal one, also in quotes
        (r"a\ b k\\l 'm\'n' " + r'"o\"p" q\nr', "a b;k\\l;m'n;o\"p;qnr"),
        ("a;b c", "a\\;b;c"),
    ],
)
def test_separate_arguments_unix_command(command: str, expected: str) -> None:
    assert _separate("UNIX_COMMAND", command) == expected


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("a b  c", "a;b;c"),
        (r"a\b c:\d\ ", "a\\b;c:\\d\\"),
        ('"c d" e"f g"h', "c d;ef gh"),
        # Backslashes only escape when they're in front of a quote
        (r'e\"f g\\"h i" \\\"j', 'e"f;g\\h i;\\"j'),
        ("'k l' \"\"", "'k;l';"),
    ],
)
def test_separate_arguments_windows_command(command: str, expected: str) -> None:
    assert _separate("WINDOWS_COMMAND", command) == expected


def test_separate_arguments_native_command() -> None:
    expected = "a\\b" if sys.platform == "win32" else "ab"
    assert _separate("NATIVE_COMMAND", r"a\b") == expected


def test_separate_arguments_without_command() -> None:
    assert _separate("UNIX_COMMAND") == ""


def test_separate_arguments_variable() -> None:
    """The form without a mode turns the spaces of a variable into separators."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["FLAGS", "a b  c;d"], line=1),
        Command(name="separate_arguments", args=["FLAGS"], line=2),
        Command(name="separate_arguments", args=["UNDEFINED"], line=3),
    ]
    process_commands(commands, ctx, strict=True)
    assert ctx.variables["FLAGS"] == "a;b;;c;d"
    assert "UNDEFINED" not in ctx.variables


def test_separate_arguments_program() -> None:
    """PROGRAM looks up the program and keeps its arguments as one string."""
    program = Path(sys.executable).name
    found = shutil.which(program)
    if found is None:
        pytest.skip("the Python interpreter isn't in the PATH")
    found = to_posix_path(found)

    command = f"{program} -c  'print(1)' x"
    assert _separate("UNIX_COMMAND", "PROGRAM", command) == f"{found}; -c  'print(1)' x"
    assert (
        _separate("UNIX_COMMAND", "PROGRAM", "SEPARATE_ARGS", command)
        == f"{found};-c;print(1);x"
    )
    assert _separate("UNIX_COMMAND", "PROGRAM", program) == f"{found};"
    assert _separate("UNIX_COMMAND", "PROGRAM", "no-such-program-xyz a b") == ""
    assert _separate("UNIX_COMMAND", "PROGRAM", "") == ""


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["BOGUS", "a b"],
        ["UNIX_COMMAND", "a b", "c d"],
    ],
)
def test_separate_arguments_errors(
    args: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    variable = ["RESULT"] if args else []
    command = Command(name="separate_arguments", args=[*variable, *args], line=1)

    process_commands([command], ctx)
    assert "RESULT" not in ctx.variables
    assert "warning:" in capsys.readouterr().err

    with pytest.raises(SystemExit):
        process_commands([command], ctx, strict=True)
