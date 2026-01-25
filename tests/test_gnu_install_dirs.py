"""Tests for GNUInstallDirs module."""

from pathlib import Path
from cninja.generator import configure


def test_gnu_install_dirs(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_install)\n"
        "include(GNUInstallDirs)\n"
        "set(BINDIR ${CMAKE_INSTALL_BINDIR})\n"
        "set(DOCDIR ${CMAKE_INSTALL_DOCDIR})\n"
    )

    ctx = configure(source_dir, "build")

    assert ctx.variables["BINDIR"] == "bin"
    assert ctx.variables["DOCDIR"] == "share/doc/test_install"
