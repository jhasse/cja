"""Tests for find_package(FLEX)."""

import shutil
from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def has_flex() -> bool:
    return shutil.which("flex") is not None


@pytest.mark.skipif(not has_flex(), reason="flex not found")
def test_find_package_flex_found() -> None:
    """find_package(FLEX) sets FLEX_FOUND and the executable path."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["FLEX"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["FLEX_FOUND"] == "TRUE"
    assert ctx.variables["FLEX_EXECUTABLE"]
    assert Path(ctx.variables["FLEX_EXECUTABLE"]).exists()


@pytest.mark.skipif(not has_flex(), reason="flex not found")
def test_find_package_flex_version() -> None:
    """find_package(FLEX) reports the version returned by `flex --version`."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["FLEX"], line=1)]
    process_commands(commands, ctx)

    version = ctx.variables.get("FLEX_VERSION", "")
    assert version
    parts = version.split(".")
    assert all(p.isdigit() for p in parts)


def test_find_package_flex_not_required() -> None:
    """find_package(FLEX) without REQUIRED does not raise when missing."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["FLEX"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables.get("FLEX_FOUND") in ("TRUE", "FALSE")


def test_find_package_flex_required_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """find_package(FLEX REQUIRED) exits when flex is not on PATH."""
    monkeypatch.setattr(shutil, "which", lambda *_args, **_kwargs: None)
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_package", args=["FLEX", "REQUIRED"], line=1)]
    with pytest.raises(SystemExit) as exc_info:
        process_commands(commands, ctx)
    assert exc_info.value.code == 1
    assert ctx.variables["FLEX_FOUND"] == "FALSE"
