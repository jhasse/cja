"""Tests for the while command."""

from pathlib import Path

import pytest

from cja.build_context import BuildContext
from cja.generator import process_commands
from cja.parser import parse


def _run(content: str) -> BuildContext:
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(parse(content), ctx)
    return ctx


def test_while_reevaluates_condition() -> None:
    ctx = _run(
        "set(i 0)\n"
        "set(RESULT)\n"
        "while(i LESS 3)\n"
        "  list(APPEND RESULT ${i})\n"
        "  math(EXPR i \"${i} + 1\")\n"
        "endwhile()\n"
    )
    assert ctx.variables["RESULT"] == "0;1;2"


def test_while_false_skips_body() -> None:
    ctx = _run("set(RESULT a)\nwhile(FALSE)\n  set(RESULT b)\nendwhile()\n")
    assert ctx.variables["RESULT"] == "a"


def test_while_break_and_continue() -> None:
    ctx = _run(
        "set(i 0)\n"
        "set(RESULT)\n"
        "while(TRUE)\n"
        "  math(EXPR i \"${i} + 1\")\n"
        "  if(i EQUAL 2)\n"
        "    continue()\n"
        "  endif()\n"
        "  if(i GREATER 4)\n"
        "    break()\n"
        "  endif()\n"
        "  list(APPEND RESULT ${i})\n"
        "endwhile()\n"
    )
    assert ctx.variables["RESULT"] == "1;3;4"


def test_nested_loops() -> None:
    """break() only leaves the innermost loop, foreach() or while()."""
    ctx = _run(
        "set(RESULT)\n"
        "foreach(x a b)\n"
        "  set(list 1 2 3)\n"
        "  while(list)\n"
        "    list(POP_FRONT list item)\n"
        "    if(item EQUAL 3)\n"
        "      break()\n"
        "    endif()\n"
        "    list(APPEND RESULT ${x}${item})\n"
        "  endwhile()\n"
        "endforeach()\n"
    )
    assert ctx.variables["RESULT"] == "a1;a2;b1;b2"


def test_return_from_while_in_function() -> None:
    ctx = _run(
        "function(count_down)\n"
        "  set(num 3)\n"
        "  while(num)\n"
        "    math(EXPR num \"${num} - 1\")\n"
        "    if(num EQUAL 1)\n"
        "      return()\n"
        "    endif()\n"
        "    set(RESULT ${num} PARENT_SCOPE)\n"
        "  endwhile()\n"
        "endfunction()\n"
        "count_down()\n"
    )
    assert ctx.variables["RESULT"] == "2"


def test_missing_endwhile() -> None:
    with pytest.raises(SyntaxError, match="No matching endwhile"):
        _run("while(TRUE)\n")


def test_unexpected_endwhile() -> None:
    with pytest.raises(SyntaxError, match="Unexpected endwhile"):
        _run("endwhile()\n")
