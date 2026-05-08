"""Tests for find_package(Freetype)."""

import subprocess
from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def has_pkg_config_freetype() -> bool:
    """Check if pkg-config can find freetype2."""
    try:
        for candidate in ("freetype2", "freetype"):
            result = subprocess.run(
                ["pkg-config", "--exists", candidate], capture_output=True
            )
            if result.returncode == 0:
                return True
        return False
    except FileNotFoundError:
        return False


@pytest.mark.skipif(
    not has_pkg_config_freetype(), reason="freetype not found via pkg-config"
)
def test_find_package_freetype_found() -> None:
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["Freetype"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["Freetype_FOUND"] == "TRUE"
    assert ctx.variables["FREETYPE_FOUND"] == "TRUE"
    assert "FREETYPE_LIBRARIES" in ctx.variables
    assert "Freetype::Freetype" in ctx.imported_targets


@pytest.mark.skipif(
    not has_pkg_config_freetype(), reason="freetype not found via pkg-config"
)
def test_find_package_freetype_imported_target() -> None:
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["Freetype"], line=1)]
    process_commands(commands, ctx)

    assert "Freetype::Freetype" in ctx.imported_targets
    target = ctx.imported_targets["Freetype::Freetype"]
    assert target.libs


def test_find_package_freetype_not_required_missing() -> None:
    """find_package(Freetype) without REQUIRED should not raise when missing."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    # Patch subprocess to simulate freetype not found
    import unittest.mock as mock

    def fake_run(args, **kwargs):
        m = mock.MagicMock()
        m.returncode = 1
        m.stdout = ""
        return m

    commands = [Command(name="find_package", args=["Freetype"], line=1)]
    with mock.patch("subprocess.run", side_effect=fake_run):
        process_commands(commands, ctx)

    assert ctx.variables["Freetype_FOUND"] == "FALSE"
    assert ctx.variables["FREETYPE_FOUND"] == "FALSE"
