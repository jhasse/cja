"""Tests for GNUInstallDirs module."""

from pathlib import Path
from cja.generator import configure


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
    assert (
        ctx.variables["CMAKE_INSTALL_FULL_INCLUDEDIR"]
        == f"{ctx.variables['CMAKE_INSTALL_PREFIX']}/include"
    )
    assert (
        ctx.variables["CMAKE_INSTALL_FULL_LIBDIR"]
        == f"{ctx.variables['CMAKE_INSTALL_PREFIX']}/lib"
    )


def test_gnu_install_dirs_full_dirs_with_overrides(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_install)\n"
        "set(CMAKE_INSTALL_PREFIX /opt/test)\n"
        "set(CMAKE_INSTALL_INCLUDEDIR include/custom)\n"
        "set(CMAKE_INSTALL_LIBDIR lib/custom)\n"
        "include(GNUInstallDirs)\n"
    )

    ctx = configure(source_dir, "build")

    assert ctx.variables["CMAKE_INSTALL_FULL_INCLUDEDIR"] == "/opt/test/include/custom"
    assert ctx.variables["CMAKE_INSTALL_FULL_LIBDIR"] == "/opt/test/lib/custom"
