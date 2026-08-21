"""Tests for the include_guard() command."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, configure, process_commands
from cja.parser import Command


def test_include_guard_global_marks_file() -> None:
    """include_guard(GLOBAL) records the current list file as guarded."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="include_guard", args=["GLOBAL"], line=1)]
    process_commands(commands, ctx)

    assert ctx.current_list_file.resolve() in ctx.include_guarded_files


def test_include_guard_directory_default() -> None:
    """include_guard() without args defaults to DIRECTORY scope."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="include_guard", args=[], line=1)]
    process_commands(commands, ctx)

    assert ctx.current_list_file.resolve() in ctx.include_guarded_files


def test_include_guard_prevents_reinclusion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A file with include_guard(GLOBAL) is processed only once when included twice."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "Counter.cmake").write_text(
        "include_guard(GLOBAL)\n"
        'message(STATUS "Counter.cmake body ran")\n'
    )
    (source_dir / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(test_include_guard)\n"
        "include(Counter.cmake)\n"
        "include(Counter.cmake)\n"
        "include(Counter.cmake)\n"
        'message(STATUS "after includes")\n'
        "add_executable(main main.c)\n"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }\n")

    configure(source_dir, "build")
    out = capsys.readouterr().out

    assert out.count("Counter.cmake body ran") == 1
    assert "after includes" in out


def test_include_guard_allows_first_inclusion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The first include of a guarded file still runs to completion."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "Guarded.cmake").write_text(
        "include_guard(GLOBAL)\n"
        'message(STATUS "Guarded.cmake body ran")\n'
    )
    (source_dir / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(test_include_guard_first)\n"
        "include(Guarded.cmake)\n"
        "add_executable(main main.c)\n"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }\n")

    configure(source_dir, "build")
    out = capsys.readouterr().out

    assert "Guarded.cmake body ran" in out
