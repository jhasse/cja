"""Tests for math() command."""

from pathlib import Path

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_math_expr_basic() -> None:
    """Test basic math(EXPR) operations."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="math", args=["EXPR", "RESULT", "1 + 2 * 3"], line=1),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "7"


def test_math_expr_variables() -> None:
    """Test math(EXPR) with variables."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["VAL"] = "10"
    commands = [
        Command(name="math", args=["EXPR", "RESULT", "${VAL} * 2"], line=1),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "20"


def test_math_expr_unquoted() -> None:
    """Test math(EXPR) with unquoted expression (multiple arguments)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="math", args=["EXPR", "RESULT", "1", "+", "2"], line=1),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "3"


def test_math_expr_hex() -> None:
    """Test math(EXPR) with HEXADECIMAL output format."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="math", args=["EXPR", "RESULT", "15 + 1", "OUTPUT_FORMAT", "HEXADECIMAL"], line=1),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "0x10"


def test_math_expr_division() -> None:
    """Test math(EXPR) integer division."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="math", args=["EXPR", "RESULT", "10 / 3"], line=1),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "3"


def test_math_expr_bitwise() -> None:
    """Test math(EXPR) bitwise operations."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="math", args=["EXPR", "RESULT", "1 << 4 | 1"], line=1),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "17"


def test_math_expr_leading_zeros() -> None:
    """Test math(EXPR) with leading-zero decimal literals."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="math", args=["EXPR", "RESULT", "007 + 1"], line=1),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "8"


def test_math_expr_leading_whitespace() -> None:
    """Test math(EXPR) with leading whitespace and newlines in expression."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="math",
            args=["EXPR", "RESULT", "   0700\n/ 100"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "7"
