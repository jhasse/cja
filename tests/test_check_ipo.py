"""Tests for check_ipo_supported command."""

import platform
import subprocess
from pathlib import Path

import pytest

from cja import configurator
from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_check_ipo_supported_result() -> None:
    """Test check_ipo_supported sets RESULT variable."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="check_ipo_supported", args=["RESULT", "IPO_SUPPORTED"], line=1),
    ]
    process_commands(commands, ctx)

    assert "IPO_SUPPORTED" in ctx.variables
    # Should be TRUE or FALSE
    assert ctx.variables["IPO_SUPPORTED"] in ("TRUE", "FALSE")


def test_check_ipo_supported_with_output() -> None:
    """Test check_ipo_supported sets OUTPUT variable on failure."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_ipo_supported",
            args=["RESULT", "IPO_SUPPORTED", "OUTPUT", "IPO_ERROR"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert "IPO_SUPPORTED" in ctx.variables
    assert "IPO_ERROR" in ctx.variables
    # If supported, error should be empty; if not, it should have a message
    if ctx.variables["IPO_SUPPORTED"] == "TRUE":
        assert ctx.variables["IPO_ERROR"] == ""


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only")
def test_check_ipo_supported_with_clang_on_windows() -> None:
    """Test check_ipo_supported succeeds with clang on Windows (uses lld-link)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="check_ipo_supported",
            args=["RESULT", "IPO_SUPPORTED", "OUTPUT", "IPO_ERROR"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["IPO_SUPPORTED"] == "TRUE", ctx.variables["IPO_ERROR"]


@pytest.mark.parametrize("system", ["Linux", "Windows"])
@pytest.mark.parametrize(
    "variables, expected_flags",
    [
        ({"CMAKE_EXE_LINKER_FLAGS": "-fuse-ld=mold"}, ["-fuse-ld=mold"]),
        ({"CMAKE_LINKER_FLAGS": "-fuse-ld=lld"}, ["-fuse-ld=lld"]),
        (
            {
                "CMAKE_EXE_LINKER_FLAGS": '-fuse-ld=mold -L"/path with spaces"',
                "CMAKE_LINKER_FLAGS": "-Wl,--as-needed",
            },
            ["-fuse-ld=mold", "-L/path with spaces", "-Wl,--as-needed"],
        ),
    ],
)
def test_check_ipo_supported_honors_linker_flags(
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    variables: dict[str, str],
    expected_flags: list[str],
) -> None:
    """Probe with the same linker options and ordering as generated links."""
    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(configurator.platform, "system", lambda: system)
    monkeypatch.setattr(configurator.subprocess, "run", fake_run)
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables.update(variables)

    process_commands(
        [Command(name="check_ipo_supported", args=["RESULT", "IPO_SUPPORTED"], line=1)],
        ctx,
    )

    assert ctx.variables["IPO_SUPPORTED"] == "TRUE"
    assert len(calls) == 1
    flags = expected_flags + (["-fuse-ld=lld-link"] if system == "Windows" else [])
    assert calls[0][-len(flags) :] == flags
