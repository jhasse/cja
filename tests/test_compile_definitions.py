"""Tests for add_compile_definitions command."""

from pathlib import Path

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_add_compile_definitions() -> None:
    """Test that add_compile_definitions adds -D flags to all targets."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_compile_definitions", args=["DEBUG_MODE"], line=1),
        Command(name="add_compile_definitions", args=["VERSION=1.0"], line=2),
        Command(name="add_executable", args=["myapp", "main.cpp"], line=3),
    ]
    process_commands(commands, ctx)

    assert ctx.compile_definitions == ["DEBUG_MODE", "VERSION=1.0"]
    assert len(ctx.executables) == 1


def test_add_compile_definitions_with_variables() -> None:
    """Test that add_compile_definitions expands variables."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_DEF"] = "CUSTOM_FLAG"
    commands = [
        Command(name="add_compile_definitions", args=["${MY_DEF}"], line=1),
    ]
    process_commands(commands, ctx)

    assert ctx.compile_definitions == ["CUSTOM_FLAG"]


def test_multiple_definitions() -> None:
    """Test adding multiple compile definitions at once."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_compile_definitions", args=["FOO", "BAR", "BAZ=123"], line=1),
    ]
    process_commands(commands, ctx)

    assert ctx.compile_definitions == ["FOO", "BAR", "BAZ=123"]


def test_add_definitions_strips_dash_d(tmp_path: Path) -> None:
    """Legacy add_definitions(-DFOO) should emit a single -DFOO flag."""
    from cja.generator import configure

    source_dir = tmp_path
    (source_dir / "main.c").write_text("int main(void) { return 0; }\n")
    (source_dir / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(AddDefsTest C)\n"
        "add_executable(myapp main.c)\n"
        "add_definitions(-DLUAJIT_OS=LUAJIT_OS_LINUX -D_FILE_OFFSET_BITS=64)\n"
    )

    configure(source_dir, "build")
    content = (source_dir / "build.ninja").read_text()
    assert "-DLUAJIT_OS=LUAJIT_OS_LINUX" in content
    assert "-D-DLUAJIT_OS" not in content
    assert "-D_FILE_OFFSET_BITS=64" in content
