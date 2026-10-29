"""Tests for string() command."""

import re
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


def _run_json(*args: str) -> BuildContext:
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="string", args=["JSON", *args], line=1)]
    process_commands(commands, ctx, strict=True)
    return ctx


_JSON_DOC = '{"name": "cja", "version": 1.0, "flag": true, "nil": null, "deps": ["a", {"b": 2}], "opts": {"z": 1, "a": []}}'


def test_string_json_get() -> None:
    """string(JSON GET) should convert scalars and serialize containers like CMake."""
    assert _run_json("R", "GET", _JSON_DOC, "name").variables["R"] == "cja"
    assert _run_json("R", "GET", _JSON_DOC, "version").variables["R"] == "1.0"
    assert _run_json("R", "GET", _JSON_DOC, "flag").variables["R"] == "ON"
    assert _run_json("R", "GET", _JSON_DOC, "nil").variables["R"] == ""
    assert _run_json("R", "GET", _JSON_DOC, "deps", "1", "b").variables["R"] == "2"
    assert (
        _run_json("R", "GET", _JSON_DOC, "deps").variables["R"]
        == '[\n  "a",\n  {\n    "b" : 2\n  }\n]'
    )
    assert (
        _run_json("R", "GET", _JSON_DOC, "opts").variables["R"]
        == '{\n  "a" : [],\n  "z" : 1\n}'
    )


def test_string_json_get_raw_and_string_encode() -> None:
    """GET_RAW keeps JSON syntax, STRING_ENCODE quotes a plain string."""
    assert _run_json("R", "GET_RAW", _JSON_DOC, "name").variables["R"] == '"cja"'
    assert _run_json("R", "GET_RAW", _JSON_DOC, "nil").variables["R"] == "null"
    assert (
        _run_json("R", "STRING_ENCODE", 'a"b\né').variables["R"]
        == '"a\\"b\\n\\u00e9"'
    )


def test_string_json_type_member_length() -> None:
    """TYPE, MEMBER and LENGTH should inspect elements; members are sorted."""
    assert _run_json("R", "TYPE", _JSON_DOC, "flag").variables["R"] == "BOOLEAN"
    assert _run_json("R", "TYPE", _JSON_DOC, "deps").variables["R"] == "ARRAY"
    assert _run_json("R", "MEMBER", _JSON_DOC, "opts", "0").variables["R"] == "a"
    assert _run_json("R", "LENGTH", _JSON_DOC, "deps").variables["R"] == "2"


def test_string_json_set_remove_equal() -> None:
    """SET, REMOVE and EQUAL should modify and compare JSON documents."""
    assert (
        _run_json("R", "SET", '{"a": [1]}', "a", "5", '"x"').variables["R"]
        == '{\n  "a" : [ 1, "x" ]\n}'
    )
    assert _run_json("R", "REMOVE", '{"a": 1, "b": 2}', "a").variables["R"] == (
        '{\n  "b" : 2\n}'
    )
    assert _run_json("R", "EQUAL", '{"a":1,"b":2}', '{"b":2, "a":1}').variables[
        "R"
    ] == "ON"
    assert _run_json("R", "EQUAL", "1", "1.0").variables["R"] == "OFF"


def test_string_json_allows_comments() -> None:
    """jsoncpp accepts comments, so CMake projects may rely on them."""
    doc = '{"a": "// not a comment", // comment\n "b": /* x */ 2}'
    assert _run_json("R", "GET", doc, "a").variables["R"] == "// not a comment"
    assert _run_json("R", "GET", doc, "b").variables["R"] == "2"


def test_string_json_error_variable() -> None:
    """Errors go to ERROR_VARIABLE and <out-var> gets the path up to the failure."""
    ctx = _run_json("R", "ERROR_VARIABLE", "E", "GET", _JSON_DOC, "name")
    assert ctx.variables["E"] == "NOTFOUND"
    ctx = _run_json("R", "ERROR_VARIABLE", "E", "GET", _JSON_DOC, "deps", "5")
    assert ctx.variables["R"] == "deps-5-NOTFOUND"
    assert ctx.variables["E"] == "expected an index less than 2 got '5'"
    ctx = _run_json("R", "ERROR_VARIABLE", "E", "GET", "{bad")
    assert ctx.variables["R"] == "NOTFOUND"
    assert ctx.variables["E"].startswith("failed parsing json string:")


def test_string_json_error_is_fatal_without_error_variable(capsys) -> None:
    """Without ERROR_VARIABLE a JSON error should stop configuration."""
    import pytest

    with pytest.raises(SystemExit):
        _run_json("R", "GET", _JSON_DOC, "missing")
    assert "string sub-command JSON member 'missing' not found." in capsys.readouterr().err
