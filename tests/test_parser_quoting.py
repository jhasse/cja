"""Test CMake-like argument parsing."""

from cninja.parser import parse


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
