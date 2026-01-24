"""Tests for message command."""

import sys
from io import StringIO
from pathlib import Path

import pytest

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


def test_message_status(capsys: pytest.CaptureFixture[str]) -> None:
    """Test message with STATUS mode."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="message", args=["STATUS", "Hello", "World"], line=1)]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert captured.out == "Hello World\n"


def test_message_no_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """Test message without mode."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="message", args=["Hello", "World"], line=1)]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert captured.out == "Hello World\n"


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
