"""Tests for target_sources command."""

import subprocess
import sys
from pathlib import Path

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_target_sources_executable() -> None:
    """Test target_sources adds sources to executable."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.c"], line=1),
        Command(
            name="target_sources",
            args=["myapp", "PRIVATE", "extra.c", "util.c"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "main.c" in exe.sources
    assert "extra.c" in exe.sources
    assert "util.c" in exe.sources


def test_target_sources_library() -> None:
    """Test target_sources adds sources to library."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["mylib", "STATIC", "lib.c"], line=1),
        Command(name="target_sources", args=["mylib", "PUBLIC", "extra.c"], line=2),
    ]
    process_commands(commands, ctx)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert "lib.c" in lib.sources
    assert "extra.c" in lib.sources


def test_target_sources_library_created_without_initial_sources() -> None:
    """target_sources should work after add_library(<name>) with no source list."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["mylib"], line=1),
        Command(name="target_sources", args=["mylib", "PRIVATE", "lib.c"], line=2),
    ]
    process_commands(commands, ctx)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert "lib.c" in lib.sources


def test_target_sources_interface_library() -> None:
    """add_library(<name> INTERFACE) should create an interface target."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["mylib", "INTERFACE"], line=1),
        Command(
            name="target_include_directories",
            args=["mylib", "INTERFACE", "include"],
            line=2,
        ),
    ]
    process_commands(commands, ctx, strict=True)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert lib.lib_type == "INTERFACE"
    assert lib.sources == []
    assert lib.public_include_directories


def test_target_sources_multiple_visibility() -> None:
    """Test target_sources with multiple visibility keywords."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.c"], line=1),
        Command(
            name="target_sources",
            args=["myapp", "PUBLIC", "pub.c", "PRIVATE", "priv.c"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "main.c" in exe.sources
    assert "pub.c" in exe.sources
    assert "priv.c" in exe.sources


def test_target_sources_no_visibility() -> None:
    """Test target_sources without visibility keywords."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.c"], line=1),
        Command(name="target_sources", args=["myapp", "extra.c"], line=2),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "main.c" in exe.sources
    assert "extra.c" in exe.sources


def test_absolute_paths_handling() -> None:
    """Test that absolute paths are converted to relative if under source_dir."""
    source_root = Path("/home/user/project").absolute()
    ctx = BuildContext(source_dir=source_root, build_dir=source_root / "build")

    commands = [
        Command(
            name="add_executable", args=["myapp", str(source_root / "main.c")], line=1
        ),
        Command(
            name="target_sources",
            args=["myapp", str(source_root / "src/util.c"), "/other/path/external.c"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    # Path inside source_dir should be relative
    assert "main.c" in exe.sources
    assert "src/util.c" in exe.sources
    # Path outside source_dir should remain absolute
    assert "/other/path/external.c" in exe.sources


def test_non_source_entries_not_compiled(tmp_path: Path) -> None:
    """Non-source files in target sources should not generate compile rules."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "lib.cpp").write_text("int f() { return 1; }\n")
    (source_dir / "README.rst").write_text("doc\n")
    (source_dir / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.15)\n"
        "project(non_source LANGUAGES CXX)\n"
        "add_library(mylib STATIC lib.cpp README.rst docs)\n"
    )

    from cja.generator import configure

    configure(source_dir, "build")
    ninja = (source_dir / "build.ninja").read_text()
    assert "README.rst" not in ninja
    assert "docs" not in ninja


def test_add_library_source_genex_list_from_variable() -> None:
    """Source-list genex should evaluate, then split into concrete sources."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["EXTRA_SRCS", "$<$<BOOL:ON>:a.cpp;b.cpp>"], line=1),
        Command(
            name="add_library",
            args=["mylib", "STATIC", "base.cpp", "${EXTRA_SRCS}"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert lib.sources == ["base.cpp", "a.cpp", "b.cpp"]


def test_duplicate_target_source_generates_single_object_rule(tmp_path: Path) -> None:
    """Duplicate target source entries should not create duplicate Ninja rules."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "main.cpp").write_text("int x() { return 0; }\n")
    (source_dir / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.15)\n"
        "project(dup_source LANGUAGES CXX)\n"
        "add_library(mylib STATIC main.cpp)\n"
        "target_sources(mylib PRIVATE main.cpp)\n"
    )

    from cja.generator import configure

    configure(source_dir, "build", strict=True)
    ninja = (source_dir / "build.ninja").read_text()
    assert ninja.count("mylib_main.o: cxx") == 1


def test_target_sources_visibility_on_library() -> None:
    """INTERFACE/PUBLIC sources become interface sources of a library."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["mylib", "STATIC", "own.c"], line=1),
        Command(
            name="target_sources",
            args=["mylib", "PRIVATE", "priv.c", "PUBLIC", "pub.c", "INTERFACE", "iface.c"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert lib.sources == ["own.c", "priv.c", "pub.c"]
    assert lib.interface_sources == ["pub.c", "iface.c"]


def test_interface_sources_are_compiled_into_consumers(tmp_path: Path) -> None:
    """Like CMake, targets using a library compile its INTERFACE sources themselves."""
    (tmp_path / "CMakeLists.txt").write_text(
        """
cmake_minimum_required(VERSION 3.16)
project(is C)
add_library(backend INTERFACE)
target_sources(backend INTERFACE backend.c backend.h)
add_library(pubsrc STATIC pub_own.c)
target_sources(pubsrc PUBLIC pub_shared.c)
add_library(shell STATIC shell.c)
target_link_libraries(shell PRIVATE backend)
add_executable(app main.c)
target_link_libraries(app PRIVATE shell pubsrc)
"""
    )
    (tmp_path / "backend.h").write_text("int backend_fn(void);\n")
    (tmp_path / "backend.c").write_text("int backend_fn(void) { return 1; }\n")
    (tmp_path / "shell.c").write_text(
        '#include "backend.h"\nint shell_fn(void) { return backend_fn(); }\n'
    )
    (tmp_path / "pub_own.c").write_text("int pub_own(void) { return 2; }\n")
    (tmp_path / "pub_shared.c").write_text("int pub_shared(void) { return 4; }\n")
    (tmp_path / "main.c").write_text(
        "int shell_fn(void); int pub_shared(void);\n"
        "int main(void) { return shell_fn() + pub_shared() == 5 ? 0 : 1; }\n"
    )

    result = subprocess.run(
        [sys.executable, "-m", "cja", "run"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    content = (tmp_path / "build.ninja").read_text()
    # backend.c goes into shell (direct PRIVATE user) but not into app, which
    # doesn't use backend; pub_shared.c goes into both pubsrc and app.
    assert "build $builddir/shell_backend.o" in content
    assert "app_backend.o" not in content
    assert "build $builddir/pubsrc_pub_shared.o" in content
    assert "build $builddir/app_pub_shared.o" in content
