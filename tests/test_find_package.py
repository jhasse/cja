"""Tests for find_package command."""

import subprocess
from pathlib import Path

import pytest

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


def has_pkg_config_gtest() -> bool:
    """Check if pkg-config can find gtest."""
    try:
        result = subprocess.run(
            ["pkg-config", "--exists", "gtest"],
            capture_output=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


@pytest.mark.skipif(not has_pkg_config_gtest(), reason="gtest not found via pkg-config")
def test_find_package_gtest_found() -> None:
    """Test find_package(GTest) when gtest is available."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["GTest"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["GTest_FOUND"] == "TRUE"
    assert ctx.variables["GTEST_FOUND"] == "TRUE"
    assert "GTEST_LIBRARIES" in ctx.variables


def test_find_package_unknown() -> None:
    """Test find_package with unknown package."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["UnknownPackage123"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["UnknownPackage123_FOUND"] == "FALSE"


def test_find_package_unknown_required() -> None:
    """Test find_package with REQUIRED for unknown package."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["UnknownPackage123", "REQUIRED"], line=1)]

    with pytest.raises(FileNotFoundError, match="Could not find package"):
        process_commands(commands, ctx)


def test_find_package_gtest_with_if() -> None:
    """Test find_package(GTest) used in if condition."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["GTest"], line=1),
        Command(name="if", args=["GTest_FOUND"], line=2),
        Command(name="set", args=["RESULT", "found"], line=3),
        Command(name="else", args=[], line=4),
        Command(name="set", args=["RESULT", "not_found"], line=5),
        Command(name="endif", args=[], line=6),
    ]
    process_commands(commands, ctx)

    # Result depends on whether gtest is installed
    if has_pkg_config_gtest():
        assert ctx.variables["RESULT"] == "found"
    else:
        assert ctx.variables["RESULT"] == "not_found"


def test_find_package_threads() -> None:
    """Test find_package(Threads) sets variables and imported target."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["Threads"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["Threads_FOUND"] == "TRUE"
    assert ctx.variables["CMAKE_THREAD_LIBS_INIT"] == "-pthread"
    assert "Threads::Threads" in ctx.imported_targets
    assert ctx.imported_targets["Threads::Threads"] == "-pthread"


def test_find_package_threads_link() -> None:
    """Test that linking against Threads::Threads adds -pthread."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["Threads"], line=1),
        Command(name="add_executable", args=["myapp", "main.c"], line=2),
        Command(name="target_link_libraries", args=["myapp", "Threads::Threads"], line=3),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "Threads::Threads" in exe.link_libraries
