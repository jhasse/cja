"""Tests for add_executable(<name> IMPORTED)."""

import platform
import re
import shlex
from pathlib import Path

import pytest

from cja.generator import BuildContext, configure, process_commands
from cja.parser import Command
from cja.targets import ImportedTarget
from tests.helpers import cd_command, join_command_lines


def _configure(tmp_path: Path, cmake: str, tools: str = "tools") -> tuple[Path, str]:
    """Configure a project with an imported ``Ext::tool`` and return the path
    of the tool and the build.ninja content with unwrapped lines."""
    tool = tmp_path / tools / "tool"
    tool.parent.mkdir()
    tool.write_text("")
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(demo NONE)\n"
        "add_executable(Ext::tool IMPORTED)\n"
        "set_property(TARGET Ext::tool PROPERTY"
        f' IMPORTED_LOCATION "${{CMAKE_SOURCE_DIR}}/{tools}/tool")\n' + cmake
    )
    configure(tmp_path, "build", strict=True, quiet=True)
    ninja = (tmp_path / "build.ninja").read_text()
    return tool, re.sub(r" *\$\n *", " ", ninja)


def _build_statement(ninja: str, output: str) -> str:
    """The build line of an output and the variables following it."""
    lines = ninja.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"build {output}:"))
    end = start + 1
    while end < len(lines) and lines[end].startswith(" "):
        end += 1
    return "\n".join(lines[start:end])


def test_imported_executable_properties(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    tool, _ = _configure(
        tmp_path,
        "add_executable(global IMPORTED GLOBAL)\n"
        "foreach(prop TYPE IMPORTED IMPORTED_GLOBAL LOCATION)\n"
        "  get_target_property(value Ext::tool ${prop})\n"
        '  message("${prop}=${value}")\n'
        "endforeach()\n"
        "get_target_property(value global IMPORTED_GLOBAL)\n"
        'message("global IMPORTED_GLOBAL=${value}")\n'
        "if(TARGET Ext::tool)\n"
        '  message("is a target")\n'
        "endif()\n",
    )

    assert capsys.readouterr().out.splitlines() == [
        "TYPE=EXECUTABLE",
        "IMPORTED=TRUE",
        "IMPORTED_GLOBAL=FALSE",
        f"LOCATION={tool.as_posix()}",
        "global IMPORTED_GLOBAL=TRUE",
        "is a target",
    ]


def test_imported_executable_in_custom_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """COMMAND runs its location, which DEPENDS makes a dependency."""
    monkeypatch.chdir(tmp_path)
    tool, ninja = _configure(
        tmp_path,
        "add_custom_command(OUTPUT gen.txt COMMAND Ext::tool --out gen.txt"
        " DEPENDS Ext::tool)\n"
        "add_custom_command(OUTPUT genex.txt"
        " COMMAND $<TARGET_FILE:Ext::tool> $<TARGET_FILE_DIR:Ext::tool>)\n"
        "add_custom_target(gen ALL DEPENDS gen.txt genex.txt)\n"
        "add_custom_target(run COMMAND Ext::tool)\n"
        "add_dependencies(run Ext::tool)\n",
    )

    assert "Ext::tool" not in ninja
    # Ninja needs the colon of a Windows drive escaped in the paths of a build line
    tool_node = tool.as_posix().replace(":", "$:")
    gen = _build_statement(ninja, "$builddir/gen.txt")
    assert gen.splitlines()[0] == (
        f"build $builddir/gen.txt: custom_command {tool_node}"
    )
    # Like in CMake, the commands run in the binary directory.
    cd = cd_command("build")
    command = join_command_lines(cd, f"{tool.as_posix()} --out gen.txt")
    assert f"cmd = {command}" in gen
    genex = _build_statement(ninja, "$builddir/genex.txt")
    command = join_command_lines(cd, f"{tool.as_posix()} {tool.parent.as_posix()}")
    assert f"cmd = {command}" in genex
    run_line, run_cmd = _build_statement(ninja, "$builddir/run.stamp").split("\n", 1)
    assert run_line.endswith(f"|| {tool_node}")
    assert f"{tool.as_posix()} && " in run_cmd


def test_imported_executable_location_with_spaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its location is a single argument of the command, also without VERBATIM."""
    monkeypatch.chdir(tmp_path)
    tool, ninja = _configure(
        tmp_path, "add_custom_target(run COMMAND Ext::tool --flag)\n", "my tools"
    )

    if platform.system() == "Windows":
        quoted = f'"{tool.as_posix()}"'
    else:
        quoted = shlex.quote(tool.as_posix())
    assert f"{quoted} --flag && " in _build_statement(ninja, "$builddir/run.stamp")


def test_imported_executable_in_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    tool, ninja = _configure(
        tmp_path,
        "enable_testing()\n"
        "add_test(NAME by_name COMMAND Ext::tool --flag)\n"
        "add_test(NAME by_genex COMMAND $<TARGET_FILE:Ext::tool> --flag)\n",
    )

    assert "Ext::tool" not in ninja
    for name in ("by_name", "by_genex"):
        statement = _build_statement(ninja, f"test_{name}")
        assert f"{tool.as_posix()} --flag" in statement
        # Unlike an executable of the project, it doesn't have to be built
        assert statement.splitlines()[0] == f"build test_{name}: test_run"


def test_imported_executable_location_is_not_linked(tmp_path: Path) -> None:
    """Unlike the location of an imported library, it's not a link flag."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="add_executable", args=["tool", "IMPORTED"], line=1),
        Command(
            name="set_target_properties",
            args=["tool", "PROPERTIES", "IMPORTED_LOCATION", "/bin/tool"],
            line=2,
        ),
    ]

    process_commands(commands, ctx, strict=True)

    assert ctx.imported_targets["tool"].libs == ""
    assert ctx.target_property("tool", "IMPORTED_LOCATION") == "/bin/tool"


@pytest.mark.parametrize(
    ("properties", "expected"),
    [
        ({"IMPORTED_LOCATION": "/bin/tool"}, "/bin/tool"),
        ({"IMPORTED_LOCATION": "C:\\bin\\tool.exe"}, "C:/bin/tool.exe"),
        (
            {"IMPORTED_LOCATION": "/bin/tool", "IMPORTED_LOCATION_RELEASE": "/rel/tool"},
            "/rel/tool",
        ),
        (
            {"IMPORTED_LOCATION": "/bin/tool", "IMPORTED_LOCATION_DEBUG": "/dbg/tool"},
            "/bin/tool",
        ),
        (
            {
                "IMPORTED_CONFIGURATIONS": "Debug;MinSizeRel",
                "IMPORTED_LOCATION_MINSIZEREL": "/min/tool",
                "IMPORTED_LOCATION_DEBUG": "/dbg/tool",
            },
            "/dbg/tool",
        ),
        ({}, None),
    ],
)
def test_imported_executable_location(
    properties: dict[str, str], expected: str | None
) -> None:
    """Like in CMake, the location of the build type is preferred."""
    imported = ImportedTarget(executable=True, properties=properties)

    assert imported.location("RELEASE") == expected
