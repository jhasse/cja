"""Tests for get_target_property command."""

from pathlib import Path

from cja.generator import configure
from cja.utils import to_posix_path


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


def test_get_target_property_include_directories(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "inc").mkdir()
    (source_dir / "mylib.c").write_text("int mylib_func() { return 0; }")
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_includes)\n"
        "add_library(mylib STATIC mylib.c)\n"
        "target_include_directories(mylib PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/inc)\n"
        "get_target_property(INCS mylib INCLUDE_DIRECTORIES)\n"
    )
    ctx = configure(source_dir, "build")
    assert "inc" in ctx.variables["INCS"]


def test_get_target_property_name_and_directories(tmp_path: Path) -> None:
    """NAME, SOURCE_DIR and BINARY_DIR tell where a target was created."""
    source_dir = (tmp_path / "src").resolve()
    (source_dir / "sub").mkdir(parents=True)
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_dirs C)\n"
        "add_library(mylib STATIC mylib.c)\n"
        "add_library(my::alias ALIAS mylib)\n"
        "add_library(imported UNKNOWN IMPORTED)\n"
        "add_subdirectory(sub)\n"
        "get_target_property(ALIAS_NAME my::alias NAME)\n"
        "get_target_property(IMPORTED_NAME imported NAME)\n"
        "foreach(target mylib subexe subcustom)\n"
        "  foreach(prop NAME SOURCE_DIR BINARY_DIR)\n"
        "    get_target_property(${target}_${prop} ${target} ${prop})\n"
        "  endforeach()\n"
        "endforeach()\n"
    )
    (source_dir / "sub" / "CMakeLists.txt").write_text(
        "add_executable(subexe main.c)\nadd_custom_target(subcustom)\n"
    )
    (source_dir / "mylib.c").write_text("int mylib_func() { return 0; }")
    (source_dir / "sub" / "main.c").write_text("int main() { return 0; }")

    ctx = configure(source_dir, "build")

    assert ctx.variables["ALIAS_NAME"] == "mylib"
    assert ctx.variables["IMPORTED_NAME"] == "imported"
    assert ctx.variables["mylib_NAME"] == "mylib"
    assert ctx.variables["mylib_SOURCE_DIR"] == to_posix_path(source_dir)
    assert ctx.variables["mylib_BINARY_DIR"] == to_posix_path(source_dir / "build")
    for target in ("subexe", "subcustom"):
        assert ctx.variables[f"{target}_NAME"] == target
        assert ctx.variables[f"{target}_SOURCE_DIR"] == to_posix_path(
            source_dir / "sub"
        )
        assert ctx.variables[f"{target}_BINARY_DIR"] == to_posix_path(
            source_dir / "build" / "sub"
        )
