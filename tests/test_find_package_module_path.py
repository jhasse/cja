"""Tests for find_package(Foo) using CMAKE_MODULE_PATH."""

from pathlib import Path
import pytest

from cja.generator import BuildContext, generate_ninja, process_commands
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


def test_find_package_module_imported_target_links_as_external(tmp_path: Path) -> None:
    """Imported targets from Find modules should not become build artifacts."""
    cmake_modules = tmp_path / "cmake"
    cmake_modules.mkdir()

    include_dir = tmp_path / "thirdparty" / "include"
    include_dir.mkdir(parents=True)
    (include_dir / "foo.h").write_text("#pragma once\n")
    imported_lib = tmp_path / "thirdparty" / "libfoo.a"
    imported_lib.parent.mkdir(parents=True, exist_ok=True)
    imported_lib.touch()

    (cmake_modules / "FindFoo.cmake").write_text(
        "\n".join(
            [
                "add_library(Foo::foo UNKNOWN IMPORTED)",
                "set_target_properties(Foo::foo PROPERTIES IMPORTED_LOCATION \""
                + str(imported_lib)
                + "\")",
                "set_target_properties(Foo::foo PROPERTIES INTERFACE_INCLUDE_DIRECTORIES \""
                + str(include_dir)
                + "\")",
                "set(Foo_FOUND TRUE)",
            ]
        )
    )
    (tmp_path / "main.c").write_text("int main(void) { return 0; }\n")

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="set", args=["CMAKE_MODULE_PATH", str(cmake_modules)], line=1),
        Command(name="find_package", args=["Foo", "REQUIRED"], line=2),
        Command(name="add_executable", args=["app", "main.c"], line=3),
        Command(name="target_link_libraries", args=["app", "PRIVATE", "Foo::foo"], line=4),
    ]
    process_commands(commands, ctx)

    assert "Foo::foo" in ctx.imported_targets
    assert ctx.get_library("Foo::foo") is None

    ninja_file = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_file, "build")
    ninja_content = ninja_file.read_text()
    assert "libFoo::foo" not in ninja_content
    assert str(imported_lib) in ninja_content
