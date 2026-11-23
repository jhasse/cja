"""Tests for set_source_files_properties command."""

import re
from pathlib import Path

import pytest

from cja.generator import BuildContext, generate_ninja, process_commands
from cja.parser import Command, parse


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
    assert abs_main in ctx.source_file_scope(ctx.source_dir)
    props = ctx.source_file_scope(ctx.source_dir)[abs_main]
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
            is_quoted=[False, False, False, False, True],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    for f in ["file1.cpp", "file2.cpp"]:
        abs_f = str(tmp_path / f)
        assert abs_f in ctx.source_file_scope(ctx.source_dir)
        props = ctx.source_file_scope(ctx.source_dir)[abs_f]
        assert "DEF1" in props.compile_definitions
        assert "DEF2" in props.compile_definitions


def test_source_file_compile_definition_escapes_quotes(tmp_path: Path) -> None:
    """Quoted values in COMPILE_DEFINITIONS should keep quotes in compiler args."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    (tmp_path / "foo.cpp").touch()
    commands = [
        Command(name="add_executable", args=["myapp", "foo.cpp"], line=1),
        Command(
            name="set_source_files_properties",
            args=["foo.cpp", "PROPERTIES", "COMPILE_DEFINITIONS", 'FOO="BAR"'],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    ninja_content = ninja_path.read_text()
    assert '-DFOO=\\"BAR\\"' in ninja_content


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
    assert abs_main in ctx.source_file_scope(ctx.source_dir)
    props = ctx.source_file_scope(ctx.source_dir)[abs_main]

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


def test_absolute_path_with_forward_slashes(tmp_path: Path) -> None:
    """Absolute paths with forward slashes (e.g. from file(GLOB) on Windows) should match."""
    source_root = tmp_path.absolute()
    ctx = BuildContext(source_dir=source_root, build_dir=source_root / "build")

    (source_root / "foo.cpp").touch()
    commands = [
        Command(name="add_executable", args=["myapp", "foo.cpp"], line=1),
        Command(
            name="set_source_files_properties",
            args=[
                (source_root / "foo.cpp").as_posix(),
                "PROPERTIES",
                "COMPILE_DEFINITIONS",
                "NOMINMAX",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    ninja_path = source_root / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    assert "-DNOMINMAX" in ninja_path.read_text()


def test_custom_source_file_properties() -> None:
    """Properties that cja doesn't use are kept and can be read again."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(
        parse(
            "set_property(SOURCE a.c PROPERTY MY_PROP x y)\n"
            "set_property(SOURCE a.c APPEND PROPERTY MY_PROP z)\n"
            'set_source_files_properties(a.c b.c PROPERTIES OTHER "o;p" LANGUAGE C)\n'
            "set_source_files_properties(a.c PROPERTIES\n"
            '    COMPILE_DEFINITIONS "A=1;B=2" COMPILE_OPTIONS "-Wall;-Wextra")\n'
            "get_property(MY_PROP SOURCE a.c PROPERTY MY_PROP)\n"
            "get_property(OTHER_IS_SET SOURCE b.c PROPERTY OTHER SET)\n"
            "get_property(UNSET_IS_SET SOURCE b.c PROPERTY MY_PROP SET)\n"
            "get_source_file_property(MY_PROP_OF_FILE a.c MY_PROP)\n"
            "get_source_file_property(OTHER b.c OTHER)\n"
            "get_source_file_property(LANGUAGE b.c DIRECTORY . LANGUAGE)\n"
            "get_source_file_property(DEFINITIONS a.c COMPILE_DEFINITIONS)\n"
            "get_source_file_property(OPTIONS a.c COMPILE_OPTIONS)\n"
            "get_source_file_property(UNSET b.c MY_PROP)\n"
            "get_source_file_property(NO_FILE c.c MY_PROP)\n"
            "set_property(SOURCE a.c PROPERTY MY_PROP)\n"
            "get_source_file_property(REMOVED a.c MY_PROP)\n"
        ),
        ctx,
        strict=True,
    )

    assert ctx.variables["MY_PROP"] == "x;y;z"
    assert ctx.variables["OTHER_IS_SET"] == "1"
    assert ctx.variables["UNSET_IS_SET"] == "0"
    assert ctx.variables["MY_PROP_OF_FILE"] == "x;y;z"
    assert ctx.variables["OTHER"] == "o;p"
    assert ctx.variables["LANGUAGE"] == "C"
    assert ctx.variables["DEFINITIONS"] == "A=1;B=2"
    assert ctx.variables["OPTIONS"] == "-Wall;-Wextra"
    assert ctx.variables["UNSET"] == "NOTFOUND"
    assert ctx.variables["NO_FILE"] == "NOTFOUND"
    assert ctx.variables["REMOVED"] == "NOTFOUND"

    with pytest.raises(SystemExit):
        process_commands(
            parse("get_source_file_property(VAR a.c)\n"), ctx, strict=True
        )


def test_source_file_properties_are_per_directory(tmp_path: Path) -> None:
    """Like in CMake, source file properties are for the targets of the
    directory that they're set in, or of the ones given."""
    from cja.generator import configure

    (tmp_path / "CMakeLists.txt").write_text(
        """\
cmake_minimum_required(VERSION 3.20)
project(SourceScopeTest C)
add_library(toplib STATIC shared.c sub/s.c)
set_source_files_properties(shared.c sub/s.c PROPERTIES
    COMPILE_DEFINITIONS TOP_DEF MY_PROP top)
add_subdirectory(sub)
add_subdirectory(other)
set_source_files_properties(shared.c DIRECTORY sub PROPERTIES
    COMPILE_DEFINITIONS FOR_SUB MY_PROP for_sub)
set_property(SOURCE shared.c TARGET_DIRECTORY otherlib PROPERTY MY_PROP for_other)
get_source_file_property(TOP shared.c MY_PROP)
get_source_file_property(TOP_FOR_SUB shared.c DIRECTORY sub MY_PROP)
get_property(TOP_FOR_OTHER SOURCE shared.c TARGET_DIRECTORY otherlib PROPERTY MY_PROP)
get_source_file_property(TOP_OF_SUB sub/s.c SUB_PROP)
get_source_file_property(TOP_OF_SUB_IN_SUB sub/s.c DIRECTORY sub SUB_PROP)
"""
    )
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "CMakeLists.txt").write_text(
        """\
add_library(sublib STATIC s.c ${CMAKE_SOURCE_DIR}/shared.c)
set_source_files_properties(s.c PROPERTIES COMPILE_DEFINITIONS SUB_DEF SUB_PROP sub)
get_source_file_property(SUB ${CMAKE_SOURCE_DIR}/shared.c MY_PROP)
get_source_file_property(SUB_OF_TOP ${CMAKE_SOURCE_DIR}/shared.c
    DIRECTORY ${CMAKE_SOURCE_DIR} MY_PROP)
set(SUB "${SUB}" PARENT_SCOPE)
set(SUB_OF_TOP "${SUB_OF_TOP}" PARENT_SCOPE)
"""
    )
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "CMakeLists.txt").write_text(
        "add_library(otherlib STATIC ${CMAKE_SOURCE_DIR}/shared.c)\n"
    )
    for source in ("shared.c", "sub/s.c"):
        (tmp_path / source).write_text("")

    ctx = configure(tmp_path, "build", strict=True)

    assert ctx.variables["TOP"] == "top"
    assert ctx.variables["TOP_FOR_SUB"] == "for_sub"
    assert ctx.variables["TOP_FOR_OTHER"] == "for_other"
    assert ctx.variables["TOP_OF_SUB"] == "NOTFOUND"
    assert ctx.variables["TOP_OF_SUB_IN_SUB"] == "sub"
    assert ctx.variables["SUB"] == "NOTFOUND"
    assert ctx.variables["SUB_OF_TOP"] == "top"

    ninja_content = (tmp_path / "build.ninja").read_text()
    flags = dict(
        re.findall(r"^build \S*/(\w+)\.o: .*\n(?:  cflags = (.*))?", ninja_content, re.MULTILINE)
    )
    assert flags == {
        "toplib_shared": "-DTOP_DEF",
        "toplib_s": "-DTOP_DEF",
        "sublib_s": "-DSUB_DEF",
        "sublib_shared": "-DFOR_SUB",
        "otherlib_shared": "",
    }
