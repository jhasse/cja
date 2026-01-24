"""Tests for CLI argument handling."""

import shutil
import subprocess
from pathlib import Path

from cninja.cli import parse_define
from cninja.generator import configure


EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


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


def test_configure_with_variables(tmp_path: Path) -> None:
    """Test configure with variables passed via -D."""
    source_dir = tmp_path / "hello"
    shutil.copytree(EXAMPLES_DIR / "hello", source_dir)

    configure(source_dir, "build", variables={"CMAKE_BUILD_TYPE": "Release"})

    build_ninja = source_dir / "build.ninja"
    content = build_ninja.read_text()
    assert "-O3" in content
    assert "-DNDEBUG" in content


def test_cli_d_flag(tmp_path: Path) -> None:
    """Test cninja CLI with -D flag."""
    source_dir = tmp_path / "hello"
    shutil.copytree(EXAMPLES_DIR / "hello", source_dir)

    result = subprocess.run(
        ["uv", "run", "cninja", str(source_dir), "-DCMAKE_BUILD_TYPE=Debug"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0

    build_ninja = source_dir / "build.ninja"
    content = build_ninja.read_text()
    assert "-g" in content
    assert "-O0" in content


def test_cli_multiple_d_flags(tmp_path: Path) -> None:
    """Test cninja CLI with multiple -D flags."""
    source_dir = tmp_path / "hello"
    shutil.copytree(EXAMPLES_DIR / "hello", source_dir)

    result = subprocess.run(
        [
            "uv", "run", "cninja",
            str(source_dir),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DENABLE_TESTS=ON",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0

    build_ninja = source_dir / "build.ninja"
    content = build_ninja.read_text()
    assert "-O3" in content


def test_d_flag_overrides_cmake_set(tmp_path: Path) -> None:
    """Test that -D flag overrides set() in CMakeLists.txt."""
    source_dir = tmp_path / "hello"
    shutil.copytree(EXAMPLES_DIR / "hello", source_dir)

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
