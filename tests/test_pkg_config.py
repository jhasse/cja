"""Tests for PkgConfig support."""

from pathlib import Path
import subprocess
import pytest

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


def test_pkg_check_modules_library_dirs() -> None:
    """Test that pkg_check_modules sets _LIBRARY_DIRS."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["PkgConfig"], line=1),
        Command(name="pkg_check_modules", args=["ZLIB", "zlib"], line=2),
    ]
    process_commands(commands, ctx)

    if ctx.variables.get("ZLIB_FOUND") == "1":
        assert "ZLIB_LIBRARY_DIRS" in ctx.variables


def has_pkg_config_openssl() -> bool:
    """Check if pkg-config can find openssl."""
    try:
        result = subprocess.run(
            ["pkg-config", "--exists", "openssl"],
            capture_output=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


@pytest.mark.skipif(
    not has_pkg_config_openssl(), reason="openssl not found via pkg-config"
)
def test_pkg_check_modules_library_dirs_openssl() -> None:
    """Test that pkg_check_modules sets _LIBRARY_DIRS with actual paths for openssl."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["PkgConfig"], line=1),
        Command(name="pkg_check_modules", args=["OPENSSL", "openssl"], line=2),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["OPENSSL_FOUND"] == "1"
    # Openssl usually has a library dir on macOS (Homebrew) or some Linux distros
    # We at least check if it's set.
    assert "OPENSSL_LIBRARY_DIRS" in ctx.variables
    # On this machine we saw it had a path, let's verify if it's not empty if found
    lib_dirs = ctx.variables["OPENSSL_LIBRARY_DIRS"]
    if lib_dirs:
        assert Path(lib_dirs.split(";")[0]).exists()


def has_pkg_config_vorbisfile() -> bool:
    """Check if pkg-config can find vorbisfile."""
    try:
        result = subprocess.run(
            ["pkg-config", "--exists", "vorbisfile"],
            capture_output=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


@pytest.mark.skipif(
    not has_pkg_config_vorbisfile(), reason="vorbisfile not found via pkg-config"
)
def test_pkg_check_modules_vorbisfile_library_dirs() -> None:
    """Test that pkg_check_modules sets _LIBRARY_DIRS for vorbisfile."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["PkgConfig"], line=1),
        Command(
            name="pkg_check_modules",
            args=["VorbisFile", "REQUIRED", "vorbisfile"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["VorbisFile_FOUND"] == "1"
    assert "VorbisFile_LIBRARY_DIRS" in ctx.variables
    # Ensure it's a semicolon separated list and doesn't contain -L
    lib_dirs = ctx.variables["VorbisFile_LIBRARY_DIRS"]
    if lib_dirs:
        assert "-L" not in lib_dirs
        for d in lib_dirs.split(";"):
            assert Path(d).is_absolute()


@pytest.mark.skipif(
    not has_pkg_config_vorbisfile(), reason="vorbisfile not found via pkg-config"
)
def test_pkg_check_modules_vorbisfile_includedir() -> None:
    """Test that pkg_check_modules sets _INCLUDEDIR for vorbisfile."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["PkgConfig"], line=1),
        Command(
            name="pkg_check_modules",
            args=["VorbisFile", "REQUIRED", "vorbisfile"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["VorbisFile_FOUND"] == "1"
    assert "VorbisFile_INCLUDEDIR" in ctx.variables
    # Most systems have an includedir for vorbisfile
    assert ctx.variables["VorbisFile_INCLUDEDIR"] != ""


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


def test_pkg_check_modules_output(capsys, tmp_path):
    """Test the output of pkg_check_modules."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path)
    commands = [
        Command(name="find_package", args=["PkgConfig"], line=1),
        Command(name="pkg_check_modules", args=["ZLIB", "zlib"], line=2),
        Command(
            name="pkg_check_modules",
            args=["NONEXISTENT", "nonexistent_package_123"],
            line=3,
        ),
    ]
    process_commands(commands, ctx)
    captured = capsys.readouterr()
    assert "✓ PkgConfig" in captured.out
    assert "✓ zlib" in captured.out
    assert "✗ nonexistent_package_123" in captured.out


def test_pkg_check_modules_quiet_output(capsys, tmp_path):
    """Test that QUIET suppresses the output of pkg_check_modules."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path)
    commands = [
        Command(name="find_package", args=["PkgConfig"], line=1),
        Command(name="pkg_check_modules", args=["ZLIB", "QUIET", "zlib"], line=2),
        Command(
            name="pkg_check_modules",
            args=["NONEXISTENT", "QUIET", "nonexistent_package_123"],
            line=3,
        ),
    ]
    process_commands(commands, ctx)
    captured = capsys.readouterr()
    assert "✓ zlib" not in captured.out
    assert "✗ nonexistent_package_123" not in captured.out
