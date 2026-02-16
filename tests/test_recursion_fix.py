"""Integration tests for fixing infinite recursion bugs."""

from pathlib import Path
from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_find_path_no_recursion(tmp_path: Path) -> None:
    """Test that find_path doesn't reset the command loop index."""
    # Create a dummy header file
    include_dir = tmp_path / "include"
    include_dir.mkdir()
    (include_dir / "test.h").touch()

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    # We use a sequence of commands. If find_path resets 'i' to a small value,
    # it will cause process_commands to repeat earlier commands or loop infinitely.
    # In our test, we'll check if the second command is executed exactly once.
    commands = [
        # Command 0
        Command(name="set", args=["COUNTER", "0"], line=1),
        # Command 1: Increment counter
        Command(name="math", args=["EXPR", "COUNTER", "${COUNTER} + 1"], line=2),
        # Command 2: find_path (the one that had the bug)
        Command(name="find_path", args=["MY_PATH", "test.h", str(include_dir)], line=3),
        # Command 3: Another command to ensure we continue
        Command(name="set", args=["FINISHED", "TRUE"], line=4),
    ]

    process_commands(commands, ctx)

    # If it recursed, COUNTER would be > 1
    assert ctx.variables["COUNTER"] == "1"
    assert ctx.variables["FINISHED"] == "TRUE"
    assert "MY_PATH" in ctx.variables


def test_install_no_recursion(tmp_path: Path) -> None:
    """Test that install doesn't reset the command loop index."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(name="set", args=["COUNTER", "0"], line=1),
        Command(name="math", args=["EXPR", "COUNTER", "${COUNTER} + 1"], line=2),
        # install(TARGETS ...) used to have 'i = 1'
        Command(
            name="install", args=["TARGETS", "myapp", "DESTINATION", "bin"], line=3
        ),
        Command(name="set", args=["FINISHED", "TRUE"], line=4),
    ]

    process_commands(commands, ctx)

    assert ctx.variables["COUNTER"] == "1"
    assert ctx.variables["FINISHED"] == "TRUE"


def test_set_source_files_properties_no_recursion(tmp_path: Path) -> None:
    """Test that set_source_files_properties doesn't reset the command loop index."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(name="set", args=["COUNTER", "0"], line=1),
        Command(name="math", args=["EXPR", "COUNTER", "${COUNTER} + 1"], line=2),
        # set_source_files_properties used to have 'i = 0' (inside the handler)
        Command(
            name="set_source_files_properties",
            args=["main.c", "PROPERTIES", "COMPILE_DEFINITIONS", "FOO"],
            line=3,
        ),
        Command(name="set", args=["FINISHED", "TRUE"], line=4),
    ]

    process_commands(commands, ctx)

    assert ctx.variables["COUNTER"] == "1"
    assert ctx.variables["FINISHED"] == "TRUE"
