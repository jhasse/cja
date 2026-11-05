"""Tests for cmake_language(EVAL CODE)."""

from pathlib import Path

import pytest

from cja.build_context import BuildContext
from cja.generator import configure


def _configure(tmp_path: Path, content: str, strict: bool = False) -> BuildContext:
    (tmp_path / "CMakeLists.txt").write_text(content)
    return configure(tmp_path, "build", strict=strict)


def test_eval(tmp_path: Path) -> None:
    """The expected values are the output of CMake 4.3."""
    ctx = _configure(
        tmp_path,
        'cmake_language(EVAL CODE "set(A 1)" "\\nset(B 2)")\n'
        "cmake_language(EVAL CODE [[set(C ${A})\n"
        "function(f)\n"
        "  set(F_RESULT in_f PARENT_SCOPE)\n"
        "endfunction()\n"
        'set(EVAL_LOCATION "${CMAKE_CURRENT_LIST_FILE} ${CMAKE_CURRENT_LIST_LINE}")'
        "]])\n"
        "f()\n"
        'set(LOCATION "${CMAKE_CURRENT_LIST_FILE} ${CMAKE_CURRENT_LIST_LINE}")\n'
        "function(g)\n"
        '  cmake_language(EVAL CODE "set(G g)\\nreturn()\\nset(G unreachable)")\n'
        "  set(G_RESULT ${G} PARENT_SCOPE)\n"
        "endfunction()\n"
        "g()\n"
        'set(x "set(NESTED nested)")\n'
        'cmake_language(EVAL CODE "cmake_language(EVAL CODE [=[${x}]=])")\n'
        'cmake_language(EVAL CODE "")\n',
    )
    list_file = (tmp_path / "CMakeLists.txt").as_posix()
    assert ctx.variables["A"] == "1"
    assert ctx.variables["B"] == "2"
    assert ctx.variables["C"] == "1"
    assert ctx.variables["F_RESULT"] == "in_f"
    assert ctx.variables["EVAL_LOCATION"] == f"{list_file}:2:EVAL 5"
    assert ctx.variables["LOCATION"] == f"{list_file} 8"
    assert ctx.variables["G_RESULT"] == "g"
    assert ctx.variables["NESTED"] == "nested"


def test_eval_diagnostics_point_into_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        _configure(
            tmp_path, 'cmake_language(EVAL CODE "\\n\\nmessage(FATAL_ERROR boom)")\n'
        )
    assert "CMakeLists.txt:1:EVAL:3: error: boom" in capsys.readouterr().err


def test_eval_parse_error(tmp_path: Path) -> None:
    with pytest.raises(SyntaxError) as error:
        _configure(tmp_path, 'cmake_language(EVAL CODE "set(A")\n')
    assert error.value.filename == f"{tmp_path / 'CMakeLists.txt'}:1:EVAL"


@pytest.mark.parametrize(
    ("call", "message"),
    [
        ("EVAL", "called with incorrect number of arguments"),
        ("EVAL FOO x", "called without CODE argument"),
    ],
)
def test_eval_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], call: str, message: str
) -> None:
    with pytest.raises(SystemExit):
        _configure(tmp_path, f"cmake_language({call})\n", strict=True)
    assert f"CMakeLists.txt:1: error: cmake_language {message}" in (
        capsys.readouterr().err
    )
