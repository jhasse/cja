"""Tests for target_sources command."""

from pathlib import Path

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_target_sources_executable() -> None:
    """Test target_sources adds sources to executable."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.c"], line=1),
        Command(
            name="target_sources",
            args=["myapp", "PRIVATE", "extra.c", "util.c"],
            line=2,
        ),
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


def test_target_sources_library_created_without_initial_sources() -> None:
    """target_sources should work after add_library(<name>) with no source list."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["mylib"], line=1),
        Command(name="target_sources", args=["mylib", "PRIVATE", "lib.c"], line=2),
    ]
    process_commands(commands, ctx)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert "lib.c" in lib.sources


def test_target_sources_multiple_visibility() -> None:
    """Test target_sources with multiple visibility keywords."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.c"], line=1),
        Command(
            name="target_sources",
            args=["myapp", "PUBLIC", "pub.c", "PRIVATE", "priv.c"],
            line=2,
        ),
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


def test_absolute_paths_handling() -> None:
    """Test that absolute paths are converted to relative if under source_dir."""
    source_root = Path("/home/user/project").absolute()
    ctx = BuildContext(source_dir=source_root, build_dir=source_root / "build")

    commands = [
        Command(
            name="add_executable", args=["myapp", str(source_root / "main.c")], line=1
        ),
        Command(
            name="target_sources",
            args=["myapp", str(source_root / "src/util.c"), "/other/path/external.c"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    # Path inside source_dir should be relative
    assert "main.c" in exe.sources
    assert "src/util.c" in exe.sources
    # Path outside source_dir should remain absolute
    assert "/other/path/external.c" in exe.sources
