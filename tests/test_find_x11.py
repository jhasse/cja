"""Tests for find_package(X11)."""

import subprocess
from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def has_x11() -> bool:
    """Check if pkg-config can find x11."""
    try:
        result = subprocess.run(
            ["pkg-config", "--exists", "x11"], capture_output=True
        )
        if result.returncode == 0:
            return True
    except FileNotFoundError:
        pass
    return any(
        (Path(inc) / "X11" / "Xlib.h").exists()
        for inc in ("/usr/include", "/usr/local/include", "/opt/X11/include")
    )


@pytest.mark.skipif(not has_x11(), reason="X11 not found")
def test_find_package_x11_found() -> None:
    """Test find_package(X11) when X11 is available."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["X11"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["X11_FOUND"] == "TRUE"
    assert ctx.variables["X11_X11_FOUND"] == "TRUE"
    assert ctx.variables.get("X11_X11_LIB")
    assert "X11::X11" in ctx.imported_targets


@pytest.mark.skipif(not has_x11(), reason="X11 not found")
def test_find_package_x11_imported_target() -> None:
    """Test find_package(X11) creates an X11::X11 imported target with libs."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["X11"], line=1)]
    process_commands(commands, ctx)

    target = ctx.imported_targets["X11::X11"]
    assert target.libs


@pytest.mark.skipif(not has_x11(), reason="X11 not found")
def test_find_package_x11_link() -> None:
    """Test that linking against X11::X11 works."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="find_package", args=["X11"], line=1),
        Command(name="add_executable", args=["myapp", "main.c"], line=2),
        Command(
            name="target_link_libraries",
            args=["myapp", "X11::X11"],
            line=3,
        ),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "X11::X11" in exe.link_libraries


@pytest.mark.skipif(not has_x11(), reason="X11 not found")
def test_find_package_x11_xkb_found() -> None:
    """Test find_package(X11) sets X11_Xkb_FOUND when XKBlib.h is present."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["X11"], line=1)]
    process_commands(commands, ctx)

    # X11_Xkb_FOUND must always be set to TRUE or FALSE after the command.
    assert ctx.variables["X11_Xkb_FOUND"] in ("TRUE", "FALSE")
    if ctx.variables["X11_Xkb_FOUND"] == "TRUE":
        assert ctx.variables.get("X11_Xkb_INCLUDE_PATH")


@pytest.mark.skipif(not has_x11(), reason="X11 not found")
def test_find_package_x11_required_found() -> None:
    """Test find_package(X11 REQUIRED) does not raise when X11 is available."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["X11", "REQUIRED"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["X11_FOUND"] == "TRUE"


def test_find_package_x11_not_required() -> None:
    """Test find_package(X11) without REQUIRED does not raise."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["X11"], line=1)]
    # Should not raise regardless of availability.
    process_commands(commands, ctx)
    assert ctx.variables.get("X11_FOUND") in ("TRUE", "FALSE")
