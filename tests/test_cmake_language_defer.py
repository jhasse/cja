"""Tests for cmake_language(DEFER)."""

from pathlib import Path

import pytest

from cja.build_context import BuildContext
from cja.generator import configure


def _configure(tmp_path: Path, content: str, strict: bool = False) -> BuildContext:
    (tmp_path / "CMakeLists.txt").write_text(content)
    return configure(tmp_path, "build", strict=strict)


def test_defer_runs_at_end_of_directory(tmp_path: Path) -> None:
    """Arguments are expanded when the deferred call runs, even after return()."""
    ctx = _configure(
        tmp_path,
        "set(x early)\n"
        'cmake_language(DEFER CALL list APPEND RESULT "${x}" [[${x}]] "a;b")\n'
        "list(APPEND RESULT immediate)\n"
        "set(x late)\n"
        "return()\n"
        "list(APPEND RESULT unreachable)\n",
    )
    assert ctx.variables["RESULT"] == "immediate;late;${x};a;b"


def test_defer_from_deferred_call(tmp_path: Path) -> None:
    """Calls deferred while running deferred calls run after them, in order."""
    ctx = _configure(
        tmp_path,
        "function(f)\n"
        "  cmake_language(DEFER CALL list APPEND RESULT nested)\n"
        "  set(RESULT ${RESULT} f PARENT_SCOPE)\n"
        "endfunction()\n"
        "cmake_language(DEFER CALL f)\n"
        "cmake_language(DEFER CALL list APPEND RESULT second)\n",
    )
    assert ctx.variables["RESULT"] == "f;second;nested"


def test_defer_ids(tmp_path: Path) -> None:
    ctx = _configure(
        tmp_path,
        "cmake_language(DEFER ID_VAR first CALL list APPEND RESULT 1)\n"
        "cmake_language(DEFER ID my_id ID_VAR second CALL list APPEND RESULT 2)\n"
        "cmake_language(DEFER ID_VAR third CALL list APPEND RESULT 3 ${x})\n"
        "cmake_language(DEFER ID my_id CALL list APPEND RESULT 4)\n"
        "cmake_language(DEFER GET_CALL_IDS IDS)\n"
        "cmake_language(DEFER GET_CALL ${third} THIRD_CALL)\n"
        "cmake_language(DEFER GET_CALL unknown UNKNOWN_CALL)\n"
        "cmake_language(DEFER CANCEL_CALL my_id unknown)\n"
        "cmake_language(DEFER GET_CALL_IDS REMAINING_IDS)\n",
    )
    assert ctx.variables["first"] == "__0"
    assert ctx.variables["second"] == "my_id"
    assert ctx.variables["third"] == "__1"
    assert ctx.variables["IDS"] == "__0;my_id;__1;my_id"
    assert ctx.variables["THIRD_CALL"] == "list;APPEND;RESULT;3;${x}"
    assert ctx.variables["UNKNOWN_CALL"] == ""
    assert ctx.variables["REMAINING_IDS"] == "__0;__1"
    assert ctx.variables["RESULT"] == "1;3"


def test_defer_current_list_line(tmp_path: Path) -> None:
    ctx = _configure(
        tmp_path, 'cmake_language(DEFER CALL set LINE "${CMAKE_CURRENT_LIST_LINE}")\n'
    )
    assert ctx.variables["LINE"] == "DEFERRED:__0"


def test_defer_to_parent_directory(tmp_path: Path) -> None:
    """DIRECTORY defers to the end of a parent, in the parent's scope."""
    sub_dir = tmp_path / "sub"
    sub_dir.mkdir()
    (sub_dir / "CMakeLists.txt").write_text(
        "set(SUB_VAR sub)\n"
        "cmake_language(DEFER DIRECTORY .. CALL list APPEND RESULT"
        ' "parent ${SUB_VAR}")\n'
        'cmake_language(DEFER CALL set RESULT "sub ${SUB_VAR}" PARENT_SCOPE)\n'
        "cmake_language(DEFER DIRECTORY ${CMAKE_BINARY_DIR} GET_CALL_IDS IDS)\n"
        "set(PARENT_IDS ${IDS} PARENT_SCOPE)\n"
    )
    ctx = _configure(tmp_path, "add_subdirectory(sub)\nlist(APPEND RESULT top)\n")
    assert ctx.variables["PARENT_IDS"] == "__0"
    assert ctx.variables["RESULT"] == "sub sub;top;parent "


def test_defer_to_finished_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    (tmp_path / "a" / "CMakeLists.txt").write_text("")
    (tmp_path / "b" / "CMakeLists.txt").write_text(
        "cmake_language(DEFER DIRECTORY ../a CALL message hi)\n"
    )
    with pytest.raises(SystemExit):
        _configure(tmp_path, "add_subdirectory(a)\nadd_subdirectory(b)\n", strict=True)
    assert (
        "b/CMakeLists.txt:1: error: cmake_language DEFER CALL may not be scheduled"
        f" in directory {(tmp_path / 'build' / 'a').as_posix()} at this time."
    ) in capsys.readouterr().err


def test_deferred_call_diagnostics_point_to_its_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "inc.cmake").write_text(
        "\ncmake_language(DEFER CALL message FATAL_ERROR boom)\n"
    )
    with pytest.raises(SystemExit):
        _configure(tmp_path, "include(inc.cmake)\n")
    assert "inc.cmake:2: error: boom" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("call", "message"),
    [
        ("DEFER", "DEFER must be followed by a CALL argument"),
        ("DEFER FOO CALL f", "DEFER unknown option: FOO"),
        ("DEFER ID Abc CALL f", "DEFER ID may not start in A-Z."),
        ("DEFER ID a ID b CALL f", "DEFER given multiple ID arguments"),
        ("DEFER ID_VAR", "DEFER ID_VAR missing value"),
        ("DEFER CALL", "CALL missing command name"),
        ("DEFER CALL ${LIST}", "CALL command's arguments must be literal"),
        ("DEFER CALL endif", "invalid command specified: endif"),
        ("DEFER ID a GET_CALL_IDS v", "DEFER GET_CALL_IDS does not accept ID or ID_VAR."),
        ("DEFER GET_CALL a", "DEFER GET_CALL missing output variable"),
        ("DEFER DIRECTORY sub CALL f", "DEFER DIRECTORY {source}/sub is not known."),
    ],
)
def test_defer_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], call: str, message: str
) -> None:
    with pytest.raises(SystemExit):
        _configure(
            tmp_path, f"set(LIST f;g)\ncmake_language({call})\n", strict=True
        )
    expected = message.format(source=tmp_path.as_posix())
    assert f"error: cmake_language {expected}" in capsys.readouterr().err
