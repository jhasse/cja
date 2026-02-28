"""Tests for target_include_directories command."""

import os
from pathlib import Path

from cja.generator import BuildContext, configure, process_commands
from cja.parser import Command
from tests.helpers import copy_unignored_tree

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def test_target_include_directories_executable() -> None:
    """Test target_include_directories on an executable."""
    ctx = BuildContext(source_dir=Path("/project"), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.cpp"], line=1),
        Command(name="target_include_directories", args=["myapp", "PRIVATE", "src/include"], line=2),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "/project/src/include" in exe.include_directories


def test_target_include_directories_library() -> None:
    """Test target_include_directories on a library."""
    ctx = BuildContext(source_dir=Path("/project"), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["mylib", "lib.cpp"], line=1),
        Command(name="target_include_directories", args=["mylib", "PUBLIC", "include"], line=2),
    ]
    process_commands(commands, ctx)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert "/project/include" in lib.include_directories
    assert "/project/include" in lib.public_include_directories


def test_target_include_directories_private_library() -> None:
    """Test PRIVATE include directories don't propagate."""
    ctx = BuildContext(source_dir=Path("/project"), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["mylib", "lib.cpp"], line=1),
        Command(name="target_include_directories", args=["mylib", "PRIVATE", "src"], line=2),
    ]
    process_commands(commands, ctx)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert "/project/src" in lib.include_directories
    assert "/project/src" not in lib.public_include_directories


def test_target_include_directories_absolute_path() -> None:
    """Test target_include_directories with absolute path."""
    ctx = BuildContext(source_dir=Path("/project"), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.cpp"], line=1),
        Command(name="target_include_directories", args=["myapp", "PRIVATE", "/usr/local/include"], line=2),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "/usr/local/include" in exe.include_directories


def test_target_include_directories_in_ninja(tmp_path: Path) -> None:
    """Test that target_include_directories appear in generated ninja file."""
    source_dir = tmp_path / "hello"
    copy_unignored_tree(EXAMPLES_DIR / "hello", source_dir)

    # Create an include directory
    include_dir = source_dir / "include"
    include_dir.mkdir()

    # Add target_include_directories to CMakeLists.txt
    cmake_file = source_dir / "CMakeLists.txt"
    content = cmake_file.read_text()
    content = content.replace(
        "add_executable(hello main.c subfolder/main.c)",
        "add_executable(hello main.c subfolder/main.c)\n"
        "target_include_directories(hello PRIVATE include)",
    )
    cmake_file.write_text(content)

    configure(source_dir, "build")

    build_ninja = source_dir / "build.ninja"
    ninja_content = build_ninja.read_text()
    assert "-Iinclude" in ninja_content


def test_target_include_directories_public_propagates(tmp_path: Path) -> None:
    """Test PUBLIC include directories propagate to linking targets."""
    source_dir = tmp_path / "libmath"
    copy_unignored_tree(EXAMPLES_DIR / "libmath", source_dir)

    # Create include directory
    include_dir = source_dir / "myinclude"
    include_dir.mkdir()

    # Modify CMakeLists.txt to add target_include_directories
    cmake_file = source_dir / "CMakeLists.txt"
    content = cmake_file.read_text()
    content = content.replace(
        "add_library(math STATIC math.cpp)",
        "add_library(math STATIC math.cpp)\ntarget_include_directories(math PUBLIC myinclude)"
    )
    cmake_file.write_text(content)

    configure(source_dir, "build")

    build_ninja = source_dir / "build.ninja"
    ninja_content = build_ninja.read_text()
    # The -Imyinclude should appear for the calculator executable too
    assert "-Imyinclude" in ninja_content


def test_target_include_directories_absolute_external_kept_in_ninja(
    tmp_path: Path,
) -> None:
    """Absolute include paths outside the project root should stay absolute."""
    source_dir = tmp_path / "hello"
    copy_unignored_tree(EXAMPLES_DIR / "hello", source_dir)

    cmake_file = source_dir / "CMakeLists.txt"
    content = cmake_file.read_text()
    content = content.replace(
        "add_executable(hello main.c subfolder/main.c)",
        "add_executable(hello main.c subfolder/main.c)\n"
        "target_include_directories(hello PRIVATE /usr/include/foo)",
    )
    cmake_file.write_text(content)

    configure(source_dir, "build")

    build_ninja = source_dir / "build.ninja"
    ninja_content = build_ninja.read_text()
    assert "-I/usr/include/foo" in ninja_content


def test_target_include_directories_build_install_interface(capsys) -> None:
    """BUILD_INTERFACE entries should be used and INSTALL_INTERFACE ignored."""
    if os.name == "nt":
        current_source_dir = "C:/project/src"
        current_binary_dir = "C:/project/build"
        expected_public_include = str(Path("C:/project/include").resolve())
        expected_public_build = str(Path("C:/project/build").resolve())
        expected_private_src = str(Path("C:/project/src").resolve())
        ctx = BuildContext(source_dir=Path("C:/project"), build_dir=Path("C:/project/build"))
    else:
        current_source_dir = "/project/src"
        current_binary_dir = "/project/build"
        expected_public_include = "/project/include"
        expected_public_build = "/project/build"
        expected_private_src = "/project/src"
        ctx = BuildContext(source_dir=Path("/project"), build_dir=Path("/project/build"))

    ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] = current_source_dir
    ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = current_binary_dir
    ctx.variables["CMAKE_INSTALL_INCLUDEDIR"] = "include"

    commands = [
        Command(name="add_library", args=["box2d", "lib.c"], line=1),
        Command(
            name="target_include_directories",
            args=[
                "box2d",
                "PUBLIC",
                "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../include>",
                "$<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}>",
                "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>",
                "PRIVATE",
                "${CMAKE_CURRENT_SOURCE_DIR}",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    lib = ctx.get_library("box2d")
    assert lib is not None
    assert expected_public_include in lib.public_include_directories
    assert expected_public_build in lib.public_include_directories
    assert expected_private_src in lib.include_directories
    assert all("include" != p for p in lib.public_include_directories)

    captured = capsys.readouterr()
    assert "generator expressions in target_include_directories are not yet supported" not in captured.err
