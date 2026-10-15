"""Tests for the archiver that static libraries are made with."""

import platform
from pathlib import Path

import pytest

from cja.generator import _default_archiver


def test_ar_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AR", "my-ar")
    assert _default_archiver("gcc-14") == "my-ar"


@pytest.mark.skipif(platform.system() == "Windows", reason="no gcc-ar on Windows")
def test_gcc_ar_next_to_gcc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A GCC other than the default one needs its own gcc-ar for LTO objects."""
    monkeypatch.delenv("AR", raising=False)
    for name in ("gcc-ar-14", "x86_64-linux-gnu-gcc-ar-13"):
        tool = tmp_path / name
        tool.write_text("#!/bin/sh\n")
        tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))

    assert _default_archiver("gcc-14") == "gcc-ar-14"
    assert _default_archiver(str(tmp_path / "gcc-14")) == str(tmp_path / "gcc-ar-14")
    assert (
        _default_archiver("x86_64-linux-gnu-gcc-13") == "x86_64-linux-gnu-gcc-ar-13"
    )
    # No gcc-ar-15 there, and other compilers keep using ar
    assert _default_archiver("gcc-15") == "ar"
    assert _default_archiver("cc") == "ar"
    assert _default_archiver("clang") == "ar"
