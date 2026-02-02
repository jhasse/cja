"""Tests for set command."""

from pathlib import Path

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


def test_set_basic() -> None:
    """Test basic set command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="set", args=["MY_VAR", "hello"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["MY_VAR"] == "hello"


def test_set_multiple_values() -> None:
    """Test set with multiple values (creates semicolon-separated string)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="set", args=["MY_LIST", "a", "b", "c"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "a;b;c"


def test_set_unset() -> None:
    """Test that set with no value unsets the variable."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_VAR"] = "old_value"
    commands = [Command(name="set", args=["MY_VAR"], line=1)]
    process_commands(commands, ctx)
    assert "MY_VAR" not in ctx.variables


def test_set_with_cache() -> None:
    """Test set with CACHE keyword (should ignore CACHE and set value)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="set",
            args=["MY_VAR", "value", "CACHE", "STRING", "description"],
            line=1,
        )
    ]
    process_commands(commands, ctx)
    assert ctx.variables["MY_VAR"] == "value"


def test_set_with_parent_scope() -> None:
    """Test set with PARENT_SCOPE at top level (no effect, there's no parent)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="set", args=["MY_VAR", "value", "PARENT_SCOPE"], line=1)]
    process_commands(commands, ctx)
    # At top level, PARENT_SCOPE has no effect since there's no parent scope
    assert "MY_VAR" not in ctx.variables


def test_set_with_cache_and_force() -> None:
    """Test set with CACHE and FORCE keywords."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="set",
            args=["MY_VAR", "value", "CACHE", "STRING", "desc", "FORCE"],
            line=1,
        )
    ]
    process_commands(commands, ctx)
    assert ctx.variables["MY_VAR"] == "value"


def test_unset_cache() -> None:
    """Test unset(CACHE) removes cache variable tracking."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.cache_variables.add("CACHED")
    ctx.variables["CACHED"] = "1"
    commands = [
        Command(name="unset", args=["CACHED", "CACHE"], line=1),
    ]
    process_commands(commands, ctx)

    assert "CACHED" not in ctx.cache_variables
    assert ctx.variables["CACHED"] == "1"


def test_set_expands_variable_name() -> None:
    """Test set with variable name expansion."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["VAR_NAME", "FOO"], line=1),
        Command(name="set", args=["${VAR_NAME}", "bar"], line=2),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["FOO"] == "bar"
