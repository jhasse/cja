"""Tests for the archiver and linker that cja reports and uses."""

import platform
from pathlib import Path

import pytest

from cja.utils import default_archiver, find_linker


def test_ar_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AR", "my-ar")
    assert default_archiver("gcc-14") == "my-ar"


@pytest.mark.skipif(platform.system() == "Windows", reason="no gcc-ar on Windows")
def test_gcc_ar_next_to_gcc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A GCC other than the default one needs its own gcc-ar for LTO objects."""
    monkeypatch.delenv("AR", raising=False)
    for name in ("gcc-ar-14", "x86_64-linux-gnu-gcc-ar-13"):
        tool = tmp_path / name
        tool.write_text("#!/bin/sh\n")
        tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))

    assert default_archiver("gcc-14") == "gcc-ar-14"
    assert default_archiver(str(tmp_path / "gcc-14")) == str(tmp_path / "gcc-ar-14")
    assert default_archiver("x86_64-linux-gnu-gcc-13") == "x86_64-linux-gnu-gcc-ar-13"
    # No gcc-ar-15 there, and other compilers keep using ar
    assert default_archiver("gcc-15") == "ar"
    assert default_archiver("cc") == "ar"
    assert default_archiver("clang") == "ar"


def _tools(directory: Path, *names: str) -> None:
    directory.mkdir(exist_ok=True)
    for name in names:
        tool = directory / name
        tool.write_text("#!/bin/sh\n")
        tool.chmod(0o755)


@pytest.mark.skipif(
    platform.system() in ("Windows", "Darwin"), reason="lld-link or no ld.lld there"
)
def test_find_linker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Like CMake: the toolchain's ld next to the compiler, ld.lld for Clang."""
    toolchain = tmp_path / "toolchain"
    _tools(toolchain, "x86_64-linux-gnu-gcc-13", "x86_64-linux-gnu-ld", "ld.lld")
    _tools(tmp_path / "path", "gcc", "clang", "ld")
    monkeypatch.setenv("PATH", str(tmp_path / "path"))

    compiler = (toolchain / "x86_64-linux-gnu-gcc-13").as_posix()
    assert find_linker(compiler, "GNU") == f"{toolchain.as_posix()}/x86_64-linux-gnu-ld"
    assert find_linker("ccache gcc", "GNU") == f"{(tmp_path / 'path').as_posix()}/ld"
    # ld.lld isn't on the PATH, only next to the other compiler
    assert find_linker("clang", "Clang") == f"{(tmp_path / 'path').as_posix()}/ld"
    monkeypatch.setenv("PATH", f"{tmp_path / 'path'}:{toolchain}")
    assert find_linker("clang", "Clang") == f"{toolchain.as_posix()}/ld.lld"
    monkeypatch.setenv("PATH", "")
    assert find_linker("gcc", "GNU") == "CMAKE_LINKER-NOTFOUND"
