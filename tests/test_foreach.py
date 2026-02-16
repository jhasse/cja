"""Tests for foreach command."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_foreach_basic(capsys: pytest.CaptureFixture[str]) -> None:
    """Test basic foreach with items."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="foreach", args=["item", "a", "b", "c"], line=1),
        Command(name="message", args=["STATUS", "${item}"], line=2),
        Command(name="endforeach", args=[], line=3),
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert "a" in captured.out
    assert "b" in captured.out
    assert "c" in captured.out


def test_foreach_range_stop(capsys: pytest.CaptureFixture[str]) -> None:
    """Test foreach with RANGE stop."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="foreach", args=["i", "RANGE", "3"], line=1),
        Command(name="message", args=["STATUS", "${i}"], line=2),
        Command(name="endforeach", args=[], line=3),
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert "0" in captured.out
    assert "1" in captured.out
    assert "2" in captured.out
    assert "3" in captured.out


def test_foreach_range_start_stop(capsys: pytest.CaptureFixture[str]) -> None:
    """Test foreach with RANGE start stop."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="foreach", args=["i", "RANGE", "2", "5"], line=1),
        Command(name="message", args=["STATUS", "${i}"], line=2),
        Command(name="endforeach", args=[], line=3),
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert "2" in captured.out
    assert "3" in captured.out
    assert "4" in captured.out
    assert "5" in captured.out


def test_foreach_range_step(capsys: pytest.CaptureFixture[str]) -> None:
    """Test foreach with RANGE start stop step."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="foreach", args=["i", "RANGE", "0", "10", "2"], line=1),
        Command(name="message", args=["STATUS", "${i}"], line=2),
        Command(name="endforeach", args=[], line=3),
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert "0" in captured.out
    assert "2" in captured.out
    assert "4" in captured.out
    assert "6" in captured.out
    assert "8" in captured.out
    assert "10" in captured.out


def test_foreach_in_lists(capsys: pytest.CaptureFixture[str]) -> None:
    """Test foreach IN LISTS."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "x y z"
    commands = [
        Command(name="foreach", args=["item", "IN", "LISTS", "MY_LIST"], line=1),
        Command(name="message", args=["STATUS", "${item}"], line=2),
        Command(name="endforeach", args=[], line=3),
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert "x" in captured.out
    assert "y" in captured.out
    assert "z" in captured.out


def test_foreach_in_items(capsys: pytest.CaptureFixture[str]) -> None:
    """Test foreach IN ITEMS."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="foreach", args=["item", "IN", "ITEMS", "one", "two", "three"], line=1),
        Command(name="message", args=["STATUS", "${item}"], line=2),
        Command(name="endforeach", args=[], line=3),
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert "one" in captured.out
    assert "two" in captured.out
    assert "three" in captured.out


def test_foreach_nested(capsys: pytest.CaptureFixture[str]) -> None:
    """Test nested foreach loops."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="foreach", args=["i", "a", "b"], line=1),
        Command(name="foreach", args=["j", "1", "2"], line=2),
        Command(name="message", args=["STATUS", "${i}${j}"], line=3),
        Command(name="endforeach", args=[], line=4),
        Command(name="endforeach", args=[], line=5),
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert "a1" in captured.out
    assert "a2" in captured.out
    assert "b1" in captured.out
    assert "b2" in captured.out


def test_foreach_set_variable() -> None:
    """Test that foreach can set variables that persist after the loop."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["RESULT", ""], line=1),
        Command(name="foreach", args=["item", "a", "b", "c"], line=2),
        Command(name="set", args=["RESULT", "${RESULT}${item}"], line=3),
        Command(name="endforeach", args=[], line=4),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["RESULT"] == "abc"
