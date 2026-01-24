"""Test for shell redirection in add_custom_command."""

from pathlib import Path
from cninja.generator import configure


def test_custom_command_redirection(tmp_path: Path) -> None:
    source_dir = tmp_path
    cmake_content = """cmake_minimum_required(VERSION 3.10)
project(RedirTest)

add_custom_command(
    OUTPUT asd.txt
    COMMAND echo foo > asd.txt
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    ninja_content = ninja_file.read_text()

    # It should NOT be quoted
    assert "cmd = echo foo > asd.txt" in ninja_content
    assert "'>'" not in ninja_content


def test_custom_command_redirection_verbatim(tmp_path: Path) -> None:
    source_dir = tmp_path
    cmake_content = """cmake_minimum_required(VERSION 3.10)
project(RedirVerbatimTest)

add_custom_command(
    OUTPUT asd.txt
    COMMAND echo foo > asd.txt
    VERBATIM
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    ninja_content = ninja_file.read_text()

    # Even with VERBATIM, users often expect redirection to work if they didn't quote it
    # But CMake's VERBATIM is tricky.
    # If we want to fix the user's issue, we should probably NOT quote shell operators
    # even in VERBATIM mode if they are stand-alone tokens.
    assert "cmd = echo foo > asd.txt" in ninja_content
    assert "'>'" not in ninja_content
