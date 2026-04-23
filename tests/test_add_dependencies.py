"""Tests for add_dependencies command."""

import platform
from pathlib import Path

from cja.generator import BuildContext, generate_ninja, process_commands
from cja.parser import Command

LIB_EXT = ".lib" if platform.system() == "Windows" else ".a"


def test_add_dependencies_on_executable() -> None:
    """add_dependencies stores dep names on the target executable."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.cpp"], line=1),
        Command(
            name="add_custom_target",
            args=["gen", "COMMAND", "echo", "hi"],
            line=2,
        ),
        Command(name="add_dependencies", args=["myapp", "gen"], line=3),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert exe.dependencies == ["gen"]


def test_add_dependencies_on_library() -> None:
    """add_dependencies stores dep names on the target library."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["mylib", "lib.cpp"], line=1),
        Command(
            name="add_custom_target",
            args=["gen", "COMMAND", "echo", "hi"],
            line=2,
        ),
        Command(name="add_dependencies", args=["mylib", "gen"], line=3),
    ]
    process_commands(commands, ctx)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert lib.dependencies == ["gen"]


def test_add_dependencies_on_custom_target() -> None:
    """add_dependencies stores dep names on a custom target."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="add_custom_target",
            args=["parent", "COMMAND", "echo", "parent"],
            line=1,
        ),
        Command(
            name="add_custom_target",
            args=["child", "COMMAND", "echo", "child"],
            line=2,
        ),
        Command(name="add_dependencies", args=["parent", "child"], line=3),
    ]
    process_commands(commands, ctx)

    parent = next(ct for ct in ctx.custom_targets if ct.name == "parent")
    assert parent.dependencies == ["child"]


def test_add_dependencies_multiple_deps() -> None:
    """Multiple deps may be specified in one call and accumulate across calls."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["app", "main.cpp"], line=1),
        Command(name="add_custom_target", args=["a"], line=2),
        Command(name="add_custom_target", args=["b"], line=3),
        Command(name="add_custom_target", args=["c"], line=4),
        Command(name="add_dependencies", args=["app", "a", "b"], line=5),
        Command(name="add_dependencies", args=["app", "c"], line=6),
        Command(name="add_dependencies", args=["app", "a"], line=7),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("app")
    assert exe is not None
    assert exe.dependencies == ["a", "b", "c"]


def test_add_dependencies_in_ninja_executable(tmp_path: Path) -> None:
    """Executable's build statements get an order-only dep on the custom target."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="add_executable", args=["myapp", "main.cpp"], line=1),
        Command(
            name="add_custom_target",
            args=["gen", "COMMAND", "echo", "generated"],
            line=2,
        ),
        Command(name="add_dependencies", args=["myapp", "gen"], line=3),
    ]
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    ninja_content = ninja_path.read_text()

    # The executable's object file should have 'gen' as order-only dep
    assert "$builddir/myapp_main.o: cxx main.cpp" in ninja_content
    # Both the compile and link steps should reference gen via '|| gen'
    assert "|| gen" in ninja_content


def test_add_dependencies_in_ninja_library(tmp_path: Path) -> None:
    """Library's archive gets an order-only dep on the custom target."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="add_library", args=["mylib", "lib.cpp"], line=1),
        Command(
            name="add_custom_target",
            args=["gen", "COMMAND", "echo", "gen"],
            line=2,
        ),
        Command(name="add_dependencies", args=["mylib", "gen"], line=3),
    ]
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    ninja_content = ninja_path.read_text()

    assert f"$builddir/libmylib{LIB_EXT}: ar" in ninja_content
    assert "|| gen" in ninja_content


def test_add_dependencies_between_custom_targets(tmp_path: Path) -> None:
    """Custom target dependencies appear in its phony rule inputs."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="add_custom_target", args=["parent"], line=1),
        Command(
            name="add_custom_target",
            args=["child", "COMMAND", "echo", "child"],
            line=2,
        ),
        Command(name="add_dependencies", args=["parent", "child"], line=3),
    ]
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    ninja_content = ninja_path.read_text()

    # parent is a pure phony aggregator: child is listed as a direct input
    assert "build parent: phony child" in ninja_content


def test_add_dependencies_target_to_library(tmp_path: Path) -> None:
    """Executable can have a library as an order-only dep via add_dependencies."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="add_library", args=["mylib", "lib.cpp"], line=1),
        Command(name="add_executable", args=["myapp", "main.cpp"], line=2),
        Command(name="add_dependencies", args=["myapp", "mylib"], line=3),
    ]
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    ninja_content = ninja_path.read_text()

    # The executable object build should have '|| $builddir/libmylib.<ext>' as order-only
    assert f"$builddir/libmylib{LIB_EXT}" in ninja_content
    # Verify it's used as an order-only dep (normalize ninja's line continuations)
    normalized = ninja_content.replace("$\n    ", "").replace("$\n  ", "")
    assert f"|| $builddir/libmylib{LIB_EXT}" in normalized


def test_add_dependencies_unknown_target_ignored() -> None:
    """Silently ignore add_dependencies on unknown target in non-strict mode."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.quiet = True
    commands = [
        Command(name="add_dependencies", args=["ghost", "other"], line=1),
    ]
    process_commands(commands, ctx)
    # Should not raise; no targets exist, nothing recorded.
    assert ctx.executables == []
    assert ctx.libraries == []
    assert ctx.custom_targets == []
