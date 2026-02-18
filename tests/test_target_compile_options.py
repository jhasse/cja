"""Tests for target_compile_options command."""

from pathlib import Path

from cja.generator import BuildContext, generate_ninja, process_commands
from cja.parser import Command


def test_target_compile_options_executable() -> None:
    """target_compile_options adds options to executable target."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.c"], line=1),
        Command(
            name="target_compile_options",
            args=["myapp", "PRIVATE", "-Wall", "-Wextra"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "-Wall" in exe.compile_options
    assert "-Wextra" in exe.compile_options


def test_target_compile_options_visibility(tmp_path: Path) -> None:
    """PUBLIC/INTERFACE options propagate to linking executable."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="add_library", args=["mylib", "lib.c"], line=1),
        Command(
            name="target_compile_options",
            args=[
                "mylib",
                "PUBLIC",
                "-Wall",
                "PRIVATE",
                "-Werror",
                "INTERFACE",
                "-Winvalid-pch",
            ],
            line=2,
        ),
        Command(name="add_executable", args=["myapp", "main.c"], line=3),
        Command(name="target_link_libraries", args=["myapp", "mylib"], line=4),
    ]
    process_commands(commands, ctx)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert "-Wall" in lib.compile_options
    assert "-Werror" in lib.compile_options
    assert "-Winvalid-pch" not in lib.compile_options
    assert "-Wall" in lib.public_compile_options
    assert "-Winvalid-pch" in lib.public_compile_options
    assert "-Werror" not in lib.public_compile_options

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")
    lines = ninja_path.read_text().splitlines()

    lib_line_idx = next(i for i, line in enumerate(lines) if " lib.c" in line)
    lib_line_block = "\n".join(lines[lib_line_idx : lib_line_idx + 2])
    assert "-Wall" in lib_line_block
    assert "-Werror" in lib_line_block

    exe_line_idx = next(i for i, line in enumerate(lines) if " main.c" in line)
    exe_line_block = "\n".join(lines[exe_line_idx : exe_line_idx + 2])
    assert "-Wall" in exe_line_block
    assert "-Winvalid-pch" in exe_line_block
    assert "-Werror" not in exe_line_block


def test_windows_clang_upgrades_cxx11_in_target_compile_options(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """On Windows clang++, target -std=c++11 should be emitted as -std=c++14."""
    monkeypatch.setattr("cja.generator.platform.system", lambda: "Windows")

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    ctx.cxx_compiler = "clang++"
    commands = [
        Command(name="add_executable", args=["myapp", "main.cpp"], line=1),
        Command(
            name="target_compile_options",
            args=["myapp", "PRIVATE", "-std=c++11"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")
    content = ninja_path.read_text()
    assert "-std=c++14" in content
    assert "-std=c++11" not in content
