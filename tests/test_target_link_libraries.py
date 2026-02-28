"""Tests for target_link_libraries edge cases."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_target_link_libraries_skips_empty_argument() -> None:
    """Empty library arguments should be ignored."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.c"], line=1),
        Command(
            name="target_link_libraries", args=["myapp", "PRIVATE", "", "m"], line=2
        ),
    ]
    process_commands(commands, ctx, strict=True)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert exe.link_libraries == ["m"]


def test_add_library_empty_target_name_fails() -> None:
    """add_library() should fail for empty target names."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["", "STATIC", "lib.c"], line=1),
    ]

    with pytest.raises(SystemExit) as exc_info:
        process_commands(commands, ctx, strict=True)
    assert exc_info.value.code == 1
