"""Tests for try_compile command."""

from pathlib import Path

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_try_compile_success(tmp_path: Path) -> None:
    """try_compile should set result variable TRUE when compile succeeds."""
    src = tmp_path / "ok.c"
    src.write_text("int main(void) { return 0; }\n")

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(
            name="try_compile",
            args=["COMPILE_OK", str(tmp_path / "build"), "SOURCES", str(src)],
            line=1,
        ),
    ]

    process_commands(commands, ctx, strict=True)

    assert ctx.variables["COMPILE_OK"] == "TRUE"


def test_try_compile_output_variable_on_failure(tmp_path: Path) -> None:
    """try_compile should populate OUTPUT_VARIABLE with compiler diagnostics."""
    src = tmp_path / "fail.cc"
    src.write_text('#error libfound "stdc++fs"\n')

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(
            name="try_compile",
            args=[
                "COMPILE_OK",
                str(tmp_path / "build"),
                "SOURCES",
                str(src),
                "OUTPUT_VARIABLE",
                "RAWOUTPUT",
            ],
            line=1,
        ),
    ]

    process_commands(commands, ctx, strict=True)

    assert ctx.variables["COMPILE_OK"] == "FALSE"
    assert 'libfound "stdc++fs"' in ctx.variables["RAWOUTPUT"]
