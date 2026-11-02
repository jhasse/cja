"""Tests for the check_linker_flag command."""

import os
import platform
import subprocess
from pathlib import Path

import pytest

from cja import configurator
from cja.generator import BuildContext, process_commands
from cja.parser import parse


def _run(content: str, ctx: BuildContext | None = None) -> BuildContext:
    ctx = ctx or BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(parse(content), ctx)
    return ctx


def test_unsupported_flag() -> None:
    ctx = _run("check_linker_flag(C -fuse-ld=no-such-linker HAVE_FLAG)\n")
    assert ctx.variables["HAVE_FLAG"] == ""
    assert "CMAKE_REQUIRED_LINK_OPTIONS" not in ctx.variables


@pytest.mark.skipif(platform.system() != "Linux", reason="ELF linker flags")
def test_supported_flags() -> None:
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    # The flag replaces the link options instead of adding to them
    ctx.variables["CMAKE_REQUIRED_LINK_OPTIONS"] = "-fuse-ld=no-such-linker"
    _run(
        "check_linker_flag(C LINKER:-z,now HAVE_NOW)\n"
        'check_linker_flag(CXX "-Wl,--gc-sections;LINKER:-z,relro" HAVE_BOTH)\n',
        ctx,
    )
    assert ctx.variables["HAVE_NOW"] == "1"
    assert ctx.variables["HAVE_BOTH"] == "1"
    assert ctx.variables["CMAKE_REQUIRED_LINK_OPTIONS"] == "-fuse-ld=no-such-linker"


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("", "1"),
        ("ld: unrecognized option '--foo'", ""),
        ("warning: -Wl,--foo ignored", ""),
        ("warning: --bar ignored", "1"),
    ],
)
def test_ignored_flag(monkeypatch, output: str, expected: str) -> None:
    """Warnings about the flag fail the check, read in the C locale."""
    locales: list[str | None] = []

    def fake_run(
        cmd: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        locales.append(os.environ.get("LC_ALL"))
        return subprocess.CompletedProcess(cmd, 0, "", output)

    monkeypatch.setenv("LC_ALL", "de_DE.UTF-8")
    monkeypatch.setattr(configurator.subprocess, "run", fake_run)

    ctx = _run("check_linker_flag(C -Wl,--foo HAVE_FLAG)\n")
    assert ctx.variables["HAVE_FLAG"] == expected
    assert locales == ["C"]
    assert os.environ["LC_ALL"] == "de_DE.UTF-8"
