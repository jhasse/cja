"""Tests for target_sources command."""

from pathlib import Path

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


def test_target_sources_executable() -> None:
    """Test target_sources adds sources to executable."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.c"], line=1),
        Command(name="target_sources", args=["myapp", "PRIVATE", "extra.c", "util.c"], line=2),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "main.c" in exe.sources
    assert "extra.c" in exe.sources
    assert "util.c" in exe.sources


def test_target_sources_library() -> None:
    """Test target_sources adds sources to library."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["mylib", "STATIC", "lib.c"], line=1),
        Command(name="target_sources", args=["mylib", "PUBLIC", "extra.c"], line=2),
    ]
    process_commands(commands, ctx)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert "lib.c" in lib.sources
    assert "extra.c" in lib.sources


def test_target_sources_multiple_visibility() -> None:
    """Test target_sources with multiple visibility keywords."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.c"], line=1),
        Command(name="target_sources", args=["myapp", "PUBLIC", "pub.c", "PRIVATE", "priv.c"], line=2),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "main.c" in exe.sources
    assert "pub.c" in exe.sources
    assert "priv.c" in exe.sources


def test_target_sources_no_visibility() -> None:
    """Test target_sources without visibility keywords."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.c"], line=1),
        Command(name="target_sources", args=["myapp", "extra.c"], line=2),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "main.c" in exe.sources
    assert "extra.c" in exe.sources
