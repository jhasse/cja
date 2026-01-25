"""Tests for set_target_properties command."""

from pathlib import Path
from cninja.generator import configure


def test_set_target_properties_interface_include_directories(tmp_path: Path) -> None:
    """Test set_target_properties(PROPERTIES INTERFACE_INCLUDE_DIRECTORIES ...)."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    (source_dir / "CMakeLists.txt").write_text(
        "project(test_props)\n"
        "add_library(mylib STATIC mylib.c)\n"
        'set_target_properties(mylib PROPERTIES INTERFACE_INCLUDE_DIRECTORIES "${CMAKE_CURRENT_SOURCE_DIR}/include")\n'
        "add_executable(main main.c)\n"
        "target_link_libraries(main mylib)"
    )
    (source_dir / "mylib.c").write_text("int mylib_func() { return 0; }")
    (source_dir / "main.c").write_text("int main() { return 0; }")
    (source_dir / "include").mkdir()

    ctx = configure(source_dir, "build")

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert any(str(source_dir / "include") in d for d in lib.public_include_directories)

    # Check that executable 'main' has the include directory from 'mylib'
    exe = ctx.get_executable("main")
    assert exe is not None
    # In cninja, public_include_directories from linked libs should be added to exe.include_directories
    # during processing or ninja generation.

    # Let's verify build.ninja content
    ninja_file = source_dir / "build.ninja"
    content = ninja_file.read_text()
    assert f"-I{source_dir}/include" in content
