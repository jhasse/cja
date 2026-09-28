"""Tests for check_include_file and check_include_files commands."""

from pathlib import Path

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_check_include_file_found() -> None:
    """Test check_include_file with a header that exists."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_include_file",
            args=["stdio.h", "HAVE_STDIO_H"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert ctx.variables.get("HAVE_STDIO_H") == "1"


def test_check_include_file_not_found() -> None:
    """Test check_include_file with a header that doesn't exist."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_include_file",
            args=["nonexistent_header_xyz_12345.h", "HAVE_FAKE_H"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert ctx.variables.get("HAVE_FAKE_H") == ""


def test_check_include_file_with_flags() -> None:
    """Test check_include_file's optional flags argument is accepted."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_include_file",
            args=["stdio.h", "HAVE_STDIO_H", "-DCHECK_INCLUDE_FILE_TEST"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert ctx.variables.get("HAVE_STDIO_H") == "1"


def test_include_check_include_file_module(tmp_path: Path) -> None:
    """Test that include(CheckIncludeFile) is recognized and check_include_file works."""
    from cja.generator import configure

    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "include(CheckIncludeFile)\ncheck_include_file(stdio.h HAVE_STDIO_H)\n"
    )
    ctx = configure(source_dir, "build", quiet=True)
    assert ctx.variables.get("HAVE_STDIO_H") == "1"


def test_check_include_files_found() -> None:
    """Test check_include_files with a header that exists."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_include_files",
            args=["stdio.h", "HAVE_STDIO_H"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert ctx.variables.get("HAVE_STDIO_H") == "1"


def test_check_include_files_not_found() -> None:
    """Test check_include_files with a header that doesn't exist."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_include_files",
            args=["nonexistent_header_xyz_12345.h", "HAVE_FAKE_H"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert ctx.variables.get("HAVE_FAKE_H") == ""


def test_check_include_files_semicolon_list() -> None:
    """Test check_include_files with a semicolon-separated list of headers."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_include_files",
            args=["stdio.h;stdlib.h", "HAVE_STDIO_STDLIB"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert ctx.variables.get("HAVE_STDIO_STDLIB") == "1"


def test_include_check_include_files_module(tmp_path: Path) -> None:
    """Test that include(CheckIncludeFiles) is recognized and check_include_files works."""
    from cja.generator import configure

    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "include(CheckIncludeFiles)\ncheck_include_files(stdio.h HAVE_STDIO_H)\n"
    )
    ctx = configure(source_dir, "build", quiet=True)
    assert ctx.variables.get("HAVE_STDIO_H") == "1"
