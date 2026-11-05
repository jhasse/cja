"""Tests for CMAKE_CURRENT_LIST_FILE variable."""

from pathlib import Path

import pytest


def test_cmake_current_list_file(tmp_path: Path) -> None:
    """Test CMAKE_CURRENT_LIST_FILE in main and subdirectory."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    main_cmake = source_dir / "CMakeLists.txt"
    main_cmake.write_text(
        "set(MAIN_FILE ${CMAKE_CURRENT_LIST_FILE})\nadd_subdirectory(subdir)"
    )

    sub_dir = source_dir / "subdir"
    sub_dir.mkdir()
    sub_cmake = sub_dir / "CMakeLists.txt"
    sub_cmake.write_text("set(SUB_FILE ${CMAKE_CURRENT_LIST_FILE} PARENT_SCOPE)")

    from cja.generator import configure

    ctx = configure(source_dir, "build")

    assert ctx.variables["MAIN_FILE"] == main_cmake.resolve().as_posix()
    assert ctx.variables["SUB_FILE"] == sub_cmake.resolve().as_posix()


def test_print_location(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that print_warning uses the correct filename in location."""

    source_dir = tmp_path / "src"
    source_dir.mkdir()

    sub_dir = source_dir / "subdir"
    sub_dir.mkdir()
    sub_cmake = sub_dir / "CMakeLists.txt"
    # Trigger a warning in subdir
    sub_cmake.write_text('message(WARNING "Test warning")')

    (source_dir / "CMakeLists.txt").write_text("add_subdirectory(subdir)")

    from cja.generator import configure

    configure(source_dir, "build")

    captured = capsys.readouterr()
    assert "subdir/CMakeLists.txt:1: warning: Test warning" in captured.err


def _write_helpers(source_dir: Path) -> None:
    (source_dir / "cmake").mkdir()
    (source_dir / "cmake" / "helpers.cmake").write_text(
        "macro(warn_macro)\n"
        '  message(WARNING "from macro")\n'
        "  warn_function()\n"
        "endmacro()\n"
        "function(warn_function)\n"
        '  message(WARNING "from function")\n'
        "endfunction()\n"
        "macro(empty_macro)\n"
        "endmacro()\n"
        "function(call_macro)\n"
        "  empty_macro()\n"
        "  set(AFTER_MACRO_IN_FUNCTION ${CMAKE_CURRENT_LIST_FILE} PARENT_SCOPE)\n"
        "endfunction()\n"
        "macro(include_in_macro)\n"
        "  include(${CMAKE_CURRENT_LIST_DIR}/cmake/empty.cmake)\n"
        "endmacro()\n"
        "macro(subdir_in_macro)\n"
        "  add_subdirectory(subdir)\n"
        "endmacro()\n"
    )
    (source_dir / "cmake" / "empty.cmake").write_text("")
    (source_dir / "subdir").mkdir()
    (source_dir / "subdir" / "CMakeLists.txt").write_text("warn_macro()\n")


def test_print_location_in_macro(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Warnings point into the file defining the macro or function."""

    source_dir = tmp_path / "src"
    source_dir.mkdir()
    _write_helpers(source_dir)
    (source_dir / "CMakeLists.txt").write_text(
        "include(cmake/helpers.cmake)\nwarn_macro()\nsubdir_in_macro()\n"
    )

    from cja.generator import configure

    configure(source_dir, "build")

    err = capsys.readouterr().err
    assert err.count("cmake/helpers.cmake:2: warning: from macro") == 2
    assert err.count("cmake/helpers.cmake:6: warning: from function") == 2


def test_cmake_current_list_file_after_macros(tmp_path: Path) -> None:
    """Macros and functions don't change the caller's CMAKE_CURRENT_LIST_FILE,
    even after they include a file or add a subdirectory."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    _write_helpers(source_dir)
    main_cmake = source_dir / "CMakeLists.txt"
    main_cmake.write_text(
        "include(cmake/helpers.cmake)\n"
        "call_macro()\n"
        "include_in_macro()\n"
        "set(AFTER_INCLUDE_IN_MACRO ${CMAKE_CURRENT_LIST_FILE})\n"
        "subdir_in_macro()\n"
        "set(AFTER_SUBDIR_IN_MACRO ${CMAKE_CURRENT_LIST_FILE})\n"
    )

    from cja.generator import configure

    ctx = configure(source_dir, "build")

    expected = main_cmake.resolve().as_posix()
    assert ctx.variables["AFTER_MACRO_IN_FUNCTION"] == expected
    assert ctx.variables["AFTER_INCLUDE_IN_MACRO"] == expected
    assert ctx.variables["AFTER_SUBDIR_IN_MACRO"] == expected
