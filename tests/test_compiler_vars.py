"""Tests for CMAKE_C_COMPILER and CMAKE_CXX_COMPILER."""

from pathlib import Path
import platform
from cja.generator import configure


def test_cmake_c_compiler(tmp_path: Path) -> None:
    """Test that CMAKE_C_COMPILER can be set via -D flag."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_compiler)\nadd_executable(main main.c)"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")

    configure(source_dir, "build", variables={"CMAKE_C_COMPILER": "gcc"})

    ninja_file = source_dir / "build.ninja"
    content = ninja_file.read_text()

    # Check that the compiler variable is set to gcc
    assert "cc = gcc" in content


def test_cmake_cxx_compiler(tmp_path: Path) -> None:
    """Test that CMAKE_CXX_COMPILER can be set via -D flag."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_compiler)\nadd_executable(main main.cpp)"
    )
    (source_dir / "main.cpp").write_text("int main() { return 0; }")

    configure(source_dir, "build", variables={"CMAKE_CXX_COMPILER": "g++"})

    ninja_file = source_dir / "build.ninja"
    content = ninja_file.read_text()

    # Check that the compiler variable is set to g++
    assert "cxx = g++" in content


def test_both_compilers(tmp_path: Path) -> None:
    """Test that both CMAKE_C_COMPILER and CMAKE_CXX_COMPILER can be set."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_compiler)\n"
        "add_executable(main_c main.c)\n"
        "add_executable(main_cpp main.cpp)"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")
    (source_dir / "main.cpp").write_text("int main() { return 0; }")

    configure(
        source_dir,
        "build",
        variables={
            "CMAKE_C_COMPILER": "clang",
            "CMAKE_CXX_COMPILER": "clang++",
        },
    )

    ninja_file = source_dir / "build.ninja"
    content = ninja_file.read_text()

    # Check that both compiler variables are set correctly
    assert "cc = clang" in content
    assert "cxx = clang++" in content


def test_default_compilers(tmp_path: Path) -> None:
    """Test that default compilers are used when not specified."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_compiler)\nadd_executable(main main.c)"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")

    ctx = configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    content = ninja_file.read_text()

    # Check that default compilers are used
    if platform.system() == "Windows":
        assert "cc = clang" in content
        assert "cxx = clang++" in content
        assert ctx.variables["CMAKE_C_COMPILER"] == "clang"
        assert ctx.variables["CMAKE_CXX_COMPILER"] == "clang++"
        assert ctx.variables["CMAKE_C_COMPILER_ID"] == "Clang"
        assert ctx.variables["CMAKE_CXX_COMPILER_ID"] == "Clang"
    else:
        assert "cc = cc" in content
        assert "cxx = c++" in content
        assert ctx.variables["CMAKE_C_COMPILER"] == "cc"
        assert ctx.variables["CMAKE_CXX_COMPILER"] == "c++"
        assert ctx.variables["CMAKE_C_COMPILER_ID"] != "Unknown"
        assert ctx.variables["CMAKE_CXX_COMPILER_ID"] != "Unknown"


def test_compiler_id_variables(tmp_path: Path) -> None:
    """Test that CMAKE_<LANG>_COMPILER_ID variables are populated."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text("project(test_compiler_ids)")

    ctx = configure(
        source_dir,
        "build",
        variables={
            "CMAKE_C_COMPILER": "gcc",
            "CMAKE_CXX_COMPILER": "clang++",
        },
    )

    assert ctx.variables["CMAKE_C_COMPILER"] == "gcc"
    assert ctx.variables["CMAKE_CXX_COMPILER"] == "clang++"
    assert ctx.variables["CMAKE_C_COMPILER_ID"] == "GNU"
    assert ctx.variables["CMAKE_CXX_COMPILER_ID"] == "Clang"
