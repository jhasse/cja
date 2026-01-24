"""Integration tests for cninja."""

import subprocess
from pathlib import Path

import pytest

from cninja import configure


EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def test_hello_example(tmp_path: Path) -> None:
    """Test building the hello example project."""
    source_dir = EXAMPLES_DIR / "hello"
    build_dir = tmp_path / "build"

    # Configure
    configure(source_dir, build_dir)

    # Check build.ninja was created
    build_ninja = build_dir / "build.ninja"
    assert build_ninja.exists()

    # Build with ninja
    result = subprocess.run(
        ["ninja"],
        cwd=build_dir,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ninja failed: {result.stderr}"

    # Check executable was created
    hello_exe = build_dir / "hello"
    assert hello_exe.exists()

    # Run the executable and check output
    result = subprocess.run(
        [str(hello_exe)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "Hello, World!"


def test_libmath_example(tmp_path: Path) -> None:
    """Test building the libmath example with static library."""
    source_dir = EXAMPLES_DIR / "libmath"
    build_dir = tmp_path / "build"

    # Configure
    configure(source_dir, build_dir)

    # Check build.ninja was created
    build_ninja = build_dir / "build.ninja"
    assert build_ninja.exists()

    # Build with ninja
    result = subprocess.run(
        ["ninja"],
        cwd=build_dir,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ninja failed: {result.stderr}"

    # Check library and executable were created
    assert (build_dir / "libmath.a").exists()
    assert (build_dir / "calculator").exists()

    # Run the executable and check output
    result = subprocess.run(
        [str(build_dir / "calculator")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "3 + 4 = 7" in result.stdout
    assert "3 * 4 = 12" in result.stdout
