"""Tests for break() and continue() outside of the loop's list file or scope."""

from pathlib import Path

import pytest

from cja.build_context import BuildContext
from cja.generator import configure


def _configure(tmp_path: Path, content: str, strict: bool = False) -> BuildContext:
    (tmp_path / "CMakeLists.txt").write_text(content)
    return configure(tmp_path, "build", strict=strict)


@pytest.mark.parametrize("command", ["break", "continue"])
def test_outside_of_loop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    ctx = _configure(tmp_path, f"{command}()\nset(AFTER 1)\n")
    message = (
        f"CMakeLists.txt:1: warning: A {command.upper()} command was found outside"
        " of a proper FOREACH or WHILE loop scope."
    )
    assert message in capsys.readouterr().err
    assert ctx.variables["AFTER"] == "1"

    with pytest.raises(SystemExit):
        _configure(tmp_path, f"{command}()\n", strict=True)
    assert message.replace("warning", "error") in capsys.readouterr().err


def test_function_and_subdirectory_dont_see_the_callers_loop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The expected values are the output of CMake 4.3, which errors instead."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "CMakeLists.txt").write_text("break()\n")
    ctx = _configure(
        tmp_path,
        "function(f)\n"
        "  break()\n"
        "endfunction()\n"
        "foreach(i 1 2)\n"
        "  f()\n"
        "  add_subdirectory(sub sub${i})\n"
        "  list(APPEND RESULT ${i})\n"
        "endforeach()\n",
    )
    assert ctx.variables["RESULT"] == "1;2"
    err = capsys.readouterr().err
    assert "CMakeLists.txt:2: warning: A BREAK command" in err
    assert "sub/CMakeLists.txt:1: warning: A BREAK command" in err


def test_loop_outside_of_list_file_is_not_affected(tmp_path: Path) -> None:
    """The expected values are the output of CMake 4.3."""
    (tmp_path / "inc.cmake").write_text("break()\nlist(APPEND RESULT inc)\n")
    ctx = _configure(
        tmp_path,
        "foreach(i 1 2)\n"
        "  include(inc.cmake)\n"
        '  cmake_language(EVAL CODE "continue()\\nlist(APPEND RESULT eval)")\n'
        "  list(APPEND RESULT ${i})\n"
        "endforeach()\n",
        strict=True,
    )
    assert ctx.variables["RESULT"] == "inc;eval;1;inc;eval;2"


def test_macro_ends_the_callers_loop(tmp_path: Path) -> None:
    ctx = _configure(
        tmp_path,
        "macro(m)\n"
        "  break()\n"
        "endmacro()\n"
        "foreach(i 1 2)\n"
        "  list(APPEND RESULT ${i})\n"
        "  m()\n"
        "endforeach()\n",
        strict=True,
    )
    assert ctx.variables["RESULT"] == "1"
