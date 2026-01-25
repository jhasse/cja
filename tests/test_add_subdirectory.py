"""Tests for add_subdirectory command."""

from pathlib import Path
from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


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

    from cninja.generator import configure

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    assert ninja_file.exists()

    ninja_content = ninja_file.read_text()
    # Source path should be relative to the ninja file (which is in source_dir)
    # So it should be subdir/main.c
    assert "build $builddir/sub_exe_main.o: cc subdir/main.c" in ninja_content


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
