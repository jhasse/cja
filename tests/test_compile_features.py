"""Tests for target_compile_features command."""

from pathlib import Path

from cninja.generator import (
    BuildContext,
    compile_feature_to_flag,
    generate_ninja,
    process_commands,
)
from cninja.parser import Command


def test_compile_feature_to_flag_cxx_std() -> None:
    """Test translating cxx_std_XX to compiler flags."""
    assert compile_feature_to_flag("cxx_std_11") == "-std=c++11"
    assert compile_feature_to_flag("cxx_std_14") == "-std=c++14"
    assert compile_feature_to_flag("cxx_std_17") == "-std=c++17"
    assert compile_feature_to_flag("cxx_std_20") == "-std=c++20"
    assert compile_feature_to_flag("cxx_std_23") == "-std=c++23"


def test_compile_feature_to_flag_c_std() -> None:
    """Test translating c_std_XX to compiler flags."""
    assert compile_feature_to_flag("c_std_99") == "-std=c99"
    assert compile_feature_to_flag("c_std_11") == "-std=c11"
    assert compile_feature_to_flag("c_std_17") == "-std=c17"


def test_compile_feature_to_flag_unknown() -> None:
    """Test unknown features return None."""
    assert compile_feature_to_flag("unknown_feature") is None


def test_target_compile_features_executable() -> None:
    """Test target_compile_features on executable."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.cpp"], line=1),
        Command(name="target_compile_features", args=["myapp", "PUBLIC", "cxx_std_17"], line=2),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "cxx_std_17" in exe.compile_features


def test_target_compile_features_library() -> None:
    """Test target_compile_features on library."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["mylib", "lib.cpp"], line=1),
        Command(name="target_compile_features", args=["mylib", "PRIVATE", "cxx_std_20"], line=2),
    ]
    process_commands(commands, ctx)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert "cxx_std_20" in lib.compile_features


def test_target_compile_features_multiple() -> None:
    """Test target_compile_features with multiple features."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.cpp"], line=1),
        Command(name="target_compile_features", args=["myapp", "PUBLIC", "cxx_std_17", "cxx_constexpr"], line=2),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "cxx_std_17" in exe.compile_features
    assert "cxx_constexpr" in exe.compile_features


def test_target_compile_features_public_propagates() -> None:
    """Test PUBLIC compile features propagate to linking executable."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["mylib", "lib.cpp"], line=1),
        Command(name="target_compile_features", args=["mylib", "PUBLIC", "cxx_std_17"], line=2),
        Command(name="add_executable", args=["myapp", "main.cpp"], line=3),
        Command(name="target_link_libraries", args=["myapp", "mylib"], line=4),
    ]
    process_commands(commands, ctx)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert "cxx_std_17" in lib.public_compile_features
    assert "cxx_std_17" in lib.compile_features  # Library also compiles with it


def test_target_compile_features_private_does_not_propagate() -> None:
    """Test PRIVATE compile features do not propagate to linking executable."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["mylib", "lib.cpp"], line=1),
        Command(name="target_compile_features", args=["mylib", "PRIVATE", "cxx_std_20"], line=2),
        Command(name="add_executable", args=["myapp", "main.cpp"], line=3),
        Command(name="target_link_libraries", args=["myapp", "mylib"], line=4),
    ]
    process_commands(commands, ctx)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert "cxx_std_20" in lib.compile_features
    assert "cxx_std_20" not in lib.public_compile_features


def test_cxx_std_not_applied_to_c_sources(tmp_path: Path) -> None:
    """Test cxx_std flags only apply to C++ sources."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.c", "main.cpp"], line=1),
        Command(name="target_compile_features", args=["myapp", "PUBLIC", "cxx_std_20"], line=2),
    ]
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")
    lines = ninja_path.read_text().splitlines()

    c_line_idx = next(i for i, line in enumerate(lines) if " main.c" in line)
    c_line_block = "\n".join(lines[c_line_idx : c_line_idx + 2])
    assert "-std=c++20" not in c_line_block

    cxx_line_idx = next(i for i, line in enumerate(lines) if " main.cpp" in line)
    cxx_line_block = "\n".join(lines[cxx_line_idx : cxx_line_idx + 2])
    assert "-std=c++20" in cxx_line_block
