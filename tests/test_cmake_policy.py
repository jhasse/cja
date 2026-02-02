"""Tests for CMAKE_POLICY_DEFAULT and cmake_policy handling."""

from pathlib import Path

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


def test_cmake_policy_default_new() -> None:
    """Test that CMAKE_POLICY_DEFAULT_CMPxxxx NEW is silently accepted."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["CMAKE_POLICY_DEFAULT_CMP0077", "NEW"], line=1),
    ]
    # Should not raise any errors or warnings
    process_commands(commands, ctx)
    # Variable should not be set in the context
    assert "CMAKE_POLICY_DEFAULT_CMP0077" not in ctx.variables


def test_cmake_policy_default_old_warns(capfd) -> None:
    """Test that CMAKE_POLICY_DEFAULT_CMPxxxx OLD prints a warning."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["CMAKE_POLICY_DEFAULT_CMP0077", "OLD"], line=1),
    ]
    process_commands(commands, ctx)

    # Check that a warning was printed
    captured = capfd.readouterr()
    assert "CMAKE_POLICY_DEFAULT_CMP0077" in captured.err
    assert "OLD" in captured.err
    assert "NEW behavior" in captured.err

    # Variable should not be set in the context
    assert "CMAKE_POLICY_DEFAULT_CMP0077" not in ctx.variables


def test_cmake_policy_default_multiple_policies() -> None:
    """Test multiple policy settings."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["CMAKE_POLICY_DEFAULT_CMP0077", "NEW"], line=1),
        Command(name="set", args=["CMAKE_POLICY_DEFAULT_CMP0135", "NEW"], line=2),
        Command(name="set", args=["CMAKE_POLICY_DEFAULT_CMP0091", "NEW"], line=3),
    ]
    # Should not raise any errors
    process_commands(commands, ctx)
    # None should be set
    assert "CMAKE_POLICY_DEFAULT_CMP0077" not in ctx.variables
    assert "CMAKE_POLICY_DEFAULT_CMP0135" not in ctx.variables
    assert "CMAKE_POLICY_DEFAULT_CMP0091" not in ctx.variables


def test_cmake_policy_default_with_cache() -> None:
    """Test CMAKE_POLICY_DEFAULT with CACHE keyword."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="set",
            args=["CMAKE_POLICY_DEFAULT_CMP0077", "NEW", "CACHE", "STRING", "Policy"],
            line=1,
        ),
    ]
    # Should not raise any errors
    process_commands(commands, ctx)
    # Variable should not be set
    assert "CMAKE_POLICY_DEFAULT_CMP0077" not in ctx.variables


def test_regular_cmake_policy_var() -> None:
    """Test that regular CMAKE_POLICY variables (not DEFAULT) work normally."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["CMAKE_POLICY_VERSION", "3.20"], line=1),
    ]
    process_commands(commands, ctx)
    # Regular CMAKE_POLICY variables should be set normally
    assert ctx.variables["CMAKE_POLICY_VERSION"] == "3.20"


def test_cmake_policy_default_different_numbers() -> None:
    """Test various CMP policy numbers."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["CMAKE_POLICY_DEFAULT_CMP0001", "NEW"], line=1),
        Command(name="set", args=["CMAKE_POLICY_DEFAULT_CMP0042", "NEW"], line=2),
        Command(name="set", args=["CMAKE_POLICY_DEFAULT_CMP0135", "NEW"], line=3),
        Command(name="set", args=["CMAKE_POLICY_DEFAULT_CMP9999", "NEW"], line=4),
    ]
    # Should handle all policy numbers
    process_commands(commands, ctx)
    assert "CMAKE_POLICY_DEFAULT_CMP0001" not in ctx.variables
    assert "CMAKE_POLICY_DEFAULT_CMP0042" not in ctx.variables
    assert "CMAKE_POLICY_DEFAULT_CMP0135" not in ctx.variables
    assert "CMAKE_POLICY_DEFAULT_CMP9999" not in ctx.variables


def test_cmake_policy_default_continues_execution() -> None:
    """Test that execution continues after CMAKE_POLICY_DEFAULT."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["BEFORE", "value1"], line=1),
        Command(name="set", args=["CMAKE_POLICY_DEFAULT_CMP0077", "NEW"], line=2),
        Command(name="set", args=["AFTER", "value2"], line=3),
    ]
    process_commands(commands, ctx)
    # Both regular variables should be set
    assert ctx.variables["BEFORE"] == "value1"
    assert ctx.variables["AFTER"] == "value2"
    # Policy variable should not be set
    assert "CMAKE_POLICY_DEFAULT_CMP0077" not in ctx.variables


def test_cmake_policy_default_in_function() -> None:
    """Test CMAKE_POLICY_DEFAULT inside a function."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="function", args=["my_func"], line=1),
        Command(name="set", args=["CMAKE_POLICY_DEFAULT_CMP0077", "NEW"], line=2),
        Command(name="set", args=["FUNC_VAR", "value"], line=3),
        Command(name="endfunction", args=[], line=4),
        Command(name="my_func", args=[], line=5),
    ]
    process_commands(commands, ctx)
    # FUNC_VAR should not be in outer scope (function scope)
    assert "FUNC_VAR" not in ctx.variables
    # Policy variable definitely should not be set
    assert "CMAKE_POLICY_DEFAULT_CMP0077" not in ctx.variables


def test_cmake_policy_default_in_macro() -> None:
    """Test CMAKE_POLICY_DEFAULT inside a macro."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="macro", args=["my_macro"], line=1),
        Command(name="set", args=["CMAKE_POLICY_DEFAULT_CMP0077", "NEW"], line=2),
        Command(name="set", args=["MACRO_VAR", "value"], line=3),
        Command(name="endmacro", args=[], line=4),
        Command(name="my_macro", args=[], line=5),
    ]
    process_commands(commands, ctx)
    # MACRO_VAR should be in outer scope (macros don't create scope)
    assert ctx.variables["MACRO_VAR"] == "value"
    # Policy variable should not be set
    assert "CMAKE_POLICY_DEFAULT_CMP0077" not in ctx.variables


def test_cmake_policy_default_empty_value() -> None:
    """Test CMAKE_POLICY_DEFAULT with no value."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["CMAKE_POLICY_DEFAULT_CMP0077"], line=1),
    ]
    # Should not crash
    process_commands(commands, ctx)
    # Variable should not be set
    assert "CMAKE_POLICY_DEFAULT_CMP0077" not in ctx.variables


def test_cmake_policy_set_new() -> None:
    """Test cmake_policy(SET ... NEW) is silently accepted."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="cmake_policy", args=["SET", "CMP0077", "NEW"], line=1),
    ]
    process_commands(commands, ctx)
    # Should not set any variables
    assert "CMP0077" not in ctx.variables


def test_cmake_policy_set_old_warns(capfd) -> None:
    """Test cmake_policy(SET ... OLD) prints a warning."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="cmake_policy", args=["SET", "CMP0077", "OLD"], line=1),
    ]
    process_commands(commands, ctx)
    captured = capfd.readouterr()
    assert "CMP0077" in captured.err
    assert "OLD" in captured.err
    assert "NEW behavior" in captured.err


def test_cmake_policy_get() -> None:
    """Test cmake_policy(GET ...)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="cmake_policy", args=["GET", "CMP0077", "MY_VAR"], line=1),
    ]
    process_commands(commands, ctx)
    # cninja always uses NEW behavior
    assert ctx.variables["MY_VAR"] == "NEW"


def test_cmake_policy_other_subcommands() -> None:
    """Test other cmake_policy subcommands are accepted."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="cmake_policy", args=["PUSH"], line=1),
        Command(name="cmake_policy", args=["VERSION", "3.20"], line=2),
        Command(name="cmake_policy", args=["POP"], line=3),
    ]
    # Should not raise any errors
    process_commands(commands, ctx)
