"""Tests for CMAKE_CURRENT_LIST_FILE variable."""

import pytest
from pathlib import Path


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

    from cninja.generator import configure

    ctx = configure(source_dir, "build")

    assert ctx.variables["MAIN_FILE"] == str(main_cmake.resolve())
    assert ctx.variables["SUB_FILE"] == str(sub_cmake.resolve())


def test_print_location(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test that print_warning uses the correct filename in location."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    sub_dir = source_dir / "subdir"
    sub_dir.mkdir()
    sub_cmake = sub_dir / "CMakeLists.txt"
    # Trigger a warning in subdir
    sub_cmake.write_text('message(WARNING "Test warning")')

    (source_dir / "CMakeLists.txt").write_text("add_subdirectory(subdir)")

    from cninja.generator import configure

    configure(source_dir, "build")

    captured = capsys.readouterr()
    assert "subdir/CMakeLists.txt:1: warning: Test warning" in captured.err
