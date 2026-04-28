"""Tests for check_type_size command."""

from pathlib import Path
import ctypes

from cja.build_context import BuildContext
from cja.configurator import process_commands
from cja.parser import Command


def test_check_type_size_sets_common_sizes() -> None:
    """Common fixed-width and primitive types should report expected sizes."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="check_type_size", args=["int16_t", "INT16_SIZE"], line=1),
        Command(name="check_type_size", args=["short", "SHORT_SIZE"], line=2),
        Command(name="check_type_size", args=["void*", "CMAKE_SIZEOF_VOID_P"], line=3),
    ]

    process_commands(commands, ctx)

    assert ctx.variables["INT16_SIZE"] == "2"
    assert ctx.variables["SHORT_SIZE"] == str(ctypes.sizeof(ctypes.c_short))
    assert ctx.variables["CMAKE_SIZEOF_VOID_P"] == str(ctypes.sizeof(ctypes.c_void_p))


def test_check_type_size_unknown_type_is_empty() -> None:
    """Unavailable types should produce an empty result variable."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="check_type_size", args=["totally_unknown_t", "UNKNOWN_SIZE"], line=1)
    ]

    process_commands(commands, ctx)

    assert ctx.variables["UNKNOWN_SIZE"] == ""
