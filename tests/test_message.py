"""Tests for message command."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_message_status(capsys: pytest.CaptureFixture[str]) -> None:
    """Test message with STATUS mode; like CMake, arguments are concatenated."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="message", args=["STATUS", "Hello", "World"], line=1)]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert captured.out == "HelloWorld\n"


def test_message_no_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """Test message without mode."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="message", args=["Hello", "World"], line=1)]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert captured.out == "HelloWorld\n"


def test_message_warning(capsys: pytest.CaptureFixture[str]) -> None:
    """Test message with WARNING mode."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="message", args=["WARNING", "This is a warning"], line=1)]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert "CMakeLists.txt:1:" in captured.err
    assert "warning:" in captured.err
    assert "This is a warning" in captured.err


def test_message_fatal_error() -> None:
    """Test message with FATAL_ERROR mode."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="message", args=["FATAL_ERROR", "Something went wrong"], line=1)]

    with pytest.raises(SystemExit) as exc_info:
        process_commands(commands, ctx)
    assert exc_info.value.code == 1


def test_message_log_levels(capsys: pytest.CaptureFixture[str]) -> None:
    """VERBOSE, DEBUG and TRACE are hidden by default, NOTICE is shown."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="message", args=[mode, mode.lower()], line=1)
        for mode in ("NOTICE", "STATUS", "VERBOSE", "DEBUG", "TRACE")
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert captured.out == "notice\nstatus\n"


def test_message_log_level_variable(capsys: pytest.CaptureFixture[str]) -> None:
    """CMAKE_MESSAGE_LOG_LEVEL shows more or fewer messages."""
    modes = ("NOTICE", "STATUS", "VERBOSE", "DEBUG", "TRACE")
    commands = [Command(name="message", args=[m, m.lower()], line=1) for m in modes]

    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["CMAKE_MESSAGE_LOG_LEVEL"] = "DEBUG"
    process_commands(commands, ctx)
    assert capsys.readouterr().out == "notice\nstatus\nverbose\ndebug\n"

    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["CMAKE_MESSAGE_LOG_LEVEL"] = "WARNING"
    process_commands([*commands, Command(name="message", args=["plain"], line=1)], ctx)
    assert capsys.readouterr().out == ""
