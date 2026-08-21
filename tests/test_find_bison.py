"""Tests for find_package(BISON)."""

import shutil
from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def has_bison() -> bool:
    return shutil.which("bison") is not None


@pytest.mark.skipif(not has_bison(), reason="bison not found")
def test_find_package_bison_found() -> None:
    """find_package(BISON) sets BISON_FOUND and the executable path."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["BISON"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["BISON_FOUND"] == "TRUE"
    assert ctx.variables["BISON_EXECUTABLE"]
    assert Path(ctx.variables["BISON_EXECUTABLE"]).exists()


@pytest.mark.skipif(not has_bison(), reason="bison not found")
def test_find_package_bison_version() -> None:
    """find_package(BISON) reports the version from `bison --version`."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["BISON"], line=1)]
    process_commands(commands, ctx)

    version = ctx.variables.get("BISON_VERSION", "")
    assert version
    parts = version.split(".")
    assert all(p.isdigit() for p in parts)


def test_find_package_bison_not_required() -> None:
    """find_package(BISON) without REQUIRED does not raise when missing."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["BISON"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables.get("BISON_FOUND") in ("TRUE", "FALSE")


def test_find_package_bison_required_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """find_package(BISON REQUIRED) exits when bison is not on PATH."""
    monkeypatch.setattr(shutil, "which", lambda *_args, **_kwargs: None)
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["BISON", "REQUIRED"], line=1)]
    with pytest.raises(SystemExit) as exc_info:
        process_commands(commands, ctx)
    assert exc_info.value.code == 1
    assert ctx.variables["BISON_FOUND"] == "FALSE"
