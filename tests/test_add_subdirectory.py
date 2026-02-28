"""Tests for add_subdirectory command."""

from pathlib import Path
from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_add_subdirectory(tmp_path: Path) -> None:
    """Test add_subdirectory command."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    sub_dir = source_dir / "subdir"
    sub_dir.mkdir()

    (sub_dir / "CMakeLists.txt").write_text(
        "set(SUB_VAR Hello)\nadd_executable(sub_exe main.c)"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")
    (sub_dir / "main.c").write_text("int main() { return 0; }")

    ctx = BuildContext(source_dir=source_dir, build_dir=tmp_path / "build")
    commands = [Command(name="add_subdirectory", args=["subdir"], line=1)]

    process_commands(commands, ctx)

    # Check that executable from subdirectory was added
    assert any(exe.name == "sub_exe" for exe in ctx.executables)

    # CMake's add_subdirectory creates a new scope.
    # Variables set in the subdirectory should NOT be visible in the parent scope.
    assert "SUB_VAR" not in ctx.variables


def test_add_subdirectory_parent_scope(tmp_path: Path) -> None:
    """Test add_subdirectory with PARENT_SCOPE."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    sub_dir = source_dir / "subdir"
    sub_dir.mkdir()

    (sub_dir / "CMakeLists.txt").write_text("set(SUB_VAR Hello PARENT_SCOPE)")

    ctx = BuildContext(source_dir=source_dir, build_dir=tmp_path / "build")
    commands = [Command(name="add_subdirectory", args=["subdir"], line=1)]

    process_commands(commands, ctx)

    assert ctx.variables["SUB_VAR"] == "Hello"


def test_add_subdirectory_ninja(tmp_path: Path) -> None:
    """Test that add_subdirectory generates correct paths in ninja file."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    sub_dir = source_dir / "subdir"
    sub_dir.mkdir()

    (source_dir / "CMakeLists.txt").write_text("add_subdirectory(subdir)")
    (sub_dir / "CMakeLists.txt").write_text("add_executable(sub_exe main.c)")
    (sub_dir / "main.c").write_text("int main() { return 0; }")

    from cja.generator import configure

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    assert ninja_file.exists()

    ninja_content = ninja_file.read_text()
    # Source path should be relative to the ninja file (which is in source_dir)
    # So it should be subdir/main.c
    assert "build $builddir/subdir/sub_exe_main.o: cc subdir/main.c" in ninja_content


def test_add_subdirectory_current_dir(tmp_path: Path) -> None:
    """Test CMAKE_CURRENT_SOURCE_DIR in add_subdirectory."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    sub_dir = source_dir / "subdir"
    sub_dir.mkdir()

    (sub_dir / "CMakeLists.txt").write_text(
        "set(SUB_DIR ${CMAKE_CURRENT_SOURCE_DIR} PARENT_SCOPE)"
    )

    ctx = BuildContext(source_dir=source_dir, build_dir=tmp_path / "build")
    commands = [Command(name="add_subdirectory", args=["subdir"], line=1)]

    process_commands(commands, ctx)

    assert ctx.variables["SUB_DIR"] == str(sub_dir.resolve())


def test_add_subdirectory_restores_current_source_dir(tmp_path: Path) -> None:
    """CMAKE_CURRENT_SOURCE_DIR should be restored after add_subdirectory."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    sub_dir = source_dir / "subdir"
    sub_dir.mkdir()
    (sub_dir / "CMakeLists.txt").write_text("message(STATUS subdir)")

    ctx = BuildContext(source_dir=source_dir, build_dir=tmp_path / "build")
    ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] = str(source_dir)
    ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(source_dir / "CMakeLists.txt")
    ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(source_dir)
    ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(tmp_path / "build")

    commands = [Command(name="add_subdirectory", args=["subdir"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] == str(source_dir)


def test_add_subdirectory_two_levels(tmp_path: Path) -> None:
    """CMAKE_CURRENT_SOURCE_DIR should restore across nested subdirectories."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    sub_dir = source_dir / "subdir"
    sub_dir.mkdir()
    sub_sub_dir = sub_dir / "inner"
    sub_sub_dir.mkdir()

    (sub_dir / "CMakeLists.txt").write_text("add_subdirectory(inner)")
    (sub_sub_dir / "CMakeLists.txt").write_text("message(STATUS inner)")

    ctx = BuildContext(source_dir=source_dir, build_dir=tmp_path / "build")
    ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] = str(source_dir)
    ctx.variables["CMAKE_CURRENT_LIST_FILE"] = str(source_dir / "CMakeLists.txt")
    ctx.variables["CMAKE_CURRENT_LIST_DIR"] = str(source_dir)
    ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(tmp_path / "build")

    commands = [Command(name="add_subdirectory", args=["subdir"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] == str(source_dir)


def test_project_source_dir_is_global_across_subdirectory(tmp_path: Path) -> None:
    """project(name) in subdirectory should expose name_SOURCE_DIR globally."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    sub_dir = source_dir / "gtest"
    sub_dir.mkdir()

    (sub_dir / "CMakeLists.txt").write_text("project(gtest)")

    ctx = BuildContext(source_dir=source_dir, build_dir=tmp_path / "build")
    commands = [Command(name="add_subdirectory", args=["gtest"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["gtest_SOURCE_DIR"] == str(sub_dir.resolve())


def test_subdirectory_compile_options_do_not_leak_to_parent(tmp_path: Path) -> None:
    """add_compile_options in subdirectory should not affect parent targets."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    sub_dir = source_dir / "subdir"
    sub_dir.mkdir()

    (source_dir / "main.cpp").write_text("int main() { return 0; }\n")
    (source_dir / "CMakeLists.txt").write_text(
        "add_subdirectory(subdir)\nadd_executable(app main.cpp)\n"
    )
    (sub_dir / "sub.cpp").write_text("int sub() { return 0; }\n")
    (sub_dir / "CMakeLists.txt").write_text(
        "add_compile_options(-Werror -Wshadow)\nadd_library(sub STATIC sub.cpp)\n"
    )

    from cja.generator import configure

    configure(source_dir, "build")
    ninja = (source_dir / "build.ninja").read_text()

    app_compile_line = next(
        line
        for line in ninja.splitlines()
        if "build $builddir/app_main.o: cxx main.cpp" in line
    )
    assert "-Werror" not in app_compile_line
    assert "-Wshadow" not in app_compile_line
