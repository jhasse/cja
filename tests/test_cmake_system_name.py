"""Tests for CMAKE_SYSTEM_NAME variable."""

import platform
from pathlib import Path
from cja.generator import configure


def test_cmake_system_name(tmp_path: Path) -> None:
    """Test that CMAKE_SYSTEM_NAME is set based on the platform."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text("project(test_sys_name)")

    ctx = configure(source_dir, "build")

    if platform.system() == "Darwin":
        expected_system_name = "Darwin"
    elif platform.system() == "Windows":
        expected_system_name = "Windows"
    else:
        expected_system_name = "Linux"
    assert ctx.variables["CMAKE_SYSTEM_NAME"] == expected_system_name


def test_cmake_host_system_processor(tmp_path: Path) -> None:
    """Test that CMAKE_HOST_SYSTEM_PROCESSOR is set."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text("project(test_host_processor)")

    ctx = configure(source_dir, "build")

    expected_processor = (
        platform.machine().strip() or platform.processor().strip() or "unknown"
    )
    assert ctx.variables["CMAKE_HOST_SYSTEM_PROCESSOR"] == expected_processor
