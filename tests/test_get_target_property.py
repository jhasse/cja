"""Tests for get_target_property command."""

from pathlib import Path
from cja.generator import configure


def test_get_target_property_type(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    (source_dir / "CMakeLists.txt").write_text(
        "project(test_props)\n"
        "add_library(mylib STATIC mylib.c)\n"
        "get_target_property(MYLIB_TYPE mylib TYPE)\n"
        "add_executable(myexe main.c)\n"
        "get_target_property(MYEXE_TYPE myexe TYPE)\n"
        'set(RESULT "${MYLIB_TYPE}:${MYEXE_TYPE}")'
    )
    (source_dir / "mylib.c").write_text("int mylib_func() { return 0; }")
    (source_dir / "main.c").write_text("int main() { return 0; }")

    ctx = configure(source_dir, "build")

    assert ctx.variables["MYLIB_TYPE"] == "STATIC_LIBRARY"
    assert ctx.variables["MYEXE_TYPE"] == "EXECUTABLE"
    assert ctx.variables["RESULT"] == "STATIC_LIBRARY:EXECUTABLE"


def test_get_target_property_notfound(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "get_target_property(VAL non_existent_target TYPE)"
    )
    ctx = configure(source_dir, "build")
    assert ctx.variables["VAL"] == "VAL-NOTFOUND"
