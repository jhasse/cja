"""Tests for return() command in functions."""

from pathlib import Path

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_return_exits_function() -> None:
    """Test that return() exits the function early."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="function", args=["my_func"], line=1),
        Command(name="set", args=["BEFORE", "yes", "PARENT_SCOPE"], line=2),
        Command(name="return", args=[], line=3),
        Command(name="set", args=["AFTER", "yes", "PARENT_SCOPE"], line=4),
        Command(name="endfunction", args=[], line=5),
        Command(name="my_func", args=[], line=6),
    ]
    process_commands(commands, ctx)

    # BEFORE should be set, AFTER should not (return exits before it)
    assert ctx.variables["BEFORE"] == "yes"
    assert "AFTER" not in ctx.variables


def test_return_in_conditional() -> None:
    """Test return() inside a conditional."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["SHOULD_RETURN"] = "TRUE"
    commands = [
        Command(name="function", args=["conditional_return"], line=1),
        Command(name="if", args=["SHOULD_RETURN"], line=2),
        Command(name="set", args=["EARLY", "yes", "PARENT_SCOPE"], line=3),
        Command(name="return", args=[], line=4),
        Command(name="endif", args=[], line=5),
        Command(name="set", args=["LATE", "yes", "PARENT_SCOPE"], line=6),
        Command(name="endfunction", args=[], line=7),
        Command(name="conditional_return", args=[], line=8),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["EARLY"] == "yes"
    assert "LATE" not in ctx.variables


def test_return_preserves_parent_scope() -> None:
    """Test that return() still applies PARENT_SCOPE changes made before it."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="function", args=["multi_set"], line=1),
        Command(name="set", args=["VAR1", "one", "PARENT_SCOPE"], line=2),
        Command(name="set", args=["VAR2", "two", "PARENT_SCOPE"], line=3),
        Command(name="return", args=[], line=4),
        Command(name="set", args=["VAR3", "three", "PARENT_SCOPE"], line=5),
        Command(name="endfunction", args=[], line=6),
        Command(name="multi_set", args=[], line=7),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["VAR1"] == "one"
    assert ctx.variables["VAR2"] == "two"
    assert "VAR3" not in ctx.variables


def test_return_exits_included_cmake_file(tmp_path: Path) -> None:
    """return() in include() should stop processing included file only."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "inc.cmake").write_text(
        "set(BEFORE yes)\nreturn()\nset(AFTER yes)\n"
    )

    ctx = BuildContext(source_dir=source_dir, build_dir=tmp_path / "build")
    commands = [
        Command(name="include", args=["inc.cmake"], line=1),
        Command(name="set", args=["OUTER", "yes"], line=2),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["BEFORE"] == "yes"
    assert "AFTER" not in ctx.variables
    assert ctx.variables["OUTER"] == "yes"
