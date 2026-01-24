"""Tests for install command."""

from pathlib import Path
import os

from cninja.generator import BuildContext, process_commands, generate_ninja
from cninja.parser import Command


def test_install_targets(tmp_path: Path) -> None:
    """Test that install(TARGETS ...) correctly creates install targets in Ninja."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    # Mock HOME environment variable for the test to have a predictable path
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()

    # We need to monkeypatch Path.home() or just accept that it will use the real one.
    # Actually, our implementation uses Path.home() / ".local" / "bin" as default.
    # Let's test explicit DESTINATION first as it's easier.

    dest_path = tmp_path / "install_dir"

    commands = [
        Command(name="add_executable", args=["myapp", "main.cpp"], line=1),
        Command(
            name="install",
            args=["TARGETS", "myapp", "DESTINATION", str(dest_path)],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    assert len(ctx.install_targets) == 1
    assert ctx.install_targets[0].targets == ["myapp"]
    assert ctx.install_targets[0].destination == str(dest_path)

    # Test propagation to Ninja file
    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    ninja_content = ninja_path.read_text()

    # Check for install_file rule
    assert "rule install_file" in ninja_content

    # Check for individual install build statement
    # src is $builddir/myapp
    expected_dest = f"{dest_path}/myapp"
    assert "install_file" in ninja_content
    assert str(expected_dest) in ninja_content
    assert "$builddir/myapp" in ninja_content
    assert f"out_dir = {dest_path}" in ninja_content

    # Check for phony install target
    assert "build install: phony" in ninja_content
    assert str(expected_dest) in ninja_content
