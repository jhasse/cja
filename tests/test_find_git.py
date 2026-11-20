"""Tests for find_package(Git) using the bundled FindGit.cmake."""

import subprocess
from pathlib import Path

import pytest

from cja.generator import configure


def test_find_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(demo NONE)\n"
        "find_package(Git 1.0 REQUIRED)\n"
    )
    monkeypatch.chdir(tmp_path)

    ctx = configure(tmp_path, "build", strict=True, quiet=True)

    assert ctx.variables["Git_FOUND"] == "TRUE"
    assert ctx.variables["GIT_FOUND"] == "TRUE"
    version = ctx.variables["Git_VERSION"]
    assert ctx.variables["GIT_VERSION_STRING"] == version
    result = subprocess.run(
        [ctx.variables["GIT_EXECUTABLE"], "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"git version {version}"
