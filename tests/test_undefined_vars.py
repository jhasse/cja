"""Tests for undefined variable warnings."""

from pathlib import Path

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_undefined_variable_warning(capsys) -> None:
    """Test that undefined variables generate a warning."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["RESULT", "${UNDEFINED_VAR}"], line=1),
    ]
    process_commands(commands, ctx, strict=False)

    captured = capsys.readouterr()
    assert "CMakeLists.txt:1:" in captured.err
    assert "warning:" in captured.err
    assert "undefined variable referenced: UNDEFINED_VAR" in captured.err
    # Variable should be set to empty string
    assert ctx.variables["RESULT"] == ""


def test_undefined_variable_strict_mode(capsys) -> None:
    """Test that undefined variables cause errors in strict mode."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["RESULT", "${UNDEFINED_VAR}"], line=1),
    ]

    try:
        process_commands(commands, ctx, strict=True)
        assert False, "Should have raised SystemExit"
    except SystemExit:
        # Expected
        pass

    captured = capsys.readouterr()
    assert "CMakeLists.txt:1:" in captured.err
    assert "error:" in captured.err
    assert "undefined variable referenced: UNDEFINED_VAR" in captured.err


def test_nested_undefined_variable_warns_in_strict_mode(capsys) -> None:
    """${${VAR}} should warn (not error) in strict mode when unresolved."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["VAR", "UNDEFINED_VAR"], line=1),
        Command(name="set", args=["RESULT", "${${VAR}}"], line=2),
    ]
    process_commands(commands, ctx, strict=True)

    captured = capsys.readouterr()
    assert "CMakeLists.txt:2:" in captured.err
    assert "warning:" in captured.err
    assert "undefined variable referenced: UNDEFINED_VAR" in captured.err
    assert "error:" not in captured.err
    assert ctx.variables["RESULT"] == ""


def test_escaped_variable_marker_is_literal_in_strict_mode(capsys) -> None:
    """\\${VAR} should remain literal and not trigger strict undefined errors."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["RESULT", r"\${exec_prefix}"], line=1, is_quoted=[False, True]),
    ]
    process_commands(commands, ctx, strict=True)

    captured = capsys.readouterr()
    assert captured.err == ""
    assert ctx.variables["RESULT"] == "${exec_prefix}"


def test_escaped_variable_marker_not_recursively_expanded(capsys) -> None:
    """A value containing escaped ${...} should stay literal when re-referenced."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["A", r"\${exec_prefix}"], line=1, is_quoted=[False, True]),
        Command(name="set", args=["B", "${A}"], line=2),
    ]
    process_commands(commands, ctx, strict=True)

    captured = capsys.readouterr()
    assert captured.err == ""
    assert ctx.variables["B"] == "${exec_prefix}"
