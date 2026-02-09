"""Tests for CMAKE_C_FLAGS and CMAKE_CXX_FLAGS."""

from pathlib import Path
from cninja.generator import configure


def test_cmake_c_flags(tmp_path: Path) -> None:
    """Test that CMAKE_C_FLAGS are included in the ninja file."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_flags)\n"
        'set(CMAKE_C_FLAGS "-Wall -Wextra")\n'
        "add_executable(main main.c)"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    content = ninja_file.read_text()

    # Check that flags are in the rule or build statement
    # Our implementation will put them in the rule for simplicity
    assert "-Wall -Wextra" in content


def test_cmake_cxx_flags(tmp_path: Path) -> None:
    """Test that CMAKE_CXX_FLAGS are included in the ninja file."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_flags)\n"
        'set(CMAKE_CXX_FLAGS "-std=c++17")\n'
        "add_executable(main main.cpp)"
    )
    (source_dir / "main.cpp").write_text("int main() { return 0; }")

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    content = ninja_file.read_text()

    assert "-std=c++17" in content


def test_cmake_linker_flags(tmp_path: Path) -> None:
    """Test that CMAKE_LINKER_FLAGS are included in the ninja file."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_linker_flags)\n"
        'set(CMAKE_LINKER_FLAGS "-Wl,--as-needed")\n'
        "add_executable(main main.c)"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    content = ninja_file.read_text()

    assert "-Wl,--as-needed" in content
