"""Tests for function() command."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


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


def test_cmake_parse_arguments() -> None:
    """Test basic cmake_parse_arguments behavior."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="cmake_parse_arguments",
            args=[
                "MY",
                "QUIET;REQUIRED",
                "MODE",
                "SOURCES;DEPS",
                "QUIET",
                "MODE",
                "FAST",
                "SOURCES",
                "a.cpp",
                "b.cpp",
                "EXTRA",
                "DEPS",
                "x",
                "y",
            ],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["MY_QUIET"] == "TRUE"
    assert ctx.variables["MY_REQUIRED"] == "FALSE"
    assert ctx.variables["MY_MODE"] == "FAST"
    assert ctx.variables["MY_SOURCES"] == "a.cpp;b.cpp;EXTRA"
    assert ctx.variables["MY_DEPS"] == "x;y"
    assert ctx.variables["MY_UNPARSED_ARGUMENTS"] == ""
    assert ctx.variables["MY_KEYWORDS_MISSING_VALUES"] == ""


def test_cmake_parse_arguments_unparsed_and_missing() -> None:
    """Test unparsed args and missing values handling."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="cmake_parse_arguments",
            args=[
                "ARG",
                "QUIET",
                "MODE",
                "SOURCES",
                "EXTRA1",
                "QUIET",
                "MODE",
                "SOURCES",
                "a.cpp",
                "EXTRA2",
            ],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    # EXTRA1 comes before any keyword and should be unparsed.
    assert ctx.variables["ARG_UNPARSED_ARGUMENTS"] == "EXTRA1"
    # MODE is a one-value keyword but has no value (next token is keyword).
    assert ctx.variables["ARG_KEYWORDS_MISSING_VALUES"] == "MODE"
    # SOURCES collects until next keyword; EXTRA2 is part of SOURCES.
    assert ctx.variables["ARG_SOURCES"] == "a.cpp;EXTRA2"


def test_cmake_parse_arguments_missing_options_list() -> None:
    """Test cmake_parse_arguments with omitted options list (CPM.cmake style)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="cmake_parse_arguments",
            args=[
                "CPM_ARGS",
                "NAME;FORCE;VERSION",
                "URL;OPTIONS",
                "NAME",
                "libogg",
                "URL",
                "http://example.com/libogg.tar.gz",
            ],
            line=1,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["CPM_ARGS_NAME"] == "libogg"
    assert ctx.variables["CPM_ARGS_URL"] == "http://example.com/libogg.tar.gz"


def test_unset_parent_scope() -> None:
    """Test unset(PARENT_SCOPE) clears variable in caller."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["OUTER"] = "keep"
    commands = [
        Command(name="function", args=["do_unset"], line=1),
        Command(name="unset", args=["OUTER", "PARENT_SCOPE"], line=2),
        Command(name="endfunction", args=[], line=3),
        Command(name="do_unset", args=[], line=4),
    ]
    process_commands(commands, ctx)

    assert "OUTER" not in ctx.variables


def test_enable_language_objcxx_noop() -> None:
    """enable_language(OBJCXX) should be a no-op."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="enable_language", args=["OBJCXX"], line=1)]
    process_commands(commands, ctx)

    assert "CMAKE_OBJCXX_FLAGS" not in ctx.variables


def test_include_directories_applies_to_targets() -> None:
    """include_directories should apply to targets in the directory."""
    source_dir = Path(".").resolve() / "root"
    ctx = BuildContext(source_dir=source_dir, build_dir=Path("build"))
    commands = [
        Command(name="include_directories", args=["include"], line=1),
        Command(name="add_executable", args=["app", "main.c"], line=2),
    ]
    process_commands(commands, ctx)

    assert ctx.executables
    expected_dir = source_dir / "include"
    assert ctx.executables[0].include_directories == [str(expected_dir)]


def test_source_group_noop() -> None:
    """source_group should be a no-op."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="source_group",
            args=["Source Files", "FILES", "a.cpp", "b.cpp"],
            line=1,
        )
    ]
    process_commands(commands, ctx)


def test_undefined_variable_in_if_strequale_empty(capsys: pytest.CaptureFixture[str]) -> None:
    """Undefined variable in if ("${VAR}" STREQUAL "") should not warn."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="if", args=["${UNDEF}", "STREQUAL", ""], line=1),
        Command(name="set", args=["HIT", "yes"], line=2),
        Command(name="endif", args=[], line=3),
    ]
    process_commands(commands, ctx)

    err = capsys.readouterr().err
    assert err == ""
    assert ctx.variables["HIT"] == "yes"


def test_undefined_variable_in_if_not_strequale_empty(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Undefined variable in if (NOT "${VAR}" STREQUAL "") should not warn."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="if", args=["NOT", "${UNDEF}", "STREQUAL", ""], line=1),
        Command(name="set", args=["HIT", "yes"], line=2),
        Command(name="endif", args=[], line=3),
    ]
    process_commands(commands, ctx)

    err = capsys.readouterr().err
    assert err == ""
    assert "HIT" not in ctx.variables


def test_undefined_variable_in_if_not_and_flags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Undefined variable in mixed NOT/AND STREQUAL check should not warn."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["MY_FLAG", "OFF"], line=1),
        Command(
            name="if",
            args=["NOT", "MY_FLAG", "AND", "NOT", "${UNDEF}", "STREQUAL", ""],
            line=2,
        ),
        Command(name="set", args=["HIT", "yes"], line=3),
        Command(name="endif", args=[], line=4),
    ]
    process_commands(commands, ctx)

    err = capsys.readouterr().err
    assert err == ""
    assert "HIT" not in ctx.variables


def test_undefined_variable_in_if_strequale_empty_nested_expansion(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Undefined variable with nested expansion in if should not warn."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["FOO", "defin"], line=1),
        Command(
            name="if",
            args=["${un${FOO}ed}", "STREQUAL", ""],
            line=2,
        ),
        Command(name="set", args=["HIT", "yes"], line=3),
        Command(name="endif", args=[], line=4),
    ]
    process_commands(commands, ctx)

    err = capsys.readouterr().err
    assert err == ""
    assert ctx.variables["HIT"] == "yes"
