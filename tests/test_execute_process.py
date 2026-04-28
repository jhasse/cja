"""Tests for execute_process command."""

from pathlib import Path
import sys
import pytest
from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_execute_process_basic() -> None:
    """Test basic execute_process with output variable."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="execute_process",
            args=[
                "COMMAND",
                sys.executable,
                "-c",
                "print('hello')",
                "OUTPUT_VARIABLE",
                "OUT",
            ],
            line=1,
        )
    ]
    process_commands(commands, ctx)

    assert "OUT" in ctx.variables
    assert "hello" in ctx.variables["OUT"]


def test_execute_process_result_variable() -> None:
    """Test execute_process with result variable."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="execute_process",
            args=[
                "COMMAND",
                sys.executable,
                "-c",
                "import sys; sys.exit(0)",
                "RESULT_VARIABLE",
                "RES",
            ],
            line=1,
        )
    ]
    process_commands(commands, ctx)

    assert ctx.variables["RES"] == "0"


def test_execute_process_strip_whitespace() -> None:
    """Test execute_process with OUTPUT_STRIP_TRAILING_WHITESPACE."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="execute_process",
            args=[
                "COMMAND",
                sys.executable,
                "-c",
                "print('hello')",
                "OUTPUT_VARIABLE",
                "OUT",
                "OUTPUT_STRIP_TRAILING_WHITESPACE",
            ],
            line=1,
        )
    ]
    process_commands(commands, ctx)

    assert ctx.variables["OUT"] == "hello"


def test_execute_process_working_directory(tmp_path: Path) -> None:
    """Test execute_process with WORKING_DIRECTORY."""
    # Create a subdirectory
    subdir = tmp_path / "subdir"
    subdir.mkdir()

    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="execute_process",
            args=[
                "COMMAND",
                sys.executable,
                "-c",
                "import os\nprint(os.getcwd())",
                "WORKING_DIRECTORY",
                str(subdir),
                "OUTPUT_VARIABLE",
                "OUT",
                "OUTPUT_STRIP_TRAILING_WHITESPACE",
            ],
            line=1,
        )
    ]
    process_commands(commands, ctx)

    assert ctx.variables["OUT"] == str(subdir)


def test_execute_process_error_variable() -> None:
    """Test execute_process with ERROR_VARIABLE."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="execute_process",
            args=[
                "COMMAND",
                sys.executable,
                "-c",
                "import sys\nprint('error', file=sys.stderr)",
                "ERROR_VARIABLE",
                "ERR",
                "ERROR_STRIP_TRAILING_WHITESPACE",
            ],
            line=1,
        )
    ]
    process_commands(commands, ctx)

    assert ctx.variables["ERR"] == "error"


def test_execute_process_output_quiet(capsys: pytest.CaptureFixture[str]) -> None:
    """Test execute_process with OUTPUT_QUIET."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="execute_process",
            args=[
                "COMMAND",
                sys.executable,
                "-c",
                "print('quiet-stdout')",
                "OUTPUT_QUIET",
                "OUTPUT_VARIABLE",
                "OUT",
            ],
            line=1,
        )
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert ctx.variables["OUT"] == ""


def test_execute_process_error_quiet(capsys: pytest.CaptureFixture[str]) -> None:
    """Test execute_process with ERROR_QUIET."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="execute_process",
            args=[
                "COMMAND",
                sys.executable,
                "-c",
                "import sys\nprint('quiet-stderr', file=sys.stderr)",
                "ERROR_QUIET",
                "ERROR_VARIABLE",
                "ERR",
            ],
            line=1,
        )
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert captured.err == ""
    assert ctx.variables["ERR"] == ""


def test_execute_process_command_not_found() -> None:
    """Test execute_process with non-existent command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="execute_process",
            args=[
                "COMMAND",
                "nonexistent_command_12345",
                "RESULT_VARIABLE",
                "RES",
            ],
            line=1,
        )
    ]
    process_commands(commands, ctx)

    assert ctx.variables["RES"] == "1"


def test_execute_process_empty_argument_filtered() -> None:
    """An empty argument (e.g. from an undefined variable expansion) must not
    crash and should be filtered out, matching CMake's behavior where an
    unquoted ``${UNDEFINED}`` produces no argument at all.
    """
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="execute_process",
            args=[
                "COMMAND",
                "",  # simulates ${CMAKE_LINKER} expanding to empty
                sys.executable,
                "-c",
                "print('ok')",
                "OUTPUT_VARIABLE",
                "OUT",
                "OUTPUT_STRIP_TRAILING_WHITESPACE",
                "RESULT_VARIABLE",
                "RES",
            ],
            line=1,
        )
    ]
    process_commands(commands, ctx)

    assert ctx.variables["RES"] == "0"
    assert ctx.variables["OUT"] == "ok"


def test_execute_process_all_empty_command() -> None:
    """A command made entirely of empty arguments should not crash and should
    set RESULT_VARIABLE to a non-zero value.
    """
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="execute_process",
            args=[
                "COMMAND",
                "",
                "RESULT_VARIABLE",
                "RES",
                "OUTPUT_VARIABLE",
                "OUT",
                "ERROR_VARIABLE",
                "ERR",
            ],
            line=1,
        )
    ]
    process_commands(commands, ctx)

    assert ctx.variables["RES"] == "1"
    assert ctx.variables["OUT"] == ""
    assert ctx.variables["ERR"] == ""


def test_execute_process_oserror_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A generic OSError from ``subprocess.run`` (e.g. WinError 87 on Windows
    when an invalid executable path is given) must be handled gracefully.
    """
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError(87, "The parameter is incorrect")

    monkeypatch.setattr("cja.generator.subprocess.run", fake_run)

    commands = [
        Command(
            name="execute_process",
            args=[
                "COMMAND",
                "some_command",
                "RESULT_VARIABLE",
                "RES",
            ],
            line=1,
        )
    ]
    process_commands(commands, ctx)

    assert ctx.variables["RES"] == "1"


def test_execute_process_command_error_is_fatal_any(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """COMMAND_ERROR_IS_FATAL ANY should raise on non-zero exit."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        return type(
            "Result",
            (),
            {"returncode": 1, "stdout": "", "stderr": "boom"},
        )()

    monkeypatch.setattr("cja.generator.subprocess.run", fake_run)

    commands = [
        Command(
            name="execute_process",
            args=[
                "COMMAND",
                "git",
                "submodule",
                "update",
                "--init",
                "subprojects/spine-runtimes",
                "COMMAND_ERROR_IS_FATAL",
                "ANY",
            ],
            line=1,
        )
    ]

    with pytest.raises(SystemExit):
        process_commands(commands, ctx)
