"""Tests for CLI argument handling."""

import importlib.metadata
import subprocess
import platform
from pathlib import Path
import sys

import pytest

from cja.cli import parse_define
from cja.generator import configure
from tests.helpers import copy_unignored_tree


EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
EXE_EXT = ".exe" if platform.system() == "Windows" else ""


def test_parse_define_with_value() -> None:
    """Test parsing -D with explicit value."""
    assert parse_define("CMAKE_BUILD_TYPE=Release") == ("CMAKE_BUILD_TYPE", "Release")
    assert parse_define("FOO=bar") == ("FOO", "bar")
    assert parse_define("EMPTY=") == ("EMPTY", "")


def test_parse_define_without_value() -> None:
    """Test parsing -D without value defaults to ON."""
    assert parse_define("ENABLE_FEATURE") == ("ENABLE_FEATURE", "ON")


def test_parse_define_with_equals_in_value() -> None:
    """Test parsing -D with = in the value."""
    assert parse_define("FLAGS=-O2 -DFOO=1") == ("FLAGS", "-O2 -DFOO=1")


def test_cli_version_flag() -> None:
    """Test cja CLI --version flag."""
    result = subprocess.run(
        ["uv", "run", "cja", "--version"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip() == f"cja {importlib.metadata.version('cja')}"


def test_configure_with_variables(tmp_path: Path) -> None:
    """Test configure with variables passed via -D."""
    source_dir = tmp_path / "hello"
    copy_unignored_tree(EXAMPLES_DIR / "hello", source_dir)

    configure(source_dir, "build", variables={"CMAKE_BUILD_TYPE": "Release"})

    build_ninja = source_dir / "build.ninja"
    content = build_ninja.read_text()
    assert "-O3" in content
    assert "-DNDEBUG" in content


def test_cli_d_flag(tmp_path: Path) -> None:
    """Test cja CLI with -D flag."""
    source_dir = tmp_path / "hello"
    copy_unignored_tree(EXAMPLES_DIR / "hello", source_dir)

    result = subprocess.run(
        ["uv", "run", "cja", "-DCMAKE_BUILD_TYPE=Debug"],
        capture_output=True,
        text=True,
        cwd=source_dir,
    )
    assert result.returncode == 0

    build_ninja = source_dir / "build.ninja"
    content = build_ninja.read_text()
    assert "-g" in content
    assert "-O0" in content


def test_cli_multiple_d_flags(tmp_path: Path) -> None:
    """Test cja CLI with multiple -D flags."""
    source_dir = tmp_path / "hello"
    copy_unignored_tree(EXAMPLES_DIR / "hello", source_dir)

    result = subprocess.run(
        [
            "uv",
            "run",
            "cja",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DENABLE_TESTS=ON",
        ],
        capture_output=True,
        text=True,
        cwd=source_dir,
    )
    assert result.returncode == 0

    build_ninja = source_dir / "build.ninja"
    content = build_ninja.read_text()
    assert "-O3" in content


def test_d_flag_overrides_cmake_set(tmp_path: Path) -> None:
    """Test that -D flag overrides set() in CMakeLists.txt."""
    source_dir = tmp_path / "hello"
    copy_unignored_tree(EXAMPLES_DIR / "hello", source_dir)

    # Add CMAKE_BUILD_TYPE=Debug to CMakeLists.txt
    cmake_file = source_dir / "CMakeLists.txt"
    content = cmake_file.read_text()
    content = content.replace(
        "project(hello)",
        "project(hello)\nset(CMAKE_BUILD_TYPE Debug)",
    )
    cmake_file.write_text(content)

    # Override with -D flag to Release
    configure(source_dir, "build", variables={"CMAKE_BUILD_TYPE": "Release"})

    build_ninja = source_dir / "build.ninja"
    content = build_ninja.read_text()
    # Should have Release flags, not Debug
    assert "-O3" in content
    assert "-DNDEBUG" in content
    assert "-O0" not in content


def test_custom_build_dir_ninja_name(tmp_path: Path) -> None:
    """Test that -B custom-dir produces custom-dir.ninja."""
    source_dir = tmp_path / "hello"
    copy_unignored_tree(EXAMPLES_DIR / "hello", source_dir)

    configure(source_dir, "build-release")

    # Should create build-release.ninja, not build.ninja
    assert (source_dir / "build-release.ninja").exists()
    assert not (source_dir / "build.ninja").exists()


def test_build_subcommand(tmp_path: Path) -> None:
    """Test cja build subcommand."""
    source_dir = tmp_path / "hello"
    copy_unignored_tree(EXAMPLES_DIR / "hello", source_dir)

    result = subprocess.run(
        ["uv", "run", "cja", "build"],
        capture_output=True,
        text=True,
        cwd=source_dir,
    )
    assert result.returncode == 0

    # Should have created build.ninja and built the executable
    assert (source_dir / "build.ninja").exists()
    assert (source_dir / "build" / f"hello{EXE_EXT}").exists()


def test_build_subcommand_release(tmp_path: Path) -> None:
    """Test cja build --release subcommand."""
    source_dir = tmp_path / "hello"
    copy_unignored_tree(EXAMPLES_DIR / "hello", source_dir)

    result = subprocess.run(
        ["uv", "run", "cja", "build", "--release"],
        capture_output=True,
        text=True,
        cwd=source_dir,
    )
    assert result.returncode == 0

    # Should have created build-release.ninja with Release flags
    assert (source_dir / "build-release.ninja").exists()
    content = (source_dir / "build-release.ninja").read_text()
    assert "-O3" in content
    assert "-DNDEBUG" in content

    # Should have built the executable in build-release
    assert (source_dir / "build-release" / f"hello{EXE_EXT}").exists()


def test_build_subcommand_skips_configure_if_ninja_exists(tmp_path: Path) -> None:
    """Test cja build skips configure if ninja file already exists."""
    source_dir = tmp_path / "hello"
    copy_unignored_tree(EXAMPLES_DIR / "hello", source_dir)

    # First build - should configure
    result1 = subprocess.run(
        ["uv", "run", "cja", "build"],
        capture_output=True,
        text=True,
        cwd=source_dir,
    )
    assert result1.returncode == 0
    assert "Configured" in result1.stdout

    # Second build - should skip configure
    result2 = subprocess.run(
        ["uv", "run", "cja", "build"],
        capture_output=True,
        text=True,
        cwd=source_dir,
    )
    assert result2.returncode == 0
    assert "Configured" not in result2.stdout


@pytest.mark.skipif(
    sys.platform == "win32", reason="TODO: Fix test subcommand on Windows"
)
def test_test_subcommand(tmp_path: Path) -> None:
    """Test cja test subcommand."""
    source_dir = tmp_path
    (source_dir / "CMakeLists.txt").write_text(
        """
cmake_minimum_required(VERSION 3.10)
project(test_prj)
add_test(NAME mytest COMMAND echo "Hello from test")
"""
    )

    result = subprocess.run(
        ["uv", "run", "cja", "test"],
        capture_output=True,
        text=True,
        cwd=source_dir,
    )
    assert result.returncode == 0
    assert "Running mytest" in result.stdout
    assert "Hello from test" in result.stdout


def test_cli_make_directory(tmp_path: Path) -> None:
    """Test cja -E make_directory command."""
    dir_path = tmp_path / "new_dir" / "nested"
    assert not dir_path.exists()

    result = subprocess.run(
        ["uv", "run", "cja", "-E", "make_directory", str(dir_path)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert dir_path.exists()
    assert dir_path.is_dir()


def test_quiet_flag_suppresses_output(tmp_path: Path) -> None:
    """Test that --quiet suppresses warnings and status output."""
    source_dir = tmp_path / "hello"
    copy_unignored_tree(EXAMPLES_DIR / "hello", source_dir)

    result = subprocess.run(
        ["uv", "run", "cja", "--quiet"],
        capture_output=True,
        text=True,
        cwd=source_dir,
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_quiet_flag_via_api(tmp_path: Path) -> None:
    """Test that quiet=True suppresses output via the Python API."""
    source_dir = tmp_path / "hello"
    copy_unignored_tree(EXAMPLES_DIR / "hello", source_dir)

    import io
    from contextlib import redirect_stdout, redirect_stderr

    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        configure(source_dir, "build", quiet=True)

    assert stdout.getvalue() == ""
    assert stderr.getvalue() == ""


def test_run_subcommand(tmp_path: Path) -> None:
    """Test cja run subcommand."""
    source_dir = tmp_path
    (source_dir / "main.c").write_text("int main() { return 42; }")
    (source_dir / "CMakeLists.txt").write_text(
        """
cmake_minimum_required(VERSION 3.10)
project(run_prj)
add_executable(myexe main.c)
"""
    )

    result = subprocess.run(
        ["uv", "run", "cja", "run"],
        capture_output=True,
        text=True,
        cwd=source_dir,
    )
    assert result.returncode == 42
