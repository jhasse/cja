"""Tests for find_package(OpenAL)."""

import subprocess
from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def has_openal() -> bool:
    """Check if pkg-config can find openal."""
    try:
        for candidate in ("openal", "openal-soft"):
            result = subprocess.run(
                ["pkg-config", "--exists", candidate], capture_output=True
            )
            if result.returncode == 0:
                return True
    except FileNotFoundError:
        pass
    return (
        Path("/usr/include/AL/al.h").exists()
        or Path("/usr/local/include/AL/al.h").exists()
        or Path("/opt/homebrew/include/AL/al.h").exists()
    )


@pytest.mark.skipif(not has_openal(), reason="OpenAL not found")
def test_find_package_openal_found() -> None:
    """Test find_package(OpenAL) when OpenAL is available."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["OpenAL"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["OPENAL_FOUND"] == "TRUE"
    assert ctx.variables["OpenAL_FOUND"] == "TRUE"
    assert "OPENAL_LIBRARY" in ctx.variables
    assert "OpenAL::OpenAL" in ctx.imported_targets


@pytest.mark.skipif(not has_openal(), reason="OpenAL not found")
def test_find_package_openal_imported_target() -> None:
    """Test find_package(OpenAL) creates OpenAL::OpenAL imported target."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["OpenAL"], line=1)]
    process_commands(commands, ctx)

    assert "OpenAL::OpenAL" in ctx.imported_targets
    target = ctx.imported_targets["OpenAL::OpenAL"]
    assert target.libs


@pytest.mark.skipif(not has_openal(), reason="OpenAL not found")
def test_find_package_openal_link() -> None:
    """Test that linking against OpenAL::OpenAL works."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["OpenAL"], line=1),
        Command(name="add_executable", args=["myapp", "main.c"], line=2),
        Command(
            name="target_link_libraries",
            args=["myapp", "OpenAL::OpenAL"],
            line=3,
        ),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "OpenAL::OpenAL" in exe.link_libraries


def test_find_package_openal_not_required() -> None:
    """Test find_package(OpenAL) without REQUIRED does not raise when not found."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    # Simulate not found by checking variables after a clean run
    commands = [Command(name="find_package", args=["OpenAL"], line=1)]
    # Should not raise
    process_commands(commands, ctx)
    assert ctx.variables.get("OPENAL_FOUND") in ("TRUE", "FALSE")
