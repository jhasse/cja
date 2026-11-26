"""Tests for foreach command."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command, parse


def test_foreach_basic(capsys: pytest.CaptureFixture[str]) -> None:
    """Test basic foreach with items."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="foreach", args=["item", "a", "b", "c"], line=1),
        Command(name="message", args=["STATUS", "${item}"], line=2),
        Command(name="endforeach", args=[], line=3),
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert "a" in captured.out
    assert "b" in captured.out
    assert "c" in captured.out


def test_foreach_range_stop(capsys: pytest.CaptureFixture[str]) -> None:
    """Test foreach with RANGE stop."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="foreach", args=["i", "RANGE", "3"], line=1),
        Command(name="message", args=["STATUS", "${i}"], line=2),
        Command(name="endforeach", args=[], line=3),
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert "0" in captured.out
    assert "1" in captured.out
    assert "2" in captured.out
    assert "3" in captured.out


def test_foreach_range_start_stop(capsys: pytest.CaptureFixture[str]) -> None:
    """Test foreach with RANGE start stop."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="foreach", args=["i", "RANGE", "2", "5"], line=1),
        Command(name="message", args=["STATUS", "${i}"], line=2),
        Command(name="endforeach", args=[], line=3),
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert "2" in captured.out
    assert "3" in captured.out
    assert "4" in captured.out
    assert "5" in captured.out


def test_foreach_range_step(capsys: pytest.CaptureFixture[str]) -> None:
    """Test foreach with RANGE start stop step."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="foreach", args=["i", "RANGE", "0", "10", "2"], line=1),
        Command(name="message", args=["STATUS", "${i}"], line=2),
        Command(name="endforeach", args=[], line=3),
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert "0" in captured.out
    assert "2" in captured.out
    assert "4" in captured.out
    assert "6" in captured.out
    assert "8" in captured.out
    assert "10" in captured.out


def test_foreach_in_lists(capsys: pytest.CaptureFixture[str]) -> None:
    """Test foreach IN LISTS."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "x y z"
    commands = [
        Command(name="foreach", args=["item", "IN", "LISTS", "MY_LIST"], line=1),
        Command(name="message", args=["STATUS", "${item}"], line=2),
        Command(name="endforeach", args=[], line=3),
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert "x" in captured.out
    assert "y" in captured.out
    assert "z" in captured.out


def test_foreach_in_lists_semicolon_separated() -> None:
    """foreach(IN LISTS) must split CMake's ";"-separated lists into items."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    # CMake stores lists as ";"-separated values (as produced by set(L a b c)).
    ctx.variables["MY_LIST"] = "x;y;z"
    commands = [
        Command(name="set", args=["RESULT", ""], line=1),
        Command(name="foreach", args=["item", "IN", "LISTS", "MY_LIST"], line=2),
        Command(name="set", args=["RESULT", "${RESULT}${item}-"], line=3),
        Command(name="endforeach", args=[], line=4),
    ]
    process_commands(commands, ctx)

    # Each element is its own iteration; before the fix this was a single
    # iteration with item="x;y;z" producing "x;y;z-".
    assert ctx.variables["RESULT"] == "x-y-z-"


def test_foreach_in_lists_nested_variable() -> None:
    """foreach(IN LISTS) with a per-item variable lookup (as used by SDL's
    CPU detection) must resolve ${prefix_${item}} for each element."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["known"] = "a;b;c"
    ctx.variables["arch_a"] = "XA"
    ctx.variables["arch_b"] = "XB"
    ctx.variables["arch_c"] = "XC"
    commands = [
        Command(name="set", args=["RESULT", ""], line=1),
        Command(name="foreach", args=["k", "IN", "LISTS", "known"], line=2),
        Command(name="set", args=["RESULT", "${RESULT}${arch_${k}}"], line=3),
        Command(name="endforeach", args=[], line=4),
    ]
    process_commands(commands, ctx, strict=True)

    assert ctx.variables["RESULT"] == "XAXBXC"


def test_foreach_in_items(capsys: pytest.CaptureFixture[str]) -> None:
    """Test foreach IN ITEMS."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="foreach", args=["item", "IN", "ITEMS", "one", "two", "three"], line=1
        ),
        Command(name="message", args=["STATUS", "${item}"], line=2),
        Command(name="endforeach", args=[], line=3),
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert "one" in captured.out
    assert "two" in captured.out
    assert "three" in captured.out


def test_foreach_nested(capsys: pytest.CaptureFixture[str]) -> None:
    """Test nested foreach loops."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="foreach", args=["i", "a", "b"], line=1),
        Command(name="foreach", args=["j", "1", "2"], line=2),
        Command(name="message", args=["STATUS", "${i}${j}"], line=3),
        Command(name="endforeach", args=[], line=4),
        Command(name="endforeach", args=[], line=5),
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert "a1" in captured.out
    assert "a2" in captured.out
    assert "b1" in captured.out
    assert "b2" in captured.out


def test_foreach_set_variable() -> None:
    """Test that foreach can set variables that persist after the loop."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["RESULT", ""], line=1),
        Command(name="foreach", args=["item", "a", "b", "c"], line=2),
        Command(name="set", args=["RESULT", "${RESULT}${item}"], line=3),
        Command(name="endforeach", args=[], line=4),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["RESULT"] == "abc"


def test_foreach_break() -> None:
    """Test that break() exits the foreach loop early."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["RESULT", ""], line=1),
        Command(name="foreach", args=["i", "a", "b", "c"], line=2),
        Command(name="if", args=["i", "STREQUAL", "b"], line=3),
        Command(name="break", args=[], line=4),
        Command(name="endif", args=[], line=5),
        Command(name="set", args=["RESULT", "${RESULT}${i}"], line=6),
        Command(name="endforeach", args=[], line=7),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "a"


def test_foreach_continue() -> None:
    """Test that continue() skips the rest of the current iteration."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["RESULT", ""], line=1),
        Command(name="foreach", args=["i", "a", "b", "c"], line=2),
        Command(name="if", args=["i", "STREQUAL", "b"], line=3),
        Command(name="continue", args=[], line=4),
        Command(name="endif", args=[], line=5),
        Command(name="set", args=["RESULT", "${RESULT}${i}"], line=6),
        Command(name="endforeach", args=[], line=7),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "ac"


def test_foreach_unquoted_list_drops_empty_elements() -> None:
    """Like CMake, an unquoted ${list} drops empty elements, e.g. the one after
    a trailing newline that string(REPLACE "\\n" ";") turned into a separator."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["OUTPUT"] = "a;;b;"
    commands = [
        Command(name="set", args=["RESULT", ""], line=1),
        Command(name="foreach", args=["item", "${OUTPUT}"], line=2),
        Command(name="set", args=["RESULT", "${RESULT}[${item}]"], line=3),
        Command(name="endforeach", args=[], line=4),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["RESULT"] == "[a][b]"


def _run(code: str) -> BuildContext:
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(parse(code), ctx, strict=True)
    return ctx


def test_foreach_zip_lists_several_variables() -> None:
    """Each variable gets the element of its list. Like in CMake, it isn't
    defined once its list has ended."""
    ctx = _run(
        r"""
set(A a1 a2 a3)
set(B b1 b2)
set(names x y)
foreach(${names} IN ZIP_LISTS A B)
  if(DEFINED y)
    list(APPEND RESULT "${x}=${y}")
  else()
    list(APPEND RESULT "${x} alone")
  endif()
endforeach()
foreach(u v IN ZIP_LISTS B A)
  if(NOT DEFINED u)
    list(APPEND FIRST_SHORTER "${v}")
  endif()
endforeach()
"""
    )

    assert ctx.variables["RESULT"] == "a1=b1;a2=b2;a3 alone"
    assert ctx.variables["FIRST_SHORTER"] == "a3"


def test_foreach_zip_lists_one_variable() -> None:
    """One variable stands for <var>_0, <var>_1, ..., one for each list."""
    ctx = _run(
        r"""
set(A a1 a2)
set(B b1 b2)
set(EMPTY_ELEMENT "c1;")
foreach(item IN ZIP_LISTS A B EMPTY_ELEMENT NOT_SET)
  list(APPEND RESULT "${item_0}${item_1}[${item_2}][${item_3}]")
  if(DEFINED item OR DEFINED item_3 OR NOT DEFINED item_2)
    set(UNEXPECTED TRUE)
  endif()
endforeach()
foreach(single IN ZIP_LISTS A)
  list(APPEND SINGLE "${single_0}")
endforeach()
foreach(none IN ZIP_LISTS)
  set(UNEXPECTED TRUE)
endforeach()
"""
    )

    assert ctx.variables["RESULT"] == "a1b1[c1][];a2b2[][]"
    assert ctx.variables["SINGLE"] == "a1;a2"
    assert "UNEXPECTED" not in ctx.variables


def test_foreach_zip_lists_elements_and_loop_control() -> None:
    r"""The lists are split like for IN LISTS, with "\;" in an element, and
    break() and continue() work like in other loops."""
    ctx = _run(
        r"""
set(A "s\;t" u v w)
set(B 1 2 3 4)
foreach(element number IN ZIP_LISTS A B)
  if(number EQUAL 2)
    continue()
  endif()
  list(APPEND RESULT "${number}:<${element}>")
  if(number EQUAL 3)
    break()
  endif()
endforeach()
"""
    )

    assert ctx.variables["RESULT"] == "1:<s;t>;3:<v>"


@pytest.mark.parametrize(
    ("loop", "message"),
    [
        ("x y z IN ZIP_LISTS A B", "Expected 3 list variables, but given 2"),
        ("x y IN ZIP_LISTS", "Expected 2 list variables, but given 0"),
        ("x y IN ZIP_LISTS A ITEMS", "ZIP_LISTS can not be used with LISTS or ITEMS"),
        ("x y IN LISTS A", "ITEMS or LISTS require exactly one iteration variable"),
        ("x y IN ITEMS a b", "ITEMS or LISTS require exactly one iteration variable"),
    ],
)
def test_foreach_wrong_number_of_variables(loop: str, message: str) -> None:
    """Like in CMake, several variables are only for as many ZIP_LISTS."""
    code = f"set(A 1 2)\nset(B 3 4)\nforeach({loop})\nendforeach()\n"
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))

    with pytest.raises(SyntaxError, match=message):
        process_commands(parse(code), ctx)


def test_foreach_restores_loop_variables() -> None:
    """Like in CMake (CMP0124), a loop variable is only for the loop: afterwards
    it has the value that it had before, or none."""
    ctx = _run(
        r"""
set(A a1 a2 a3)
set(B b1 b2)
set(was_set before)
foreach(was_set IN LISTS A)
endforeach()
foreach(was_not_set IN LISTS A)
endforeach()
set(cached from_cache CACHE STRING "")
foreach(cached IN LISTS A)
endforeach()
set(broken before)
foreach(broken IN LISTS A)
  break()
endforeach()
set(in_range before)
foreach(in_range RANGE 2)
endforeach()
set(x before)
foreach(x y IN ZIP_LISTS A B)
endforeach()
set(p_1 before)
foreach(p IN ZIP_LISTS A B)
endforeach()
foreach(outer 1 2)
  foreach(outer x y)
  endforeach()
  list(APPEND NESTED "${outer}")
endforeach()
foreach(set_in_body 1 2)
  set(set_in_body changed)
endforeach()
set(unset_in_body before)
foreach(unset_in_body 1 2)
  unset(unset_in_body)
endforeach()
"""
    )

    for name in ("was_set", "broken", "in_range", "x", "p_1", "unset_in_body"):
        assert ctx.variables[name] == "before", name
    for name in ("was_not_set", "y", "p_0", "outer", "set_in_body"):
        assert name not in ctx.variables, name
    # The cache entry that the loop variable hid shows again.
    assert ctx.variables["cached"] == "from_cache"
    assert ctx.variables["NESTED"] == "1;2"


def test_foreach_without_iterations_keeps_variables() -> None:
    ctx = _run(
        r"""
set(EMPTY "")
set(was_set before)
foreach(was_set IN LISTS EMPTY)
endforeach()
foreach(was_not_set IN LISTS EMPTY)
endforeach()
"""
    )

    assert ctx.variables["was_set"] == "before"
    assert "was_not_set" not in ctx.variables


def test_foreach_restores_loop_variables_on_return(tmp_path: Path) -> None:
    """Also when return() leaves the loop, in a function or an included file."""
    included = tmp_path / "included.cmake"
    included.write_text(
        "set(in_file before)\n"
        "foreach(in_file 1 2 3)\n"
        "  return()\n"
        "endforeach()\n"
    )
    ctx = _run(
        r"""
function(in_function)
  foreach(inherited 1 2)
  endforeach()
  set(INHERITED "${inherited}" PARENT_SCOPE)
  foreach(local 1 2)
  endforeach()
  if(NOT DEFINED local)
    set(LOCAL_NOT_DEFINED TRUE PARENT_SCOPE)
  endif()
  foreach(inherited 1 2)
    return()
  endforeach()
endfunction()
set(inherited before)
in_function()
include("@INCLUDED@")
""".replace("@INCLUDED@", included.as_posix())
    )

    assert ctx.variables["INHERITED"] == "before"
    assert ctx.variables["LOCAL_NOT_DEFINED"] == "TRUE"
    assert ctx.variables["inherited"] == "before"
    assert ctx.variables["in_file"] == "before"
