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
        "    \"foo \\\n"
        "bar\"\n"
        ")\n"
        "message(FATAL_ERROR \"Line number should be 5\")\n"
    )
    commands = parse(content)
    assert len(commands) == 2
    assert commands[1].line == 5
