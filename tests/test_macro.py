"""Tests for macro command."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command, parse


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


def test_macro_leaves_special_vars() -> None:
    """Test that the special variables of the caller are as before after a macro call."""
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
    # After macro, ARGC should still be the original
    assert ctx.variables["OUTSIDE_ARGC"] == "99"


def _run(code: str) -> BuildContext:
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(parse(code), ctx)
    return ctx


def test_macro_parameters_are_not_variables() -> None:
    """Like in CMake, the parameters are replaced as text and aren't defined."""
    ctx = _run(
        """
function(callee)
  set(CALLEE_SEES "[${arg}]" PARENT_SCOPE)
endfunction()
macro(my_macro arg)
  if(DEFINED arg OR DEFINED ARGN OR DEFINED ARGV OR DEFINED ARGC OR DEFINED ARGV0)
    set(IS_DEFINED TRUE)
  endif()
  if(arg)
    set(NAME_IS_TRUE TRUE)
  endif()
  if(${arg})
    set(REFERENCE_IS_TRUE TRUE)
  endif()
  list(LENGTH ARGN ARGN_LENGTH)
  callee()
endmacro()
my_macro(ON more)
"""
    )
    assert "IS_DEFINED" not in ctx.variables
    assert "NAME_IS_TRUE" not in ctx.variables
    assert ctx.variables["REFERENCE_IS_TRUE"] == "TRUE"
    assert ctx.variables["ARGN_LENGTH"] == "0"
    assert ctx.variables["CALLEE_SEES"] == "[]"


def test_macro_sets_variable_named_like_parameter() -> None:
    """Such a variable is neither what a reference to the parameter stands
    for, nor is it gone after the call."""
    ctx = _run(
        """
set(other outer)
macro(my_macro arg other)
  set(arg changed)
  set(INSIDE "${arg} ${other}")
endmacro()
my_macro(original inner)
"""
    )
    assert ctx.variables["INSIDE"] == "original inner"
    assert ctx.variables["arg"] == "changed"
    assert ctx.variables["other"] == "outer"


def test_macro_evaluates_argument_values() -> None:
    """The variable references and escape sequences that the value of an
    argument has are evaluated in the body, unlike in a function."""
    ctx = _run(
        r"""
set(y value)
function(my_function arg)
  set(IN_FUNCTION "${arg}" PARENT_SCOPE)
endfunction()
macro(my_macro arg)
  set(QUOTED "${arg}")
  set(UNQUOTED ${arg})
  set(BRACKET [[${arg}]])
endmacro()
my_function("\${y} a\\\\b \\\${y}")
my_macro("\${y} a\\\\b \\\${y}")
"""
    )
    assert ctx.variables["IN_FUNCTION"] == r"${y} a\\b \${y}"
    assert ctx.variables["QUOTED"] == r"value a\b ${y}"
    assert ctx.variables["UNQUOTED"] == ctx.variables["QUOTED"]
    assert ctx.variables["BRACKET"] == "${arg}"


def test_macro_in_function_keeps_function_arguments() -> None:
    """ARGN and so on are the variables of the function, while references to
    them are replaced with the arguments of the macro where it has some."""
    ctx = _run(
        """
macro(my_macro)
  set(items)
  foreach(item IN LISTS ARGN)
    list(APPEND items "${item}")
  endforeach()
  set(RESULT "${ARGC}|${ARGN}|${ARGV0}|${ARGV2}|${items}" PARENT_SCOPE)
endmacro()
function(my_function)
  my_macro(x y)
endfunction()
my_function(a b c)
"""
    )
    assert ctx.variables["RESULT"] == "2|x;y|x|c|a;b;c"


def test_macro_replaces_references_in_nested_definition() -> None:
    """A function defined in a macro has the arguments of that call in its body."""
    ctx = _run(
        """
macro(define arg)
  function(defined)
    set(RESULT "${arg}|${ARGN}" PARENT_SCOPE)
  endfunction()
endmacro()
define(captured more)
defined(called)
"""
    )
    assert ctx.variables["RESULT"] == "captured|more"


def test_macro_replaces_in_order() -> None:
    """Like in CMake, what a parameter is replaced with can have a reference
    to ARGN and so on, which are replaced afterwards."""
    ctx = _run(
        r"""
macro(my_macro arg)
  set(RESULT "${arg}")
endmacro()
my_macro("\${ARGN}|\${ARGC}" tail)
"""
    )
    assert ctx.variables["RESULT"] == "tail|2"


def test_macro_drops_empty_unquoted_argument() -> None:
    ctx = _run(
        """
macro(my_macro arg)
  set(UNQUOTED a ${arg} b)
  set(QUOTED a "${arg}" b)
endmacro()
my_macro("")
"""
    )
    assert ctx.variables["UNQUOTED"] == "a;b"
    assert ctx.variables["QUOTED"] == "a;;b"


def test_macro_too_few_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    """Like in CMake, the macro isn't called then, which is an error."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    code = """
macro(MyMacro a b)
  set(RESULT "[${a}] [${b}]")
endmacro()
mymacro(only)
"""
    with pytest.raises(SystemExit) as exc_info:
        process_commands(parse(code), ctx)
    assert exc_info.value.code == 1
    assert capsys.readouterr().err == (
        "CMakeLists.txt:5: error: Macro invoked with incorrect arguments for macro"
        " named: mymacro\n"
    )
    assert "RESULT" not in ctx.variables


def test_macro_invalid_escape_in_argument(capsys: pytest.CaptureFixture[str]) -> None:
    """Like in CMake, a backslash in the value of an argument that starts no
    escape sequence is an error, once a command with it is evaluated."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    code = r"""
macro(not_evaluated arg)
  if(FALSE)
    set(NEVER "${arg}")
  endif()
endmacro()
macro(evaluated arg)
  set(RESULT "${arg}")
endmacro()
not_evaluated("C:\\dir")
set(REACHED TRUE)
evaluated("C:\\dir")
"""
    with pytest.raises(SystemExit) as exc_info:
        process_commands(parse(code), ctx)
    assert exc_info.value.code == 1
    assert capsys.readouterr().err == (
        "CMakeLists.txt:8: error: Invalid character escape '\\d'.\n"
    )
    assert ctx.variables["REACHED"] == "TRUE"
    assert "RESULT" not in ctx.variables
