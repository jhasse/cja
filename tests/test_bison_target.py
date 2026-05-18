"""Tests for BISON_TARGET() command."""

import shutil
import subprocess
from pathlib import Path

import pytest

from cja.generator import BuildContext, configure, process_commands
from cja.parser import Command


def has_bison() -> bool:
    return shutil.which("bison") is not None


def test_bison_target_creates_custom_command() -> None:
    """BISON_TARGET adds a custom_command invoking bison with --defines."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["BISON"], line=1),
        Command(
            name="bison_target",
            args=["MyParser", "parser.y", "parser.c"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    assert len(ctx.custom_commands) == 1
    custom = ctx.custom_commands[0]
    assert custom.outputs == ["parser.c", "parser.h"]
    bison_argv = custom.commands[0]
    assert any(arg.startswith("--defines=") for arg in bison_argv)
    assert "-o" in bison_argv
    output_index = bison_argv.index("-o") + 1
    assert Path(bison_argv[output_index]).name == "parser.c"
    assert Path(bison_argv[-1]).name == "parser.y"
    assert custom.depends == ["parser.y"]

    assert ctx.variables["BISON_MyParser_DEFINED"] == "TRUE"
    assert ctx.variables["BISON_MyParser_INPUT"] == "parser.y"
    # BISON_<Name>_OUTPUT_{SOURCE,HEADER} are anchored to CMAKE_CURRENT_BINARY_DIR
    # per CMake's FindBISON, expressed relative to the source dir.
    assert ctx.variables["BISON_MyParser_OUTPUT_SOURCE"] == "build/parser.c"
    assert ctx.variables["BISON_MyParser_OUTPUT_HEADER"] == "build/parser.h"


def test_bison_target_cpp_default_header() -> None:
    """A .cpp output picks .hpp as the default header extension."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["BISON"], line=1),
        Command(
            name="bison_target",
            args=["MyParser", "parser.yy", "parser.cpp"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["BISON_MyParser_OUTPUT_HEADER"] == "build/parser.hpp"
    assert "parser.hpp" in ctx.custom_commands[0].outputs


def test_bison_target_defines_file_override() -> None:
    """DEFINES_FILE overrides the default header path."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["BISON"], line=1),
        Command(
            name="bison_target",
            args=[
                "MyParser",
                "parser.y",
                "parser.c",
                "DEFINES_FILE",
                "tokens.h",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["BISON_MyParser_OUTPUT_HEADER"] == "build/tokens.h"
    assert "tokens.h" in ctx.custom_commands[0].outputs
    assert any(
        arg.startswith("--defines=")
        and Path(arg.split("=", 1)[1]).name == "tokens.h"
        for arg in ctx.custom_commands[0].commands[0]
    )


def test_bison_target_report_file() -> None:
    """REPORT_FILE adds the output and the --report-file flag."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["BISON"], line=1),
        Command(
            name="bison_target",
            args=[
                "MyParser",
                "parser.y",
                "parser.c",
                "REPORT_FILE",
                "parser.output",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["BISON_MyParser_REPORT_FILE"] == "build/parser.output"
    assert "parser.output" in ctx.custom_commands[0].outputs
    assert any(
        arg.startswith("--report-file=")
        and Path(arg.split("=", 1)[1]).name == "parser.output"
        for arg in ctx.custom_commands[0].commands[0]
    )


@pytest.mark.skipif(not has_bison(), reason="bison not found")
def test_bison_target_end_to_end(tmp_path: Path) -> None:
    """Verify a full configure/build cycle using BISON_TARGET."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "parser.y").write_text(
        "%{\n"
        "#include <stdio.h>\n"
        "int yylex(void);\n"
        "void yyerror(const char *s);\n"
        "%}\n"
        "%token NUM\n"
        "%%\n"
        "input: NUM { printf(\"got num\\n\"); } ;\n"
        "%%\n"
        "int yylex(void) { return 0; }\n"
        "void yyerror(const char *s) { (void)s; }\n"
        "int main(void) { return yyparse(); }\n"
    )
    (source_dir / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(bison_demo C)\n"
        "find_package(BISON REQUIRED)\n"
        "BISON_TARGET(MyParser parser.y "
        "${CMAKE_CURRENT_BINARY_DIR}/parser.c)\n"
        "add_executable(demo ${BISON_MyParser_OUTPUT_SOURCE})\n"
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
    assert (source_dir / "build" / "parser.c").exists()
    assert (source_dir / "build" / "parser.h").exists()
