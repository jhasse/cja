"""Tests for string() command."""

from pathlib import Path
import re

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_string_regex_match_sets_cmake_match_count() -> None:
    """string(REGEX MATCH) should set CMAKE_MATCH_COUNT and captures."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="string",
            args=[
                "REGEX",
                "MATCH",
                "SPDLOG_VER_MAJOR ([0-9]+)",
                "_",
                "SPDLOG_VER_MAJOR 1",
            ],
            line=1,
        ),
        Command(name="if", args=["NOT", "CMAKE_MATCH_COUNT", "EQUAL", "1"], line=2),
        Command(name="set", args=["BAD", "1"], line=3),
        Command(name="endif", args=[], line=4),
    ]
    process_commands(commands, ctx, strict=True)

    assert "BAD" not in ctx.variables
    assert ctx.variables["CMAKE_MATCH_COUNT"] == "1"
    assert ctx.variables["CMAKE_MATCH_1"] == "1"


def test_string_regex_match_clears_previous_match_vars() -> None:
    """A failed REGEX MATCH should clear previous CMAKE_MATCH_* captures."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="string", args=["REGEX", "MATCH", "(a)", "_", "a"], line=1),
        Command(name="string", args=["REGEX", "MATCH", "(b)", "_", "x"], line=2),
    ]
    process_commands(commands, ctx, strict=True)

    assert ctx.variables["CMAKE_MATCH_COUNT"] == "0"
    assert ctx.variables["CMAKE_MATCH_0"] == ""
    assert ctx.variables.get("CMAKE_MATCH_1", "") == ""


def test_string_make_c_identifier() -> None:
    """string(MAKE_C_IDENTIFIER) should convert to a valid C identifier."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="string",
            args=["MAKE_C_IDENTIFIER", "my-flag-name", "result"],
            line=1,
        ),
    ]
    process_commands(commands, ctx, strict=True)
    assert ctx.variables["result"] == "my_flag_name"


def test_string_make_c_identifier_leading_digit() -> None:
    """string(MAKE_C_IDENTIFIER) should prepend underscore for leading digit."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="string",
            args=["MAKE_C_IDENTIFIER", "2bad", "result"],
            line=1,
        ),
    ]
    process_commands(commands, ctx, strict=True)
    assert ctx.variables["result"] == "_2bad"


def test_string_find_returns_index() -> None:
    """string(FIND) should return the first match position."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="string",
            args=["FIND", "libsharpyuv_la_SOURCES += sharpyuv.c", "=", "offset"],
            line=1,
        ),
    ]
    process_commands(commands, ctx, strict=True)
    assert ctx.variables["offset"] == "24"


def test_string_find_reverse_returns_last_match() -> None:
    """string(FIND ... REVERSE) should return the last match position."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="string",
            args=["FIND", "abc=def=ghi", "=", "offset", "REVERSE"],
            line=1,
        ),
    ]
    process_commands(commands, ctx, strict=True)
    assert ctx.variables["offset"] == "7"


def test_string_timestamp_sets_variable() -> None:
    """string(TIMESTAMP) should set the output variable to a formatted time."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="string", args=["TIMESTAMP", "VERSION", "%Y-%m"], line=1),
    ]
    process_commands(commands, ctx, strict=True)
    assert "VERSION" in ctx.variables
    assert re.fullmatch(r"\d{4}-\d{2}", ctx.variables["VERSION"])


def test_string_timestamp_honors_source_date_epoch(monkeypatch) -> None:
    """SOURCE_DATE_EPOCH should make string(TIMESTAMP) reproducible."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1234567890")
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="string",
            args=["TIMESTAMP", "TS", "%Y-%m-%dT%H:%M:%S", "UTC"],
            line=1,
        ),
    ]
    process_commands(commands, ctx, strict=True)
    assert ctx.variables["TS"] == "2009-02-13T23:31:30"


def test_string_timestamp_default_format(monkeypatch) -> None:
    """string(TIMESTAMP) without a format uses CMake's default."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1234567890")
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="string", args=["TIMESTAMP", "TS"], line=1),
    ]
    process_commands(commands, ctx, strict=True)
    # SOURCE_DATE_EPOCH forces UTC, which appends the trailing Z.
    assert ctx.variables["TS"] == "2009-02-13T23:31:30Z"


def test_string_timestamp_unix_seconds(monkeypatch) -> None:
    """The %s specifier should yield UNIX seconds even though strftime can't."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1234567890")
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="string", args=["TIMESTAMP", "TS", "%s"], line=1),
    ]
    process_commands(commands, ctx, strict=True)
    assert ctx.variables["TS"] == "1234567890"


def test_string_unknown_subcommand_errors_in_strict_mode(capsys) -> None:
    """An unknown string() subcommand should be reported instead of silently ignored."""
    import pytest

    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="string", args=["BOGUS", "x", "out"], line=1),
    ]
    with pytest.raises(SystemExit):
        process_commands(commands, ctx, strict=True)
    captured = capsys.readouterr()
    assert "unknown subcommand: BOGUS" in captured.err
