"""Tests for CMAKE_CURRENT_LIST_DIR variable."""

from pathlib import Path
from cninja.generator import configure


def test_cmake_current_list_dir(tmp_path: Path) -> None:
    """Test CMAKE_CURRENT_LIST_DIR in main and subdirectory."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    main_cmake = source_dir / "CMakeLists.txt"
    main_cmake.write_text(
        "set(MAIN_DIR ${CMAKE_CURRENT_LIST_DIR})\nadd_subdirectory(subdir)"
    )

    sub_dir = source_dir / "subdir"
    sub_dir.mkdir()
    sub_cmake = sub_dir / "CMakeLists.txt"
    sub_cmake.write_text("set(SUB_DIR ${CMAKE_CURRENT_LIST_DIR} PARENT_SCOPE)")

    ctx = configure(source_dir, "build")

    assert ctx.variables["MAIN_DIR"] == str(source_dir.resolve())
    assert ctx.variables["SUB_DIR"] == str(sub_dir.resolve())


def test_include_current_list_dir(tmp_path: Path) -> None:
    """Test CMAKE_CURRENT_LIST_DIR inside an included file."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    cmake_dir = source_dir / "cmake"
    cmake_dir.mkdir()
    inc_file = cmake_dir / "inc.cmake"
    inc_file.write_text("set(INC_DIR ${CMAKE_CURRENT_LIST_DIR})")

    (source_dir / "CMakeLists.txt").write_text("include(cmake/inc.cmake)")

    ctx = configure(source_dir, "build")

    assert ctx.variables["INC_DIR"] == str(cmake_dir.resolve())
