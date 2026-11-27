"""Tests for target_compile_definitions command."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, generate_ninja, process_commands
from cja.parser import Command, parse


def test_target_compile_definitions() -> None:
    """Test that target_compile_definitions adds definitions to specific targets."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.cpp"], line=1),
        Command(
            name="target_compile_definitions",
            args=["myapp", "PRIVATE", "MY_DEF"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "MY_DEF" in exe.compile_definitions


def test_target_compile_definitions_visibility(tmp_path: Path) -> None:
    """Test visibility propagation of target_compile_definitions."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="add_library", args=["mylib", "lib.cpp"], line=1),
        Command(
            name="target_compile_definitions",
            args=[
                "mylib",
                "PUBLIC",
                "PUB_DEF",
                "PRIVATE",
                "PRIV_DEF",
                "INTERFACE",
                "INT_DEF",
            ],
            line=2,
        ),
        Command(name="add_executable", args=["myapp", "main.cpp"], line=3),
        Command(name="target_link_libraries", args=["myapp", "mylib"], line=4),
    ]
    process_commands(commands, ctx)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert "PUB_DEF" in lib.compile_definitions
    assert "PRIV_DEF" in lib.compile_definitions
    assert "INT_DEF" not in lib.compile_definitions
    assert "PUB_DEF" in lib.public_compile_definitions
    assert "INT_DEF" in lib.public_compile_definitions
    assert "PRIV_DEF" not in lib.public_compile_definitions

    # Test propagation to Ninja file
    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    ninja_content = ninja_path.read_text()

    # mylib should have both PUB_DEF and PRIV_DEF
    assert "-DPUB_DEF" in ninja_content
    assert "-DPRIV_DEF" in ninja_content

    # myapp should have PUB_DEF and INT_DEF (from mylib)
    assert "-DINT_DEF" in ninja_content


def test_target_compile_definitions_bool_genex(tmp_path: Path) -> None:
    """$<BOOL:...> generator expressions in definitions should evaluate to 1/0."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="add_executable", args=["myapp", "main.cpp"], line=1),
        Command(
            name="target_compile_definitions",
            args=[
                "myapp",
                "PRIVATE",
                "JSON_USE_IMPLICIT_CONVERSIONS=$<BOOL:ON>",
                "JSON_DIAGNOSTICS=$<BOOL:OFF>",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")
    ninja_content = ninja_path.read_text()

    assert "-DJSON_USE_IMPLICIT_CONVERSIONS=1" in ninja_content
    assert "-DJSON_DIAGNOSTICS=0" in ninja_content


def test_target_compile_definitions_genex_space_separated_values(tmp_path: Path) -> None:
    """Space-separated genex values should emit separate -D flags."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = parse(
        "add_library(mylib lib.c)\n"
        "target_compile_definitions(mylib PRIVATE\n"
        "  $<$<BOOL:ON>:LUA_USE_LINUX LUA_COMPAT_5_2>)\n"
    )
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")
    ninja_content = ninja_path.read_text()

    assert "-DLUA_USE_LINUX -DLUA_COMPAT_5_2" in ninja_content


def test_target_compile_definitions_with_spaces(tmp_path: Path) -> None:
    """Like in CMake, a definition is a single one with the spaces it has,
    e.g. in the value of a string, wherever they are from."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = parse(
        r"""
add_library(mylib lib.c)
set(FROM_VARIABLE "VARIABLE=\"four words\"")
target_compile_definitions(mylib
  PRIVATE "QUOTED=\"two words\"" UNQUOTED=\"three\ more\ words\" ${FROM_VARIABLE}
  PUBLIC "$<1:GENEX=\"in quotes\">")
set_property(TARGET mylib APPEND PROPERTY COMPILE_DEFINITIONS "PROPERTY=\"as well\"")
"""
    )
    process_commands(commands, ctx)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert lib.compile_definitions == [
        'QUOTED="two words"',
        'UNQUOTED="three more words"',
        'VARIABLE="four words"',
        'GENEX="in quotes"',
        'PROPERTY="as well"',
    ]
    assert lib.public_compile_definitions == ['GENEX="in quotes"']


@pytest.mark.parametrize("strict", [False, True])
def test_target_compile_definitions_leading_d(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], strict: bool
) -> None:
    """Like in CMake, a leading -D is removed, which is worth a warning in
    strict mode."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="add_library", args=["mylib", "lib.c"], line=1),
        Command(
            name="target_compile_definitions",
            args=[
                "mylib",
                "PRIVATE",
                "-DPRIV_DEF",
                "PLAIN_DEF",
                "-DVALUE=1",
                "PUBLIC",
                "-DLIST_A;-DLIST_B",
                "INTERFACE",
                "$<1:-DGENEX_DEF>",
            ],
            line=2,
        ),
        Command(name="add_executable", args=["myapp", "main.c"], line=3),
        Command(name="target_link_libraries", args=["myapp", "mylib"], line=4),
        Command(
            name="target_compile_definitions", args=["myapp", "PRIVATE", "-DAPP_DEF"], line=5
        ),
    ]
    process_commands(commands, ctx, strict=strict)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert lib.compile_definitions == [
        "PRIV_DEF",
        "PLAIN_DEF",
        "VALUE=1",
        "LIST_A",
        "LIST_B",
    ]
    assert lib.public_compile_definitions == [
        "LIST_A",
        "LIST_B",
        "GENEX_DEF",
    ]
    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert exe.compile_definitions == ["APP_DEF"]

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")
    ninja_content = ninja_path.read_text()
    assert "-D-D" not in ninja_content
    for definition in ("PRIV_DEF", "VALUE=1", "LIST_B", "GENEX_DEF", "APP_DEF"):
        assert f"-D{definition}" in ninja_content

    warnings = [
        f'CMakeLists.txt:{line}: warning: target_compile_definitions: "{arg}" has a'
        " leading -D, which is removed"
        for line, arg in (
            (2, "-DPRIV_DEF"),
            (2, "-DVALUE=1"),
            (2, "-DLIST_A"),
            (2, "-DLIST_B"),
            (2, "$<1:-DGENEX_DEF>"),
            (5, "-DAPP_DEF"),
        )
    ]
    assert capsys.readouterr().err.splitlines() == (warnings if strict else [])
