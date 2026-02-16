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
