"""Tests for add_executable(<name> ALIAS <target>)."""

import platform
import re
from pathlib import Path

import pytest

from cja.generator import BuildContext, configure

EXE_EXT = ".exe" if platform.system() == "Windows" else ""

# Everything that runs or depends on an executable
USES = (
    "add_custom_command(OUTPUT gen.txt COMMAND @tool@ --out gen.txt DEPENDS @tool@)\n"
    "add_custom_command(OUTPUT genex.txt"
    " COMMAND $<TARGET_FILE:@tool@> $<TARGET_FILE_DIR:@tool@>)\n"
    "add_custom_target(gen ALL DEPENDS gen.txt genex.txt)\n"
    "add_custom_target(run COMMAND @tool@)\n"
    "add_dependencies(run @tool@)\n"
    "enable_testing()\n"
    "add_test(NAME by_name COMMAND @tool@ --flag)\n"
    "add_test(NAME by_genex COMMAND $<TARGET_FILE:@tool@> --flag)\n"
)
CANNOT_CREATE = 'add_executable cannot create ALIAS target "other" because target '


def _configure(
    tmp_path: Path, cmake: str, target: str = "", strict: bool = True
) -> BuildContext:
    """Configure a project with an executable ``tool``, unless there's another
    ``target``, and its alias ``Demo::tool``."""
    (tmp_path / "tool.c").write_text("int main(void) { return 0; }\n")
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(demo C)\n"
        + (target or "add_executable(tool tool.c)\n")
        + "add_executable(Demo::tool ALIAS tool)\n"
        + cmake
    )
    return configure(tmp_path, "build", strict=strict, quiet=strict)


def _ninja(tmp_path: Path, cmake: str, target: str = "") -> str:
    """The build.ninja content of such a project, with unwrapped lines."""
    _configure(tmp_path, cmake, target)
    return re.sub(r" *\$\n *", " ", (tmp_path / "build.ninja").read_text())


def test_executable_alias_properties(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    ctx = _configure(
        tmp_path,
        "set_target_properties(tool PROPERTIES OUTPUT_NAME renamed)\n"
        "foreach(prop NAME TYPE OUTPUT_NAME)\n"
        "  get_target_property(value Demo::tool ${prop})\n"
        '  message("${prop}=${value}")\n'
        "endforeach()\n"
        "if(TARGET Demo::tool)\n"
        '  message("is a target")\n'
        "endif()\n",
    )

    assert capsys.readouterr().out.splitlines() == [
        "NAME=tool",
        "TYPE=EXECUTABLE",
        "OUTPUT_NAME=renamed",
        "is a target",
    ]
    # It isn't another executable to build.
    assert [exe.name for exe in ctx.executables] == ["tool"]


def test_executable_alias_stands_for_the_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In commands, dependencies, generator expressions and tests."""
    monkeypatch.chdir(tmp_path)
    with_alias = _ninja(tmp_path, USES.replace("@tool@", "Demo::tool"))
    with_target = _ninja(tmp_path, USES.replace("@tool@", "tool"))

    assert "Demo::tool" not in with_alias
    assert with_alias == with_target
    tool = f"$builddir/tool{EXE_EXT}"
    assert f"build $builddir/gen.txt: custom_command {tool}\n" in with_alias
    assert f"build test_by_name: test_run | {tool}\n" in with_alias


def test_alias_of_imported_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """It has the location that the imported executable gets afterwards."""
    monkeypatch.chdir(tmp_path)
    tool = tmp_path / "tools" / "tool"
    tool.parent.mkdir()
    tool.write_text("")
    imported = "add_executable(tool IMPORTED)\n"
    location = (
        "set_property(TARGET tool PROPERTY"
        ' IMPORTED_LOCATION "${CMAKE_SOURCE_DIR}/tools/tool")\n'
    )
    properties = (
        "foreach(prop NAME TYPE LOCATION)\n"
        "  get_target_property(value Demo::tool ${prop})\n"
        '  message("${prop}=${value}")\n'
        "endforeach()\n"
    )
    with_alias = _ninja(
        tmp_path, location + properties + USES.replace("@tool@", "Demo::tool"), imported
    )
    with_target = _ninja(tmp_path, location + USES.replace("@tool@", "tool"), imported)

    assert capsys.readouterr().out.splitlines() == [
        "NAME=tool",
        "TYPE=EXECUTABLE",
        f"LOCATION={tool.as_posix()}",
    ]
    assert "Demo::tool" not in with_alias
    assert with_alias == with_target
    assert f"{tool.as_posix()} --flag" in with_alias


@pytest.mark.parametrize(
    ("command", "message"),
    [
        (
            "add_executable(other ALIAS missing)",
            CANNOT_CREATE + '"missing" does not already exist.',
        ),
        (
            "add_library(lib INTERFACE)\nadd_executable(other ALIAS lib)",
            CANNOT_CREATE + '"lib" is not an executable.',
        ),
        (
            "add_executable(other ALIAS Demo::tool)",
            CANNOT_CREATE + '"Demo::tool" is itself an ALIAS.',
        ),
        (
            "add_executable(other ALIAS tool tool.c)",
            "add_executable ALIAS requires exactly one target argument.",
        ),
    ],
)
def test_executable_alias_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    message: str,
) -> None:
    """Like in CMake, which is only a warning without strict mode."""
    monkeypatch.chdir(tmp_path)
    line = 4 + command.count("\n") + 1
    with pytest.raises(SystemExit) as exc_info:
        _configure(tmp_path, command + "\n")
    assert exc_info.value.code == 1
    assert f"CMakeLists.txt:{line}: error: {message}\n" in capsys.readouterr().err

    ctx = _configure(tmp_path, command + "\n", strict=False)
    assert f"CMakeLists.txt:{line}: warning: {message}\n" in capsys.readouterr().err
    assert not ctx.target_exists("other")
    assert ctx.executable_aliases == {"Demo::tool": "tool"}
