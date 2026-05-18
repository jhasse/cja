"""Tests for FLEX_TARGET() command."""

import shutil
from pathlib import Path

import pytest

from cja.generator import BuildContext, configure, process_commands
from cja.parser import Command


def has_flex() -> bool:
    return shutil.which("flex") is not None


def test_flex_target_creates_custom_command() -> None:
    """FLEX_TARGET adds a custom_command running flex with -o."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["FLEX"], line=1),
        Command(
            name="flex_target",
            args=["MyScanner", "scanner.l", "scanner.c"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    assert len(ctx.custom_commands) == 1
    custom = ctx.custom_commands[0]
    assert custom.outputs == ["scanner.c"]
    assert len(custom.commands) == 1
    flex_argv = custom.commands[0]
    assert "-o" in flex_argv
    output_index = flex_argv.index("-o") + 1
    output_arg = Path(flex_argv[output_index])
    assert output_arg.name == "scanner.c"
    assert output_arg.is_absolute()
    # Relative FlexOutput must be anchored to the build dir, not the source dir.
    assert output_arg.parent == Path("build").resolve()
    assert Path(flex_argv[-1]).name == "scanner.l"
    assert custom.depends == ["scanner.l"]
    assert custom.main_dependency == "scanner.l"

    assert ctx.variables["FLEX_MyScanner_DEFINED"] == "TRUE"
    assert ctx.variables["FLEX_MyScanner_INPUT"] == "scanner.l"
    # FLEX_<Name>_OUTPUTS is anchored to CMAKE_CURRENT_BINARY_DIR per CMake's
    # FindFLEX, expressed relative to the source dir.
    assert ctx.variables["FLEX_MyScanner_OUTPUTS"] == "build/scanner.c"


def test_flex_target_with_defines_file() -> None:
    """FLEX_TARGET with DEFINES_FILE adds --header-file and sets OUTPUT_HEADER."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["FLEX"], line=1),
        Command(
            name="flex_target",
            args=[
                "MyScanner",
                "scanner.l",
                "scanner.c",
                "DEFINES_FILE",
                "scanner.h",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["FLEX_MyScanner_OUTPUT_HEADER"] == "build/scanner.h"
    assert "scanner.h" in ctx.custom_commands[0].outputs
    assert any(
        arg.startswith("--header-file=")
        and Path(arg.split("=", 1)[1]).name == "scanner.h"
        for arg in ctx.custom_commands[0].commands[0]
    )


def test_flex_target_compile_flags() -> None:
    """COMPILE_FLAGS are split and passed through to the flex invocation."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["FLEX"], line=1),
        Command(
            name="flex_target",
            args=[
                "MyScanner",
                "scanner.l",
                "scanner.c",
                "COMPILE_FLAGS",
                "--debug -B",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    cmd_args = ctx.custom_commands[0].commands[0]
    assert "--debug" in cmd_args
    assert "-B" in cmd_args


@pytest.mark.skipif(not has_flex(), reason="flex not found")
def test_flex_target_end_to_end(tmp_path: Path) -> None:
    """Verify a full configure/build/run cycle using FLEX_TARGET."""
    import subprocess

    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "scanner.l").write_text(
        "%%\n"
        '[a-z]+    { printf("word\\n"); }\n'
        '\\n        { return 0; }\n'
        ".         { }\n"
        "%%\n"
        "int yywrap(void) { return 1; }\n"
        "int main(void) { return yylex(); }\n"
    )
    (source_dir / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(flex_demo C)\n"
        "find_package(FLEX REQUIRED)\n"
        "FLEX_TARGET(MyScanner scanner.l ${CMAKE_CURRENT_BINARY_DIR}/scanner.c)\n"
        "add_executable(demo ${FLEX_MyScanner_OUTPUTS})\n"
    )

    configure(source_dir, "build")
    ninja_manifest = source_dir / "build.ninja"
    assert ninja_manifest.exists()

    ninja = shutil.which("ninja")
    if ninja is None:
        pytest.skip("ninja not available")
    result = subprocess.run(
        [ninja, "-f", str(ninja_manifest)],
        cwd=source_dir,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"ninja failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert (source_dir / "build" / "scanner.c").exists()
