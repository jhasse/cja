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
