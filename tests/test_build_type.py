"""Tests for CMAKE_BUILD_TYPE support."""

import shutil
from pathlib import Path

from cja.generator import configure


EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def test_build_type_debug(tmp_path: Path) -> None:
    """Test CMAKE_BUILD_TYPE=Debug adds -g -O0 flags."""
    source_dir = tmp_path / "hello"
    shutil.copytree(EXAMPLES_DIR / "hello", source_dir)

    # Add CMAKE_BUILD_TYPE to CMakeLists.txt
    cmake_file = source_dir / "CMakeLists.txt"
    content = cmake_file.read_text()
    content = content.replace(
        "project(hello)",
        "project(hello)\nset(CMAKE_BUILD_TYPE Debug)",
    )
    cmake_file.write_text(content)

    configure(source_dir, "build")

    build_ninja = source_dir / "build.ninja"
    content = build_ninja.read_text()
    assert "-g" in content
    assert "-O0" in content


def test_build_type_release(tmp_path: Path) -> None:
    """Test CMAKE_BUILD_TYPE=Release adds -O3 -DNDEBUG flags."""
    source_dir = tmp_path / "hello"
    shutil.copytree(EXAMPLES_DIR / "hello", source_dir)

    cmake_file = source_dir / "CMakeLists.txt"
    content = cmake_file.read_text()
    content = content.replace(
        "project(hello)",
        "project(hello)\nset(CMAKE_BUILD_TYPE Release)",
    )
    cmake_file.write_text(content)

    configure(source_dir, "build")

    build_ninja = source_dir / "build.ninja"
    content = build_ninja.read_text()
    assert "-O3" in content
    assert "-DNDEBUG" in content


def test_build_type_relwithdebinfo(tmp_path: Path) -> None:
    """Test CMAKE_BUILD_TYPE=RelWithDebInfo adds -O2 -g -DNDEBUG flags."""
    source_dir = tmp_path / "hello"
    shutil.copytree(EXAMPLES_DIR / "hello", source_dir)

    cmake_file = source_dir / "CMakeLists.txt"
    content = cmake_file.read_text()
    content = content.replace(
        "project(hello)",
        "project(hello)\nset(CMAKE_BUILD_TYPE RelWithDebInfo)",
    )
    cmake_file.write_text(content)

    configure(source_dir, "build")

    build_ninja = source_dir / "build.ninja"
    content = build_ninja.read_text()
    assert "-O2" in content
    assert "-g" in content
    assert "-DNDEBUG" in content


def test_build_type_minsizerel(tmp_path: Path) -> None:
    """Test CMAKE_BUILD_TYPE=MinSizeRel adds -Os -DNDEBUG flags."""
    source_dir = tmp_path / "hello"
    shutil.copytree(EXAMPLES_DIR / "hello", source_dir)

    cmake_file = source_dir / "CMakeLists.txt"
    content = cmake_file.read_text()
    content = content.replace(
        "project(hello)",
        "project(hello)\nset(CMAKE_BUILD_TYPE MinSizeRel)",
    )
    cmake_file.write_text(content)

    configure(source_dir, "build")

    build_ninja = source_dir / "build.ninja"
    content = build_ninja.read_text()
    assert "-Os" in content
    assert "-DNDEBUG" in content


def test_build_type_default_debug(tmp_path: Path) -> None:
    """Test CMAKE_BUILD_TYPE defaults to Debug."""
    source_dir = tmp_path / "hello"
    shutil.copytree(EXAMPLES_DIR / "hello", source_dir)

    configure(source_dir, "build")

    build_ninja = source_dir / "build.ninja"
    content = build_ninja.read_text()
    # Default should be Debug
    assert "-g" in content
    assert "-O0" in content
