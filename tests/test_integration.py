"""Integration tests for cja."""

import shutil
import subprocess
from pathlib import Path

from cja import configure


EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def test_hello_example(tmp_path: Path) -> None:
    """Test building the hello example project."""
    # Copy example to tmp_path since build.ninja is written in source dir
    source_dir = tmp_path / "hello"
    shutil.copytree(EXAMPLES_DIR / "hello", source_dir)

    # Configure
    configure(source_dir, "build")

    # Check build.ninja was created in source directory
    build_ninja = source_dir / "build.ninja"
    assert build_ninja.exists()

    # Build with ninja (run from source dir)
    result = subprocess.run(
        ["ninja"],
        cwd=source_dir,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ninja failed: {result.stderr}"

    # Check executable was created in build dir
    build_dir = source_dir / "build"
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
    # Copy example to tmp_path since build.ninja is written in source dir
    source_dir = tmp_path / "libmath"
    shutil.copytree(EXAMPLES_DIR / "libmath", source_dir)

    # Configure
    configure(source_dir, "build")

    # Check build.ninja was created in source directory
    build_ninja = source_dir / "build.ninja"
    assert build_ninja.exists()

    # Build with ninja (run from source dir)
    result = subprocess.run(
        ["ninja"],
        cwd=source_dir,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ninja failed: {result.stderr}"

    # Check library and executable were created in build dir
    build_dir = source_dir / "build"
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


def test_objlib_example(tmp_path: Path) -> None:
    """Test building the objlib example with OBJECT library."""
    # Copy example to tmp_path since build.ninja is written in source dir
    source_dir = tmp_path / "objlib"
    shutil.copytree(EXAMPLES_DIR / "objlib", source_dir)

    # Configure
    configure(source_dir, "build")

    # Check build.ninja was created in source directory
    build_ninja = source_dir / "build.ninja"
    assert build_ninja.exists()

    # Verify no .a file is created for OBJECT library
    content = build_ninja.read_text()
    assert "libutils.a" not in content

    # Build with ninja (run from source dir)
    result = subprocess.run(
        ["ninja"],
        cwd=source_dir,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ninja failed: {result.stderr}"

    # Check executable was created in build dir (but no .a file)
    build_dir = source_dir / "build"
    assert (build_dir / "app").exists()
    assert not (build_dir / "libutils.a").exists()

    # Run the executable and check output
    result = subprocess.run(
        [str(build_dir / "app")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Value: 42" in result.stdout
