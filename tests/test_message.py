"""Tests for message command."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, configure, process_commands
from cja.parser import Command, parse


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


def test_message_send_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """SEND_ERROR continues processing, but configure fails without generating."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "CMakeLists.txt").write_text(
        "message(SEND_ERROR first)\nmessage(SEND_ERROR second)\n"
    )
    with pytest.raises(SystemExit) as exc_info:
        configure(tmp_path, "build")
    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "first" in err
    assert "second" in err
    assert not (tmp_path / "build.ninja").exists()


def test_message_checks(capsys: pytest.CaptureFixture[str]) -> None:
    """CHECK_PASS and CHECK_FAIL complete the message of the latest CHECK_START."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(
        parse(
            'message(CHECK_START "Looking for foo")\n'
            'message(CHECK_START "Looking for bar")\n'
            'message(CHECK_FAIL "not found")\n'
            'message(CHECK_PASS "found")\n'
            "set(CMAKE_MESSAGE_LOG_LEVEL NOTICE)\n"
            'message(CHECK_START "hidden")\n'
            'message(CHECK_PASS "hidden")\n'
            "unset(CMAKE_MESSAGE_LOG_LEVEL)\n"
            'message(CHECK_PASS "orphan")\n'
        ),
        ctx,
    )
    captured = capsys.readouterr()
    assert captured.out == (
        "Looking for foo\n"
        "Looking for bar\n"
        "Looking for bar - not found\n"
        "Looking for foo - found\n"
    )
    assert "Ignored CHECK_PASS without CHECK_START" in captured.err


def test_message_indent(capsys: pytest.CaptureFixture[str]) -> None:
    """CMAKE_MESSAGE_INDENT indents every line of messages but warnings."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(
        parse(
            'list(APPEND CMAKE_MESSAGE_INDENT "  ")\n'
            'message("notice")\n'
            'message(STATUS "multi\\nline")\n'
            'message(CHECK_START "check")\n'
            'list(APPEND CMAKE_MESSAGE_INDENT "> ")\n'
            'message(CHECK_PASS "done")\n'
            'message(WARNING "warning")\n'
        ),
        ctx,
    )
    captured = capsys.readouterr()
    assert captured.out == "  notice\n  multi\n  line\n  check\n  > check - done\n"
    assert "warning: warning" in captured.err
