"""Tests for string() command."""

from pathlib import Path

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
