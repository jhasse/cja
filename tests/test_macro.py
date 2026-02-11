"""Tests for macro command."""

from pathlib import Path

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_macro_basic() -> None:
    """Test basic macro definition and call."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="macro", args=["my_macro"], line=1),
        Command(name="set", args=["MY_VAR", "hello"], line=2),
        Command(name="endmacro", args=[], line=3),
        Command(name="my_macro", args=[], line=4),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["MY_VAR"] == "hello"


def test_macro_with_parameters() -> None:
    """Test macro with parameters."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="macro", args=["my_macro", "arg1", "arg2"], line=1),
        Command(name="set", args=["RESULT", "${arg1}_${arg2}"], line=2),
        Command(name="endmacro", args=[], line=3),
        Command(name="my_macro", args=["foo", "bar"], line=4),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "foo_bar"


def test_macro_scope_difference() -> None:
    """Test that macros operate in caller's scope (unlike functions)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["MY_VAR", "original"], line=1),
        Command(name="macro", args=["change_var"], line=2),
        Command(name="set", args=["MY_VAR", "changed"], line=3),
        Command(name="endmacro", args=[], line=4),
        Command(name="change_var", args=[], line=5),
    ]
    process_commands(commands, ctx)
    # Variable should be changed because macros operate in caller's scope
    assert ctx.variables["MY_VAR"] == "changed"


def test_macro_vs_function_scope() -> None:
    """Test that macros don't create new scope while functions do."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["MY_VAR", "original"], line=1),
        # Macro that changes variable
        Command(name="macro", args=["macro_change"], line=2),
        Command(name="set", args=["MY_VAR", "macro_changed"], line=3),
        Command(name="endmacro", args=[], line=4),
        # Function that changes variable
        Command(name="function", args=["func_change"], line=5),
        Command(name="set", args=["MY_VAR", "func_changed"], line=6),
        Command(name="endfunction", args=[], line=7),
        # Call macro
        Command(name="macro_change", args=[], line=8),
        Command(name="set", args=["AFTER_MACRO", "${MY_VAR}"], line=9),
        # Reset and call function
        Command(name="set", args=["MY_VAR", "original"], line=10),
        Command(name="func_change", args=[], line=11),
        Command(name="set", args=["AFTER_FUNC", "${MY_VAR}"], line=12),
    ]
    process_commands(commands, ctx)
    # After macro, variable should be changed
    assert ctx.variables["AFTER_MACRO"] == "macro_changed"
    # After function, variable should remain original
    assert ctx.variables["AFTER_FUNC"] == "original"


def test_macro_argn() -> None:
    """Test ARGN in macros."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="macro", args=["my_macro", "first"], line=1),
        Command(name="set", args=["FIRST_ARG", "${first}"], line=2),
        Command(name="set", args=["REST_ARGS", "${ARGN}"], line=3),
        Command(name="endmacro", args=[], line=4),
        Command(name="my_macro", args=["a", "b", "c", "d"], line=5),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["FIRST_ARG"] == "a"
    assert ctx.variables["REST_ARGS"] == "b;c;d"


def test_macro_argc_argv() -> None:
    """Test ARGC and ARGV in macros."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="macro", args=["my_macro"], line=1),
        Command(name="set", args=["ARG_COUNT", "${ARGC}"], line=2),
        Command(name="set", args=["ALL_ARGS", "${ARGV}"], line=3),
        Command(name="set", args=["ARG0", "${ARGV0}"], line=4),
        Command(name="set", args=["ARG1", "${ARGV1}"], line=5),
        Command(name="endmacro", args=[], line=6),
        Command(name="my_macro", args=["foo", "bar"], line=7),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["ARG_COUNT"] == "2"
    assert ctx.variables["ALL_ARGS"] == "foo;bar"
    assert ctx.variables["ARG0"] == "foo"
    assert ctx.variables["ARG1"] == "bar"


def test_macro_nested_calls() -> None:
    """Test nested macro calls."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="macro", args=["inner"], line=1),
        Command(name="set", args=["INNER", "called"], line=2),
        Command(name="endmacro", args=[], line=3),
        Command(name="macro", args=["outer"], line=4),
        Command(name="set", args=["OUTER", "called"], line=5),
        Command(name="inner", args=[], line=6),
        Command(name="endmacro", args=[], line=7),
        Command(name="outer", args=[], line=8),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["OUTER"] == "called"
    assert ctx.variables["INNER"] == "called"


def test_macro_with_conditionals() -> None:
    """Test macro with conditionals."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="macro", args=["conditional_macro", "value"], line=1),
        Command(name="if", args=["${value}", "STREQUAL", "true"], line=2),
        Command(name="set", args=["RESULT", "yes"], line=3),
        Command(name="else", args=[], line=4),
        Command(name="set", args=["RESULT", "no"], line=5),
        Command(name="endif", args=[], line=6),
        Command(name="endmacro", args=[], line=7),
        Command(name="conditional_macro", args=["true"], line=8),
        Command(name="set", args=["RESULT1", "${RESULT}"], line=9),
        Command(name="conditional_macro", args=["false"], line=10),
        Command(name="set", args=["RESULT2", "${RESULT}"], line=11),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT1"] == "yes"
    assert ctx.variables["RESULT2"] == "no"


def test_macro_with_foreach() -> None:
    """Test macro with foreach loop."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="macro", args=["append_all"], line=1),
        Command(name="set", args=["RESULT", ""], line=2),
        Command(name="foreach", args=["item", "${ARGN}"], line=3),
        Command(name="set", args=["RESULT", "${RESULT}${item}"], line=4),
        Command(name="endforeach", args=[], line=5),
        Command(name="endmacro", args=[], line=6),
        Command(name="append_all", args=["a", "b", "c"], line=7),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "abc"


def test_macro_case_insensitive() -> None:
    """Test that macro names are case-insensitive."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="macro", args=["MyMacro"], line=1),
        Command(name="set", args=["CALLED", "yes"], line=2),
        Command(name="endmacro", args=[], line=3),
        Command(name="mymacro", args=[], line=4),  # lowercase call
    ]
    process_commands(commands, ctx)
    assert ctx.variables["CALLED"] == "yes"


def test_macro_modifies_list() -> None:
    """Test that macro can modify lists in caller's scope."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["MY_LIST", "a;b;c"], line=1),
        Command(name="macro", args=["add_to_list", "item"], line=2),
        Command(name="list", args=["APPEND", "MY_LIST", "${item}"], line=3),
        Command(name="endmacro", args=[], line=4),
        Command(name="add_to_list", args=["d"], line=5),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "a;b;c;d"


def test_macro_multiple_parameters() -> None:
    """Test macro with multiple parameters."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="macro", args=["add_three", "a", "b", "c"], line=1),
        Command(name="math", args=["EXPR", "RESULT", "${a} + ${b} + ${c}"], line=2),
        Command(name="endmacro", args=[], line=3),
        Command(name="add_three", args=["1", "2", "3"], line=4),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "6"


def test_macro_empty_parameters() -> None:
    """Test macro called with fewer arguments than parameters."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="macro", args=["my_macro", "arg1", "arg2"], line=1),
        Command(name="set", args=["ARG1_VAL", "${arg1}"], line=2),
        Command(name="set", args=["ARG2_VAL", "${arg2}"], line=3),
        Command(name="endmacro", args=[], line=4),
        Command(name="my_macro", args=["only_one"], line=5),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["ARG1_VAL"] == "only_one"
    assert ctx.variables["ARG2_VAL"] == ""


def test_macro_restores_special_vars() -> None:
    """Test that special variables are restored after macro call."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    # Set up initial ARGC/ARGV
    ctx.variables["ARGC"] = "99"
    ctx.variables["ARGV"] = "original"
    ctx.variables["ARGV0"] = "orig0"

    commands = [
        Command(name="macro", args=["my_macro"], line=1),
        Command(name="set", args=["INSIDE_ARGC", "${ARGC}"], line=2),
        Command(name="endmacro", args=[], line=3),
        Command(name="my_macro", args=["a", "b"], line=4),
        Command(name="set", args=["OUTSIDE_ARGC", "${ARGC}"], line=5),
    ]
    process_commands(commands, ctx)

    # Inside macro, ARGC should be 2
    assert ctx.variables["INSIDE_ARGC"] == "2"
    # After macro, ARGC should be restored to original
    assert ctx.variables["OUTSIDE_ARGC"] == "99"
