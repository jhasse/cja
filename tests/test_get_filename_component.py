"""Tests for get_filename_component command."""

import pytest
from pathlib import Path
from cninja.generator import configure


def test_get_filename_component(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    (source_dir / "CMakeLists.txt").write_text(
        "project(test)\n"
        'get_filename_component(DIR "a/b/c.txt" DIRECTORY)\n'
        'get_filename_component(NAME "a/b/c.txt" NAME)\n'
        'get_filename_component(EXT "a/b/c.txt" EXT)\n'
        'get_filename_component(NAME_WE "a/b/c.txt" NAME_WE)\n'
        'get_filename_component(ABS "c.txt" ABSOLUTE)\n'
        'get_filename_component(ABS_BASE "c.txt" ABSOLUTE BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/sub")\n'
    )

    ctx = configure(source_dir, "build")

    assert ctx.variables["DIR"].replace("\\", "/") == "a/b"
    assert ctx.variables["NAME"] == "c.txt"
    assert ctx.variables["EXT"] == ".txt"
    assert ctx.variables["NAME_WE"] == "c"
    assert ctx.variables["ABS"] == str((source_dir / "c.txt").resolve())
    assert ctx.variables["ABS_BASE"] == str((source_dir / "sub" / "c.txt").resolve())


def test_get_filename_component_empty_dir(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        'get_filename_component(DIR "c.txt" DIRECTORY)'
    )
    ctx = configure(source_dir, "build")
    assert ctx.variables["DIR"] == ""
