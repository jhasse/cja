"""Test compilation database generation."""

from pathlib import Path
import json
from cja.generator import configure


def test_compile_commands_json(tmp_path: Path) -> None:
    source_dir = tmp_path
    (source_dir / "main.c").write_text("int main() { return 0; }")
    (source_dir / "CMakeLists.txt").write_text(
        """
cmake_minimum_required(VERSION 3.10)
project(compdb_prj)
add_executable(myexe main.c)
"""
    )

    configure(source_dir, "build")

    compdb_path = source_dir / "build" / "compile_commands.json"
    assert compdb_path.exists()

    with open(compdb_path) as f:
        data = json.load(f)

    assert len(data) > 0
    # Check if main.c is in the database
    files = [entry["file"] for entry in data]
    assert any("main.c" in f for f in files)
