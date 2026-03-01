"""Tests for target_link_libraries edge cases."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, generate_ninja, process_commands
from cja.parser import Command


def test_target_link_libraries_skips_empty_argument() -> None:
    """Empty library arguments should be ignored."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.c"], line=1),
        Command(
            name="target_link_libraries", args=["myapp", "PRIVATE", "", "m"], line=2
        ),
    ]
    process_commands(commands, ctx, strict=True)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert exe.link_libraries == ["m"]


def test_add_library_empty_target_name_fails() -> None:
    """add_library() should fail for empty target names."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["", "STATIC", "lib.c"], line=1),
    ]

    with pytest.raises(SystemExit) as exc_info:
        process_commands(commands, ctx, strict=True)
    assert exc_info.value.code == 1


def test_target_link_libraries_versioned_names_get_dash_l(tmp_path: Path) -> None:
    """Library names with version-style dots (e.g. from pkg-config) should get -l prefix."""
    src = tmp_path / "main.c"
    src.write_text("int main() { return 0; }\n")
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="add_executable", args=["app", "main.c"], line=1),
        Command(
            name="target_link_libraries",
            args=["app", "PRIVATE", "webkit2gtk-4.1", "glib-2.0", "pangocairo-1.0"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    ninja_file = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_file, "build")
    content = ninja_file.read_text()
    assert "-lwebkit2gtk-4.1" in content
    assert "-lglib-2.0" in content
    assert "-lpangocairo-1.0" in content


def test_target_link_libraries_genex_false_branch_omitted(tmp_path: Path) -> None:
    """False compiler/version genex branch should not add link libraries."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    ctx.variables["CMAKE_CXX_COMPILER_ID"] = "GNU"
    ctx.variables["CMAKE_CXX_COMPILER_VERSION"] = "11.2.0"
    genex = "$<$<AND:$<CXX_COMPILER_ID:GNU>,$<VERSION_LESS:$<CXX_COMPILER_VERSION>,9.0>>:stdc++fs>"
    commands = [
        Command(name="add_executable", args=["app", "main.cpp"], line=1),
        Command(name="target_link_libraries", args=["app", "PRIVATE", genex], line=2),
    ]
    process_commands(commands, ctx)

    ninja_file = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_file, "build")
    content = ninja_file.read_text()
    assert "stdc++fs" not in content
