"""Test CMake-like argument parsing."""

from cja.parser import parse


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
