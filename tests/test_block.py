"""Tests for the block()/endblock() commands."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_block_scope_for_policies_no_op() -> None:
    """block(SCOPE_FOR POLICIES)/endblock() execute without error and run the body."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="block", args=["SCOPE_FOR", "POLICIES"], line=1),
        Command(name="set", args=["INSIDE_BLOCK", "yes"], line=2),
        Command(name="endblock", args=[], line=3),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["INSIDE_BLOCK"] == "yes"


def test_block_no_args() -> None:
    """Bare block()/endblock() is also accepted."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="block", args=[], line=1),
        Command(name="set", args=["INSIDE", "value"], line=2),
        Command(name="endblock", args=[], line=3),
    ]
    process_commands(commands, ctx)

    assert ctx.variables["INSIDE"] == "value"


def test_block_strict_mode_does_not_error() -> None:
    """block/endblock must not trigger 'unsupported command' in strict mode."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="block", args=["SCOPE_FOR", "POLICIES"], line=1),
        Command(name="endblock", args=[], line=2),
    ]
    process_commands(commands, ctx, strict=True)
