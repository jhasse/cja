"""Tests for set_source_files_properties command."""

from pathlib import Path

from cninja.generator import BuildContext, process_commands, generate_ninja
from cninja.parser import Command


def test_set_source_files_properties(tmp_path: Path) -> None:
    """Test that set_source_files_properties correctly sets and applies properties."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    # Create dummy source files
    main_cpp = tmp_path / "main.cpp"
    main_cpp.touch()
    generated_h = tmp_path / "generated.h"
    generated_h.touch()

    commands = [
        Command(name="add_executable", args=["myapp", "main.cpp"], line=1),
        Command(
            name="set_source_files_properties",
            args=[
                "main.cpp",
                "PROPERTIES",
                "COMPILE_DEFINITIONS",
                "SPECIAL_DEF",
                "INCLUDE_DIRECTORIES",
                "extra_inc",
                "OBJECT_DEPENDS",
                "generated.h",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    abs_main = str(main_cpp)
    assert abs_main in ctx.source_file_properties
    props = ctx.source_file_properties[abs_main]
    assert "SPECIAL_DEF" in props.compile_definitions
    assert "extra_inc" in props.include_directories
    assert "generated.h" in props.object_depends

    # Test propagation to Ninja file
    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    ninja_content = ninja_path.read_text()

    # Check if properties are applied to main.cpp build statement
    assert "build $builddir/myapp_main.o: cxx main.cpp" in ninja_content
    assert "-DSPECIAL_DEF" in ninja_content
    assert "-Iextra_inc" in ninja_content
    # Use a more flexible check for the dependency as ninja-syntax might wrap lines
    assert "generated.h" in ninja_content
    assert "|" in ninja_content


def test_multiple_files_and_semicolons(tmp_path: Path) -> None:
    """Test setting properties on multiple files and using semicolon lists."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    (tmp_path / "file1.cpp").touch()
    (tmp_path / "file2.cpp").touch()

    commands = [
        Command(name="add_library", args=["mylib", "file1.cpp", "file2.cpp"], line=1),
        Command(
            name="set_source_files_properties",
            args=[
                "file1.cpp",
                "file2.cpp",
                "PROPERTIES",
                "COMPILE_DEFINITIONS",
                "DEF1;DEF2",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    for f in ["file1.cpp", "file2.cpp"]:
        abs_f = str(tmp_path / f)
        assert abs_f in ctx.source_file_properties
        props = ctx.source_file_properties[abs_f]
        assert "DEF1" in props.compile_definitions
        assert "DEF2" in props.compile_definitions


def test_object_depends_absolute_path(tmp_path: Path) -> None:
    """Test that absolute paths in OBJECT_DEPENDS are handled correctly."""
    source_root = tmp_path.absolute()
    ctx = BuildContext(source_dir=source_root, build_dir=source_root / "build")

    main_cpp = source_root / "main.cpp"
    main_cpp.touch()
    dep_h = source_root / "dep.h"
    dep_h.touch()

    commands = [
        Command(name="add_executable", args=["myapp", "main.cpp"], line=1),
        Command(
            name="set_source_files_properties",
            args=["main.cpp", "PROPERTIES", "OBJECT_DEPENDS", str(dep_h)],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    abs_main = str(main_cpp)
    assert abs_main in ctx.source_file_properties
    props = ctx.source_file_properties[abs_main]

    # It should be relative to source_dir if it's inside it
    assert "dep.h" in props.object_depends
    assert str(dep_h) not in props.object_depends

    # Test propagation to Ninja file
    ninja_path = source_root / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    ninja_content = ninja_path.read_text()
    assert (
        "main.cpp | dep.h" in ninja_content
        or "main.cpp | $\n    dep.h" in ninja_content
    )
