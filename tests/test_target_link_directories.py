"""Tests for target_link_directories command."""

import platform
from pathlib import Path

from cja.generator import BuildContext, process_commands, generate_ninja
from cja.parser import Command

LIB_EXT = ".lib" if platform.system() == "Windows" else ".a"


def test_target_link_directories_exe() -> None:
    """Test target_link_directories for an executable."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.c"], line=1),
        Command(
            name="target_link_directories",
            args=["myapp", "PRIVATE", "/opt/mylib/lib"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "/opt/mylib/lib" in exe.link_directories


def test_target_link_directories_ninja(tmp_path: Path) -> None:
    """Test that target_link_directories ends up in build.ninja."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    # Ensure source file exists so it's not filtered out if we add validation later
    (tmp_path / "main.c").write_text("int main() { return 0; }")

    commands = [
        Command(name="add_executable", args=["myapp", "main.c"], line=1),
        Command(
            name="target_link_directories",
            args=["myapp", "PRIVATE", "/opt/mylib/lib"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    ninja_file = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_file, "build")

    content = ninja_file.read_text()
    assert "-L/opt/mylib/lib" in content


def test_target_link_directories_propagation(tmp_path: Path) -> None:
    """Test propagation of public link directories from library to executable."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    (tmp_path / "lib.c").write_text("void f() {}")
    (tmp_path / "main.c").write_text("void f(); int main() { f(); return 0; }")

    commands = [
        Command(name="add_library", args=["mylib", "STATIC", "lib.c"], line=1),
        Command(
            name="target_link_directories",
            args=["mylib", "PUBLIC", "/opt/mylib/lib"],
            line=2,
        ),
        Command(name="add_executable", args=["myapp", "main.c"], line=3),
        Command(name="target_link_libraries", args=["myapp", "mylib"], line=4),
    ]
    process_commands(commands, ctx)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert "/opt/mylib/lib" in lib.public_link_directories

    ninja_file = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_file, "build")

    content = ninja_file.read_text()
    assert "-L/opt/mylib/lib" in content


def test_target_link_libraries_public_propagates(tmp_path: Path) -> None:
    """Test PUBLIC link libraries propagate to executables."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    (tmp_path / "libbar.c").write_text("void bar() {}")
    (tmp_path / "libfoo.c").write_text("void bar(); void foo() { bar(); }")
    (tmp_path / "main.c").write_text("void foo(); int main() { foo(); return 0; }")

    commands = [
        Command(name="add_library", args=["bar", "STATIC", "libbar.c"], line=1),
        Command(name="add_library", args=["foo", "STATIC", "libfoo.c"], line=2),
        Command(
            name="target_link_libraries",
            args=["foo", "PUBLIC", "bar"],
            line=3,
        ),
        Command(name="add_executable", args=["myapp", "main.c"], line=4),
        Command(name="target_link_libraries", args=["myapp", "foo"], line=5),
    ]
    process_commands(commands, ctx)

    foo = ctx.get_library("foo")
    assert foo is not None
    assert "bar" in foo.public_link_libraries

    ninja_file = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_file, "build")

    content = ninja_file.read_text()
    assert f"$builddir/libbar{LIB_EXT}" in content
