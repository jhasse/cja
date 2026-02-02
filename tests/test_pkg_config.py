"""Tests for PkgConfig support."""

from pathlib import Path
import subprocess

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


def test_find_package_pkgconfig() -> None:
    """Test find_package(PkgConfig)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["PkgConfig"], line=1),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["PkgConfig_FOUND"] == "TRUE"
    assert "PKG_CONFIG_EXECUTABLE" in ctx.variables


def test_pkg_check_modules_zlib() -> None:
    """Test pkg_check_modules with zlib (assuming it's installed)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["PkgConfig"], line=1),
        Command(name="pkg_check_modules", args=["ZLIB", "zlib"], line=2),
    ]
    process_commands(commands, ctx)

    # On most systems zlib is found
    if ctx.variables.get("ZLIB_FOUND") == "1":
        assert "ZLIB_LIBRARIES" in ctx.variables
        assert "ZLIB_INCLUDE_DIRS" in ctx.variables
    else:
        # If not found, it shouldn't crash unless REQUIRED was specified
        assert ctx.variables.get("ZLIB_FOUND") == "0"


def test_pkg_check_modules_link_libraries() -> None:
    """Test that pkg_check_modules sets _LINK_LIBRARIES."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["PkgConfig"], line=1),
        Command(name="pkg_check_modules", args=["ZLIB", "zlib"], line=2),
    ]
    process_commands(commands, ctx)

    if ctx.variables.get("ZLIB_FOUND") == "1":
        assert "ZLIB_LINK_LIBRARIES" in ctx.variables
        assert ctx.variables["ZLIB_LINK_LIBRARIES"] != ""


def test_pkg_check_modules_imported_target() -> None:
    """Test pkg_check_modules with IMPORTED_TARGET."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["PkgConfig"], line=1),
        Command(
            name="pkg_check_modules", args=["ZLIB", "IMPORTED_TARGET", "zlib"], line=2
        ),
    ]
    process_commands(commands, ctx)

    if ctx.variables.get("ZLIB_FOUND") == "1":
        assert "PkgConfig::ZLIB" in ctx.imported_targets
        target = ctx.imported_targets["PkgConfig::ZLIB"]
        assert target.libs is not None
