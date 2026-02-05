"""Tests for write_basic_package_version_file."""

from pathlib import Path

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


def test_write_basic_package_version_file_uses_project_version(
    tmp_path: Path,
) -> None:
    """Falls back to PROJECT_VERSION when VERSION is omitted."""
    build_dir = tmp_path / "build"
    ctx = BuildContext(source_dir=tmp_path, build_dir=build_dir)
    ctx.variables["PROJECT_VERSION"] = "2.4.1"
    ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(build_dir)

    out_file = build_dir / "box2dConfigVersion.cmake"
    commands = [
        Command(
            name="write_basic_package_version_file",
            args=[str(out_file), "COMPATIBILITY", "SameMajorVersion"],
            line=1,
        )
    ]
    process_commands(commands, ctx)

    assert out_file.exists()
    content = out_file.read_text()
    assert 'set(PACKAGE_VERSION "2.4.1")' in content
