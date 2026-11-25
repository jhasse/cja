"""Tests for find_package(Git) using the bundled FindGit.cmake."""

import re
import subprocess
from pathlib import Path

import pytest

from cja.generator import configure, run_script


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
    git = ctx.imported_targets["Git::Git"]
    assert git.executable
    assert git.properties["IMPORTED_LOCATION"] == ctx.variables["GIT_EXECUTABLE"]


def test_git_target_in_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(demo NONE)\n"
        "find_package(Git REQUIRED)\n"
        "add_custom_target(version COMMAND Git::Git --version)\n"
    )
    monkeypatch.chdir(tmp_path)

    ctx = configure(tmp_path, "build", strict=True, quiet=True)

    # Unwrap the lines that ninja_syntax continues with a trailing "$"
    ninja = re.sub(r"\$\n *", "", (tmp_path / "build.ninja").read_text())
    assert "Git::Git" not in ninja
    command = next(line for line in ninja.splitlines() if " --version && " in line)
    assert Path(ctx.variables["GIT_EXECUTABLE"]).name in command


def test_find_git_in_script_mode(tmp_path: Path) -> None:
    """Scripts can't define targets, so Git::Git is only for projects."""
    script = tmp_path / "script.cmake"
    script.write_text("find_package(Git REQUIRED)\n")

    ctx = run_script(script, strict=True, quiet=True)

    assert ctx.variables["Git_FOUND"] == "TRUE"
    assert "Git::Git" not in ctx.imported_targets
