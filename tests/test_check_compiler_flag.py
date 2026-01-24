"""Tests for check_cxx_compiler_flag and check_c_compiler_flag commands."""

from pathlib import Path

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


def test_check_cxx_compiler_flag_supported() -> None:
    """Test check_cxx_compiler_flag with a commonly supported flag."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="check_cxx_compiler_flag", args=["-Wall", "HAS_WALL"], line=1),
    ]
    process_commands(commands, ctx)

    assert "HAS_WALL" in ctx.variables
    # -Wall should be supported by gcc/clang
    assert ctx.variables["HAS_WALL"] == "1"


def test_check_cxx_compiler_flag_unsupported() -> None:
    """Test check_cxx_compiler_flag with an unsupported flag."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_cxx_compiler_flag",
            args=["--this-flag-does-not-exist-12345", "HAS_FAKE_FLAG"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert "HAS_FAKE_FLAG" in ctx.variables
    # This flag should not be supported
    assert ctx.variables["HAS_FAKE_FLAG"] == ""


def test_check_c_compiler_flag_supported() -> None:
    """Test check_c_compiler_flag with a commonly supported flag."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="check_c_compiler_flag", args=["-Wall", "HAS_WALL"], line=1),
    ]
    process_commands(commands, ctx)

    assert "HAS_WALL" in ctx.variables
    # -Wall should be supported by gcc/clang
    assert ctx.variables["HAS_WALL"] == "1"


def test_check_c_compiler_flag_unsupported() -> None:
    """Test check_c_compiler_flag with an unsupported flag."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_c_compiler_flag",
            args=["--this-flag-does-not-exist-12345", "HAS_FAKE_FLAG"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert "HAS_FAKE_FLAG" in ctx.variables
    # This flag should not be supported
    assert ctx.variables["HAS_FAKE_FLAG"] == ""
