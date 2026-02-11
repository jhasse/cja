"""Tests for find_package(Foo) using CMAKE_MODULE_PATH."""

from pathlib import Path
import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_find_package_module_path(tmp_path: Path) -> None:
    """Test find_package(Foo) looking for FindFoo.cmake in CMAKE_MODULE_PATH."""
    # Create a custom module directory
    cmake_modules = tmp_path / "cmake"
    cmake_modules.mkdir()

    # Create FindFoo.cmake
    find_foo = cmake_modules / "FindFoo.cmake"
    find_foo.write_text('set(Foo_FOUND TRUE)\nset(Foo_VERSION "1.2.3")')

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    # Set CMAKE_MODULE_PATH
    commands = [
        Command(name="set", args=["CMAKE_MODULE_PATH", str(cmake_modules)], line=1),
        Command(name="find_package", args=["Foo"], line=2),
    ]

    process_commands(commands, ctx)

    assert ctx.variables["Foo_FOUND"] == "TRUE"
    assert ctx.variables["Foo_VERSION"] == "1.2.3"


def test_find_package_module_path_relative(tmp_path: Path) -> None:
    """Test find_package(Foo) with relative CMAKE_MODULE_PATH."""
    # Create a custom module directory
    cmake_modules = tmp_path / "cmake"
    cmake_modules.mkdir()

    # Create FindFoo.cmake
    find_foo = cmake_modules / "FindFoo.cmake"
    find_foo.write_text("set(Foo_FOUND TRUE)")

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    # Set CMAKE_MODULE_PATH to a relative path
    commands = [
        Command(name="set", args=["CMAKE_MODULE_PATH", "cmake"], line=1),
        Command(name="find_package", args=["Foo"], line=2),
    ]

    process_commands(commands, ctx)

    assert ctx.variables["Foo_FOUND"] == "TRUE"


def test_find_package_not_found_in_module_path(tmp_path: Path) -> None:
    """Test find_package(Bar) when FindBar.cmake is not in CMAKE_MODULE_PATH."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(name="set", args=["CMAKE_MODULE_PATH", "nonexistent"], line=1),
        Command(name="find_package", args=["Bar"], line=2),
    ]

    process_commands(commands, ctx)

    assert ctx.variables["Bar_FOUND"] == "FALSE"


def test_find_package_required_not_found_in_module_path(tmp_path: Path) -> None:
    """Test find_package(Bar REQUIRED) when FindBar.cmake is not found."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(name="find_package", args=["Bar", "REQUIRED"], line=1),
    ]

    with pytest.raises(SystemExit):
        process_commands(commands, ctx)
