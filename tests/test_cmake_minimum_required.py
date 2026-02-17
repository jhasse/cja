"""Tests for cmake_minimum_required()."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command, parse


def test_cmake_minimum_required_sets_minimum_version() -> None:
    """cmake_minimum_required(VERSION x.y) sets CMAKE_MINIMUM_REQUIRED_VERSION."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="cmake_minimum_required", args=["VERSION", "3.22"], line=1),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["CMAKE_MINIMUM_REQUIRED_VERSION"] == "3.22"


def test_cmake_minimum_required_handles_version_range() -> None:
    """cmake_minimum_required(VERSION x...y) stores the minimum end of the range."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="cmake_minimum_required", args=["VERSION", "3.22...3.31"], line=1),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["CMAKE_MINIMUM_REQUIRED_VERSION"] == "3.22"


def test_cmake_minimum_required_missing_version_in_strict_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Missing VERSION is an error in strict mode."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="cmake_minimum_required", args=["FATAL_ERROR"], line=1),
    ]
    with pytest.raises(SystemExit) as exc_info:
        process_commands(commands, ctx, strict=True)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "cmake_minimum_required missing VERSION argument" in captured.err


def test_parse_bom_prefixed_cmake_minimum_required() -> None:
    """A UTF-8 BOM must not become part of the first command name."""
    commands = parse("\ufeffcmake_minimum_required(VERSION 3.22)")
    assert len(commands) == 1
    assert commands[0].name == "cmake_minimum_required"
    assert commands[0].args == ["VERSION", "3.22"]
