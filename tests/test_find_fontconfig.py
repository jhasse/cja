"""Tests for find_package(Fontconfig)."""

import subprocess
from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def has_pkg_config_fontconfig() -> bool:
    """Check if pkg-config can find fontconfig."""
    try:
        result = subprocess.run(
            ["pkg-config", "--exists", "fontconfig"], capture_output=True
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


@pytest.mark.skipif(
    not has_pkg_config_fontconfig(), reason="fontconfig not found via pkg-config"
)
def test_find_package_fontconfig_found() -> None:
    """Test find_package(Fontconfig) when fontconfig is available."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["Fontconfig"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["Fontconfig_FOUND"] == "TRUE"
    assert ctx.variables["FONTCONFIG_FOUND"] == "TRUE"
    assert "Fontconfig_LIBRARIES" in ctx.variables
    assert "Fontconfig::Fontconfig" in ctx.imported_targets


@pytest.mark.skipif(
    not has_pkg_config_fontconfig(), reason="fontconfig not found via pkg-config"
)
def test_find_package_fontconfig_imported_target() -> None:
    """Test find_package(Fontconfig) creates Fontconfig::Fontconfig imported target."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["Fontconfig"], line=1)]
    process_commands(commands, ctx)

    assert "Fontconfig::Fontconfig" in ctx.imported_targets
    target = ctx.imported_targets["Fontconfig::Fontconfig"]
    assert target.libs


@pytest.mark.skipif(
    not has_pkg_config_fontconfig(), reason="fontconfig not found via pkg-config"
)
def test_find_package_fontconfig_version() -> None:
    """Test find_package(Fontconfig) sets version."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["Fontconfig"], line=1)]
    process_commands(commands, ctx)

    assert "Fontconfig_VERSION" in ctx.variables
    # Version should look like X.Y.Z
    version = ctx.variables["Fontconfig_VERSION"]
    assert len(version.split(".")) >= 2


@pytest.mark.skipif(
    not has_pkg_config_fontconfig(), reason="fontconfig not found via pkg-config"
)
def test_find_package_fontconfig_link() -> None:
    """Test that linking against Fontconfig::Fontconfig works."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["Fontconfig"], line=1),
        Command(name="add_executable", args=["myapp", "main.c"], line=2),
        Command(
            name="target_link_libraries",
            args=["myapp", "Fontconfig::Fontconfig"],
            line=3,
        ),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "Fontconfig::Fontconfig" in exe.link_libraries
