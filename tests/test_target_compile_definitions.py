"""Tests for target_compile_definitions command."""

from pathlib import Path

from cja.generator import BuildContext, process_commands, generate_ninja
from cja.parser import Command


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
    commands = [
        Command(name="add_library", args=["mylib", "lib.c"], line=1),
        Command(
            name="target_compile_definitions",
            args=[
                "mylib",
                "PRIVATE",
                "$<$<BOOL:ON>:LUA_USE_LINUX LUA_COMPAT_5_2>",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")
    ninja_content = ninja_path.read_text()

    assert "-DLUA_USE_LINUX" in ninja_content
    assert "-DLUA_COMPAT_5_2" in ninja_content
