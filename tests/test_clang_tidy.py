"""Tests for CXX_CLANG_TIDY support via validation nodes."""

from pathlib import Path

from cja.build_context import BuildContext
from cja.parser import Command
from cja.generator import process_commands, generate_ninja


def test_cxx_clang_tidy_generates_validation_node(tmp_path: Path) -> None:
    """CXX_CLANG_TIDY should produce a clang_tidy rule and |@ validation edges."""
    (tmp_path / "main.cpp").write_text("int main() {}\n")

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="add_executable", args=["app", "main.cpp"], line=1),
        Command(
            name="set_target_properties",
            args=["app", "PROPERTIES", "CXX_CLANG_TIDY", "clang-tidy;--use-color"],
            is_quoted=[False, False, False, True],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    ninja_file = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_file, "build")
    content = ninja_file.read_text()

    assert "rule clang_tidy" in content
    assert "clang_tidy_cmd = clang-tidy --use-color" in content
    assert "|@ " in content
    assert ".tidy" in content


def test_cxx_clang_tidy_not_applied_to_c_files(tmp_path: Path) -> None:
    """CXX_CLANG_TIDY should not generate validation for C source files."""
    (tmp_path / "main.c").write_text("int main() { return 0; }\n")

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="add_executable", args=["app", "main.c"], line=1),
        Command(
            name="set_target_properties",
            args=["app", "PROPERTIES", "CXX_CLANG_TIDY", "clang-tidy"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    ninja_file = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_file, "build")
    content = ninja_file.read_text()

    assert "|@" not in content
    assert ".tidy" not in content


def test_no_clang_tidy_without_property(tmp_path: Path) -> None:
    """Without CXX_CLANG_TIDY property, no clang_tidy rule should be emitted."""
    (tmp_path / "main.cpp").write_text("int main() {}\n")

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="add_executable", args=["app", "main.cpp"], line=1),
    ]
    process_commands(commands, ctx)

    ninja_file = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_file, "build")
    content = ninja_file.read_text()

    assert "clang_tidy" not in content
    assert "|@" not in content


def test_clang_tidy_includes_compile_flags(tmp_path: Path) -> None:
    """Clang-tidy build edge should receive the same compile flags."""
    (tmp_path / "main.cpp").write_text("int main() {}\n")

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="add_executable", args=["app", "main.cpp"], line=1),
        Command(
            name="target_compile_definitions",
            args=["app", "PRIVATE", "MY_DEFINE=1"],
            line=2,
        ),
        Command(
            name="set_target_properties",
            args=["app", "PROPERTIES", "CXX_CLANG_TIDY", "clang-tidy"],
            line=3,
        ),
    ]
    process_commands(commands, ctx)

    ninja_file = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_file, "build")
    content = ninja_file.read_text()

    # Find the tidy build edge and verify it has the compile definition
    lines = content.split("\n")
    in_tidy_block = False
    tidy_has_define = False
    for line in lines:
        if ".tidy:" in line and "clang_tidy" in line:
            in_tidy_block = True
        elif in_tidy_block:
            if line.startswith("  cflags") and "-DMY_DEFINE=1" in line:
                tidy_has_define = True
                break
            if line and not line.startswith(" "):
                break
    assert tidy_has_define
