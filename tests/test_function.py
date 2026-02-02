"""Tests for function() command."""

from pathlib import Path

import pytest

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


def test_function_basic() -> None:
    """Test basic function definition and call."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="function", args=["my_func", "ARG1"], line=1),
        Command(name="set", args=["RESULT", "${ARG1}_processed"], line=2),
        Command(name="endfunction", args=[], line=3),
        Command(name="my_func", args=["hello"], line=4),
    ]
    process_commands(commands, ctx)

    # Function should be defined
    assert "my_func" in ctx.functions


def test_function_with_argc_argv() -> None:
    """Test function with ARGC and ARGV variables."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="function", args=["test_func"], line=1),
        Command(name="set", args=["COUNT", "${ARGC}", "PARENT_SCOPE"], line=2),
        Command(name="set", args=["ALL_ARGS", "${ARGV}", "PARENT_SCOPE"], line=3),
        Command(name="endfunction", args=[], line=4),
        Command(name="test_func", args=["a", "b", "c"], line=5),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["COUNT"] == "3"
    assert ctx.variables["ALL_ARGS"] == "a;b;c"


def test_function_argn() -> None:
    """Test function ARGN for extra arguments."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="function", args=["my_func", "FIRST"], line=1),
        Command(name="set", args=["EXTRA", "${ARGN}", "PARENT_SCOPE"], line=2),
        Command(name="endfunction", args=[], line=3),
        Command(name="my_func", args=["one", "two", "three"], line=4),
    ]
    process_commands(commands, ctx)

    # ARGN should contain arguments after FIRST
    assert ctx.variables["EXTRA"] == "two;three"


def test_function_case_insensitive() -> None:
    """Test that function names are case-insensitive."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="function", args=["MyFunc"], line=1),
        Command(name="set", args=["CALLED", "yes", "PARENT_SCOPE"], line=2),
        Command(name="endfunction", args=[], line=3),
        Command(name="MYFUNC", args=[], line=4),  # Call with different case
    ]
    process_commands(commands, ctx)

    assert ctx.variables["CALLED"] == "yes"


def test_function_scope() -> None:
    """Test that function has its own variable scope."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["OUTER"] = "original"
    commands = [
        Command(name="function", args=["scope_test"], line=1),
        Command(
            name="set", args=["OUTER", "modified"], line=2
        ),  # Should not affect outer
        Command(name="set", args=["INNER", "value"], line=3),  # Should not leak out
        Command(name="endfunction", args=[], line=4),
        Command(name="scope_test", args=[], line=5),
    ]
    process_commands(commands, ctx)

    # OUTER should be unchanged, INNER should not exist
    assert ctx.variables["OUTER"] == "original"
    assert "INNER" not in ctx.variables


def test_function_parent_scope() -> None:
    """Test PARENT_SCOPE to set variables in caller's scope."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="function", args=["setter", "NAME", "VALUE"], line=1),
        Command(name="set", args=["${NAME}", "${VALUE}", "PARENT_SCOPE"], line=2),
        Command(name="endfunction", args=[], line=3),
        Command(name="setter", args=["MY_VAR", "my_value"], line=4),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["MY_VAR"] == "my_value"


def test_function_argv_indexed() -> None:
    """Test ARGV0, ARGV1, etc. variables."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="function", args=["indexed_test"], line=1),
        Command(name="set", args=["FIRST", "${ARGV0}", "PARENT_SCOPE"], line=2),
        Command(name="set", args=["SECOND", "${ARGV1}", "PARENT_SCOPE"], line=3),
        Command(name="endfunction", args=[], line=4),
        Command(name="indexed_test", args=["alpha", "beta"], line=5),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["FIRST"] == "alpha"
    assert ctx.variables["SECOND"] == "beta"


def test_function_error_uses_defining_file(capsys: pytest.CaptureFixture[str]) -> None:
    """Errors inside functions should report the function's defining file."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.current_list_file = Path("defs/CMakeLists.txt")
    commands = [
        Command(name="function", args=["bad_func"], line=1),
        Command(name="not_a_command", args=[], line=2),
        Command(name="endfunction", args=[], line=3),
    ]
    process_commands(commands, ctx)

    ctx.current_list_file = Path("caller/CMakeLists.txt")
    with pytest.raises(SystemExit):
        process_commands([Command(name="bad_func", args=[], line=10)], ctx, strict=True)

    err = capsys.readouterr().err
    assert "defs/CMakeLists.txt:2:" in err
    assert "caller/CMakeLists.txt" not in err
