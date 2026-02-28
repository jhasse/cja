"""Tests for interface library behavior."""

from pathlib import Path

from cja.generator import configure


def test_interface_library_not_linked_as_l_flag(tmp_path: Path) -> None:
    """Linking an INTERFACE library should not emit -l<name>."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "main.cpp").write_text("int main() { return 0; }\n")
    (source_dir / "CMakeLists.txt").write_text(
        "\n".join(
            [
                "cmake_minimum_required(VERSION 3.15)",
                "project(interface_link LANGUAGES CXX)",
                "add_library(mylib INTERFACE)",
                "target_include_directories(mylib INTERFACE include)",
                "add_executable(app main.cpp)",
                "target_link_libraries(app PRIVATE mylib)",
            ]
        )
        + "\n"
    )

    configure(source_dir, "build")
    ninja = (source_dir / "build.ninja").read_text()
    assert "-lmylib" not in ninja
