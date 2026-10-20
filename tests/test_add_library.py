"""Tests for add_library command."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


@pytest.mark.parametrize(
    ("build_shared_libs", "expected"),
    [(None, "STATIC"), ("OFF", "STATIC"), ("ON", "SHARED"), ("1", "SHARED")],
)
def test_add_library_default_type(build_shared_libs: str | None, expected: str) -> None:
    """Without a type, BUILD_SHARED_LIBS decides between STATIC and SHARED."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["lib", "lib.c"], line=1),
        Command(name="add_library", args=["static_lib", "STATIC", "lib.c"], line=2),
    ]
    if build_shared_libs is not None:
        commands.insert(0, Command(name="set", args=["BUILD_SHARED_LIBS", build_shared_libs]))
    process_commands(commands, ctx)

    lib = ctx.get_library("lib")
    static_lib = ctx.get_library("static_lib")
    assert lib is not None and static_lib is not None
    assert lib.lib_type == expected
    assert static_lib.lib_type == "STATIC"
