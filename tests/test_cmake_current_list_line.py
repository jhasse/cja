"""Tests for CMAKE_CURRENT_LIST_LINE variable."""

from pathlib import Path
from cja.generator import configure


def test_cmake_current_list_line(tmp_path: Path) -> None:
    """Test CMAKE_CURRENT_LIST_LINE reflects the line of each command."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    main_cmake = source_dir / "CMakeLists.txt"
    main_cmake.write_text(
        "set(LINE1 ${CMAKE_CURRENT_LIST_LINE})\n"
        "set(DUMMY ignored)\n"
        "set(LINE3 ${CMAKE_CURRENT_LIST_LINE})\n"
    )

    ctx = configure(source_dir, "build")

    assert ctx.variables["LINE1"] == "1"
    assert ctx.variables["LINE3"] == "3"


def test_cmake_current_list_line_subdirectory(tmp_path: Path) -> None:
    """Test CMAKE_CURRENT_LIST_LINE in a subdirectory."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    main_cmake = source_dir / "CMakeLists.txt"
    main_cmake.write_text("add_subdirectory(subdir)\n")

    sub_dir = source_dir / "subdir"
    sub_dir.mkdir()
    sub_cmake = sub_dir / "CMakeLists.txt"
    sub_cmake.write_text(
        "set(DUMMY ignored)\nset(SUB_LINE ${CMAKE_CURRENT_LIST_LINE} PARENT_SCOPE)\n"
    )

    ctx = configure(source_dir, "build")

    assert ctx.variables["SUB_LINE"] == "2"
