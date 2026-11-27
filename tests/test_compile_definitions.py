"""Tests for add_compile_definitions command."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, generate_ninja, process_commands
from cja.parser import Command


def test_add_compile_definitions() -> None:
    """Test that add_compile_definitions adds -D flags to all targets."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_compile_definitions", args=["DEBUG_MODE"], line=1),
        Command(name="add_compile_definitions", args=["VERSION=1.0"], line=2),
        Command(name="add_executable", args=["myapp", "main.cpp"], line=3),
    ]
    process_commands(commands, ctx)

    assert ctx.compile_definitions == ["DEBUG_MODE", "VERSION=1.0"]
    assert len(ctx.executables) == 1


def test_add_compile_definitions_with_variables() -> None:
    """Test that add_compile_definitions expands variables."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_DEF"] = "CUSTOM_FLAG"
    commands = [
        Command(name="add_compile_definitions", args=["${MY_DEF}"], line=1),
    ]
    process_commands(commands, ctx)

    assert ctx.compile_definitions == ["CUSTOM_FLAG"]


def test_multiple_definitions() -> None:
    """Test adding multiple compile definitions at once."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_compile_definitions", args=["FOO", "BAR", "BAZ=123"], line=1),
    ]
    process_commands(commands, ctx)

    assert ctx.compile_definitions == ["FOO", "BAR", "BAZ=123"]


def test_add_definitions_strips_dash_d(tmp_path: Path) -> None:
    """Legacy add_definitions(-DFOO) should emit a single -DFOO flag."""
    from cja.generator import configure

    source_dir = tmp_path
    (source_dir / "main.c").write_text("int main(void) { return 0; }\n")
    (source_dir / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(AddDefsTest C)\n"
        "add_executable(myapp main.c)\n"
        "add_definitions(-DLUAJIT_OS=LUAJIT_OS_LINUX -D_FILE_OFFSET_BITS=64)\n"
    )

    configure(source_dir, "build")
    content = (source_dir / "build.ninja").read_text()
    assert "-DLUAJIT_OS=LUAJIT_OS_LINUX" in content
    assert "-D-DLUAJIT_OS" not in content
    assert "-D_FILE_OFFSET_BITS=64" in content


def test_definitions_with_leading_dash_d(tmp_path: Path) -> None:
    """Like in CMake, a leading -D of any compile definition is removed when
    generating, and what's empty then is ignored."""
    from cja.generator import configure

    source_dir = tmp_path
    (source_dir / "main.c").write_text("int main(void) { return 0; }\n")
    (source_dir / "lib.c").write_text("int f(void) { return 0; }\n")
    (source_dir / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(DashDTest C)\n"
        "add_compile_definitions(-DDIR_DEF DIR_PLAIN -D $<1:-DDIR_GENEX>)\n"
        "add_library(mylib STATIC lib.c)\n"
        # Only known once it's evaluated for the target that uses the library
        "target_compile_definitions(mylib INTERFACE\n"
        '  "$<$<STREQUAL:$<TARGET_PROPERTY:TYPE>,EXECUTABLE>:-DLATE_GENEX>")\n'
        "add_executable(myapp main.c)\n"
        "target_link_libraries(myapp PRIVATE mylib)\n"
        "set_source_files_properties(main.c PROPERTIES\n"
        '  COMPILE_DEFINITIONS "-DSRC_DEF;SRC_PLAIN")\n'
    )

    configure(source_dir, "build")
    content = (source_dir / "build.ninja").read_text()
    assert "-D-D" not in content
    assert "-D " not in content
    for definition in (
        "DIR_DEF",
        "DIR_PLAIN",
        "DIR_GENEX",
        "LATE_GENEX",
        "SRC_DEF",
        "SRC_PLAIN",
    ):
        assert f"-D{definition}" in content


@pytest.mark.parametrize(
    "command",
    [
        Command("add_compile_definitions", ["-D", "FOO"], line=2),
        Command("target_compile_definitions", ["myapp", "PRIVATE", "-D", "FOO"], line=2),
    ],
)
def test_lone_dash_d(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: Command
) -> None:
    """A -D without a definition is ignored with a warning, and is an error in
    strict mode."""
    commands = [Command("add_executable", ["myapp", "main.c"], line=1), command]
    message = f'{command.name} given "-D" without a definition\n'

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    process_commands(commands, ctx)
    assert capsys.readouterr().err == f"CMakeLists.txt:2: warning: {message}"
    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")
    (cflags,) = [
        line.split() for line in ninja_path.read_text().splitlines() if "cflags =" in line
    ]
    assert [flag for flag in cflags if flag.startswith("-D")] == ["-DFOO"]

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    with pytest.raises(SystemExit) as exc_info:
        process_commands(commands, ctx, strict=True)
    assert exc_info.value.code == 1
    assert capsys.readouterr().err == f"CMakeLists.txt:2: error: {message}"
