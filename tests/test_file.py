"""Tests for file command."""

from pathlib import Path
from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_file_glob(tmp_path: Path) -> None:
    """Test file(GLOB ...) command."""
    # Create some files
    (tmp_path / "file1.cpp").touch()
    (tmp_path / "file2.cpp").touch()
    (tmp_path / "other.txt").touch()

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="file", args=["GLOB", "src_files", "*.cpp"], line=1),
    ]
    process_commands(commands, ctx)

    assert "src_files" in ctx.variables
    # Values are semicolon separated absolute paths (since we use py_glob on full paths)
    files = ctx.variables["src_files"].split(";")
    assert len(files) == 2
    assert any(f.endswith("file1.cpp") for f in files)
    assert any(f.endswith("file2.cpp") for f in files)
    assert not any(f.endswith("other.txt") for f in files)


def test_file_glob_with_target(tmp_path: Path) -> None:
    """Test using file(GLOB ...) results in add_executable."""
    (tmp_path / "main.cpp").touch()
    (tmp_path / "util.cpp").touch()

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="file", args=["GLOB", "SOURCES", "*.cpp"], line=1),
        Command(name="add_executable", args=["myapp", "${SOURCES}"], line=2),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert len(exe.sources) == 2
    assert any(s.endswith("main.cpp") for s in exe.sources)
    assert any(s.endswith("util.cpp") for s in exe.sources)


def test_file_write_creates_parent_dir(tmp_path: Path) -> None:
    """file(WRITE ...) should create parent directories."""
    source_dir = Path.cwd() / f"tmp_file_write_{tmp_path.name}"
    build_dir = source_dir / "build"
    source_dir.mkdir(parents=True, exist_ok=True)
    try:
        ctx = BuildContext(source_dir=source_dir, build_dir=build_dir)
        commands = [
            Command(
                name="file",
                args=["WRITE", "build/nested/out.txt", "hello"],
                line=1,
            ),
        ]
        process_commands(commands, ctx)

        assert (build_dir / "nested" / "out.txt").read_text() == "hello"
    finally:
        import shutil

        shutil.rmtree(source_dir, ignore_errors=True)
