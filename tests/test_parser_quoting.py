"""Test CMake-like argument parsing."""

from pathlib import Path

from cja.parser import parse
from cja.parser import parse_file


def test_mixed_quoting() -> None:
    content = 'message(STATUS FOO="BAR")'
    commands = parse(content)
    assert len(commands) == 1
    assert commands[0].args == ["STATUS", 'FOO="BAR"']


def test_complex_mixed_quoting() -> None:
    content = 'message(STATUS PRE"MID"POST)'
    commands = parse(content)
    assert len(commands) == 1
    assert commands[0].args == ["STATUS", 'PRE"MID"POST']


def test_line_numbers_after_escaped_newline() -> None:
    content = (
        "message(STATUS\n"
        '    "foo \\\n'
        'bar"\n'
        ")\n"
        'message(FATAL_ERROR "Line number should be 5")\n'
    )
    commands = parse(content)
    assert len(commands) == 2
    assert commands[1].line == 5


def test_escaped_variable_marker_in_quoted_string() -> None:
    content = 'set(X "\\${exec_prefix}")'
    commands = parse(content)
    assert len(commands) == 1
    assert commands[0].args == ["X", r"\${exec_prefix}"]


def test_genex_with_spaces_is_single_argument() -> None:
    content = (
        "target_compile_options(foo PRIVATE "
        "$<$<CXX_COMPILER_ID:MSVC>:/W3 /wd4127 /wd4355>)"
    )
    commands = parse(content)
    assert len(commands) == 1
    assert commands[0].args == [
        "foo",
        "PRIVATE",
        "$<$<CXX_COMPILER_ID:MSVC>:/W3 /wd4127 /wd4355>",
    ]


def test_parse_file_latin1_fallback(tmp_path: Path) -> None:
    cmake = tmp_path / "CMakeLists.txt"
    cmake.write_bytes(b'message(STATUS "ok")\n# Python\x92s os.path.join\n')
    commands = parse_file(cmake)
    assert len(commands) == 1
    assert commands[0].name == "message"


def test_bracket_argument() -> None:
    content = "set(FOO [=[hello world]=])"
    commands = parse(content)
    assert len(commands) == 1
    assert commands[0].args == ["FOO", "hello world"]


def test_bracket_argument_with_special_chars() -> None:
    content = 'set(PATTERN [=["?[A-Za-z_0-9.-]+"?]=])'
    commands = parse(content)
    assert len(commands) == 1
    assert commands[0].args == ["PATTERN", '"?[A-Za-z_0-9.-]+"?']


def test_bracket_argument_no_equals() -> None:
    content = "set(FOO [[bar]])"
    commands = parse(content)
    assert len(commands) == 1
    assert commands[0].args == ["FOO", "bar"]
