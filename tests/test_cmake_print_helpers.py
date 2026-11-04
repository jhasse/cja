"""Tests for the bundled CMakePrintHelpers.cmake from CMake."""

from pathlib import Path

import pytest

from cja.generator import configure


def _configure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str, capsys
) -> str:
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(print C)\n"
        "include(CMakePrintHelpers)\n" + body
    )
    (tmp_path / "lib.c").write_text("int f(void) { return 0; }\n")
    monkeypatch.chdir(tmp_path)
    configure(tmp_path, "build", strict=True)
    captured = capsys.readouterr()
    assert "error" not in captured.err
    return captured.out


def test_cmake_print_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    out = _configure(
        tmp_path,
        monkeypatch,
        'set(A "1;2")\nset(B hello)\ncmake_print_variables(A B NOT_EXISTS)\n',
        capsys,
    )

    assert 'A="1;2" ; B="hello" ; NOT_EXISTS=""\n' in out


def test_cmake_print_properties_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    out = _configure(
        tmp_path,
        monkeypatch,
        "add_library(foo STATIC lib.c)\n"
        "target_include_directories(foo PUBLIC /usr/include/foo)\n"
        "cmake_print_properties(TARGETS foo nosuch\n"
        "  PROPERTIES TYPE INTERFACE_INCLUDE_DIRECTORIES UNSET_PROP)\n",
        capsys,
    )

    assert (
        " Properties for TARGET foo:\n"
        '   foo.TYPE = "STATIC_LIBRARY"\n'
        '   foo.INTERFACE_INCLUDE_DIRECTORIES = "/usr/include/foo"\n'
        "   foo.UNSET_PROP = <NOTFOUND>\n"
        '\n No such TARGET "nosuch" !\n'
    ) in out


def test_cmake_print_properties_other_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    out = _configure(
        tmp_path,
        monkeypatch,
        "set_source_files_properties(lib.c PROPERTIES COMPILE_DEFINITIONS X=1)\n"
        "set_property(DIRECTORY PROPERTY MY_DIR_PROP hello)\n"
        "add_executable(app lib.c)\n"
        "add_test(NAME t COMMAND app)\n"
        "set_tests_properties(t PROPERTIES TIMEOUT 5)\n"
        'set(MY_ENTRY abc CACHE STRING "doc")\n'
        "cmake_print_properties(SOURCES lib.c PROPERTIES COMPILE_DEFINITIONS)\n"
        "cmake_print_properties(DIRECTORIES . PROPERTIES MY_DIR_PROP UNSET_PROP)\n"
        "cmake_print_properties(TESTS t PROPERTIES TIMEOUT UNSET_PROP)\n"
        "cmake_print_properties(CACHE_ENTRIES MY_ENTRY PROPERTIES VALUE)\n",
        capsys,
    )

    assert '   lib.c.COMPILE_DEFINITIONS = "X=1"\n' in out
    assert '   ..MY_DIR_PROP = "hello"\n   ..UNSET_PROP = <NOTFOUND>\n' in out
    assert '   t.TIMEOUT = "5"\n   t.UNSET_PROP = <NOTFOUND>\n' in out
    assert '   MY_ENTRY.VALUE = "abc"\n' in out


def test_cmake_print_properties_requires_one_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(print NONE)\n"
        "include(CMakePrintHelpers)\n"
        "cmake_print_properties(TARGETS a TESTS b PROPERTIES TYPE)\n"
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        configure(tmp_path, "build", strict=True)

    assert "Multiple mode keywords used" in capsys.readouterr().err
