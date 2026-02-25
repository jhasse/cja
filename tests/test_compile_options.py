"""Tests for add_compile_options command."""

from pathlib import Path

from cja.generator import BuildContext, configure, process_commands
from cja.parser import Command
from tests.helpers import copy_unignored_tree

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def test_add_compile_options_stored() -> None:
    """Test that add_compile_options stores flags in context."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_compile_options", args=["-Wall", "-Wextra"], line=1),
    ]
    process_commands(commands, ctx)

    assert "-Wall" in ctx.compile_options
    assert "-Wextra" in ctx.compile_options


def test_add_compile_options_in_ninja(tmp_path: Path) -> None:
    """Test that add_compile_options flags appear in generated ninja file."""
    source_dir = tmp_path / "hello"
    copy_unignored_tree(EXAMPLES_DIR / "hello", source_dir)

    # Add add_compile_options to CMakeLists.txt
    cmake_file = source_dir / "CMakeLists.txt"
    content = cmake_file.read_text()
    # Insert add_compile_options after project()
    content = content.replace(
        "project(hello)",
        "project(hello)\nadd_compile_options(-Wall -Wextra)"
    )
    cmake_file.write_text(content)

    configure(source_dir, "build")

    build_ninja = source_dir / "build.ninja"
    ninja_content = build_ninja.read_text()
    assert "-Wall" in ninja_content
    assert "-Wextra" in ninja_content


def test_add_compile_options_variable_expansion() -> None:
    """Test that add_compile_options expands variables."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_FLAGS"] = "-DFOO"
    commands = [
        Command(name="add_compile_options", args=["${MY_FLAGS}"], line=1),
    ]
    process_commands(commands, ctx)

    assert "-DFOO" in ctx.compile_options
