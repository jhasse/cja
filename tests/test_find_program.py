"""Tests for find_program command."""

import os
from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_find_program_basic() -> None:
    """Test finding a program that exists."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_program", args=["PYTHON", "python3", "python"], line=1)]
    process_commands(commands, ctx)

    assert "PYTHON" in ctx.variables
    assert os.path.basename(ctx.variables["PYTHON"]).lower().startswith(("python3", "python"))
    assert "NOTFOUND" not in ctx.variables["PYTHON"]


def test_find_program_with_names() -> None:
    """Test find_program with NAMES keyword."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_program", args=["SH", "NAMES", "sh", "bash"], line=1)]
    process_commands(commands, ctx)

    assert "SH" in ctx.variables
    assert "NOTFOUND" not in ctx.variables["SH"]


def test_find_program_not_found() -> None:
    """Test find_program when program doesn't exist."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_program", args=["NONEXISTENT", "nonexistent_xyz_123"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["NONEXISTENT"] == "NONEXISTENT-NOTFOUND"


def test_find_program_required_not_found() -> None:
    """Test find_program with REQUIRED when program doesn't exist."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="find_program", args=["NONEXISTENT", "nonexistent_xyz_123", "REQUIRED"], line=1)]

    with pytest.raises(FileNotFoundError, match="Could not find program"):
        process_commands(commands, ctx)


def test_find_program_followed_by_if(capsys: pytest.CaptureFixture[str]) -> None:
    """Test find_program followed by if statement (regression test for variable shadowing bug)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_VERSION"] = "0"
    commands = [
        Command(name="find_program", args=["MY_PROG", "nonexistent_xyz_123"], line=1),
        Command(name="if", args=["MY_VERSION", "GREATER", "1"], line=2),
        Command(name="message", args=["STATUS", "version is greater"], line=3),
        Command(name="else", args=[], line=4),
        Command(name="message", args=["STATUS", "version is not greater"], line=5),
        Command(name="endif", args=[], line=6),
    ]
    process_commands(commands, ctx)

    captured = capsys.readouterr()
    assert "version is not greater" in captured.out
    assert ctx.variables["MY_PROG"] == "MY_PROG-NOTFOUND"


def _run(commands: list[Command]) -> BuildContext:
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(commands, ctx)
    return ctx


def test_find_program_searches_again_after_notfound() -> None:
    """A NOTFOUND cache entry doesn't stop a later search, like in CMake."""
    ctx = _run(
        [
            Command(name="find_program", args=["PY", "nonexistent_prog_xyz"], line=1),
            Command(name="find_program", args=["PY", "python3", "python"], line=2),
        ]
    )
    assert "NOTFOUND" not in ctx.variables["PY"]
    assert ctx.cache_values["PY"] == ctx.variables["PY"]


def test_find_program_skips_when_already_set() -> None:
    """An existing non-NOTFOUND value (cache, normal or empty) skips the search."""
    ctx = _run(
        [
            Command(name="set", args=["P1", "/custom", "CACHE", "FILEPATH", ""], line=1),
            Command(name="find_program", args=["P1", "python3"], line=2),
            Command(name="set", args=["P2", "/normal"], line=3),
            Command(name="find_program", args=["P2", "python3"], line=4),
            Command(name="set", args=["P3", "", "CACHE", "FILEPATH", ""], line=5),
            Command(name="find_program", args=["P3", "python3"], line=6),
        ]
    )
    assert ctx.variables["P1"] == "/custom"
    assert ctx.variables["P2"] == "/normal"
    assert "P2" not in ctx.cache_values
    assert ctx.variables["P3"] == ""


def test_find_program_updates_notfound_normal_variable() -> None:
    """A result is cached and also replaces a NOTFOUND normal variable (CMP0125)."""
    ctx = _run(
        [
            Command(name="set", args=["PY", "PY-NOTFOUND"], line=1),
            Command(name="find_program", args=["PY", "python3", "python"], line=2),
        ]
    )
    assert "NOTFOUND" not in ctx.variables["PY"]
    assert ctx.cache_values["PY"] == ctx.variables["PY"]


def test_find_program_no_cache() -> None:
    """NO_CACHE stores the result as a normal variable only."""
    ctx = _run(
        [Command(name="find_program", args=["PY", "python3", "python", "NO_CACHE"], line=1)]
    )
    assert "NOTFOUND" not in ctx.variables["PY"]
    assert "PY" not in ctx.cache_values


def test_find_program_paths_are_not_names() -> None:
    """The values of PATHS and HINTS aren't program names."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="find_program",
            args=["PROG", "nonexistent_xyz_123", "PATHS", "python3", "HINTS", "sh"],
            line=1,
        )
    ]
    process_commands(commands, ctx)
    assert ctx.variables["PROG"] == "PROG-NOTFOUND"


EXE = ".exe" if os.name == "nt" else ""


def make_program(directory: Path, name: str = "tool") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    program = directory / f"{name}{EXE}"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    return program


def find(tmp_path: Path, *args: str, strict: bool = True, **variables: str) -> str:
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    ctx.variables.update(variables)
    process_commands([Command(name="find_program", args=["PROG", *args], line=1)], ctx, strict=strict)
    return ctx.variables["PROG"]


def test_find_program_hints_and_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """HINTS come before PATH, PATHS after everything else."""
    monkeypatch.setenv("PATH", str(tmp_path / "env"))
    hint = make_program(tmp_path / "hint")
    env = make_program(tmp_path / "env")
    path = make_program(tmp_path / "path")
    assert find(tmp_path, "tool", "HINTS", str(hint.parent)) == hint.as_posix()
    assert find(tmp_path, "tool", "PATHS", str(path.parent)) == env.as_posix()
    assert find(tmp_path, "tool", "PATHS", str(path.parent), "NO_SYSTEM_ENVIRONMENT_PATH") == (
        path.as_posix()
    )
    assert find(tmp_path, "tool", "NO_DEFAULT_PATH") == "PROG-NOTFOUND"
    assert find(tmp_path, "tool", str(path.parent), "NO_DEFAULT_PATH") == path.as_posix()
    monkeypatch.setenv("PROG_DIR", str(hint.parent))
    assert find(tmp_path, "tool", "HINTS", "ENV", "PROG_DIR") == hint.as_posix()


def test_find_program_path_suffixes(tmp_path: Path) -> None:
    """Each directory is tried with the suffixes first."""
    in_dir = make_program(tmp_path / "dir")
    in_suffix = make_program(tmp_path / "dir" / "sub")
    args = ["tool", "PATHS", str(in_dir.parent), "NO_DEFAULT_PATH"]
    assert find(tmp_path, *args) == in_dir.as_posix()
    assert find(tmp_path, *args, "PATH_SUFFIXES", "sub") == in_suffix.as_posix()


def test_find_program_names_per_dir(tmp_path: Path) -> None:
    second_name = make_program(tmp_path / "first", "second")
    first_name = make_program(tmp_path / "second", "first")
    args = ["NAMES", "first", "second", "PATHS", str(second_name.parent), str(first_name.parent)]
    assert find(tmp_path, *args, "NO_DEFAULT_PATH") == first_name.as_posix()
    assert find(tmp_path, *args, "NO_DEFAULT_PATH", "NAMES_PER_DIR") == second_name.as_posix()


def test_find_program_cmake_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """<prefix>/bin of CMAKE_PREFIX_PATH and CMAKE_PROGRAM_PATH come before PATH."""
    monkeypatch.setenv("PATH", str(tmp_path / "env"))
    monkeypatch.delenv("CMAKE_PREFIX_PATH", raising=False)
    monkeypatch.delenv("CMAKE_PROGRAM_PATH", raising=False)
    make_program(tmp_path / "env")
    in_prefix = make_program(tmp_path / "prefix" / "bin")
    in_program_path = make_program(tmp_path / "programs")
    prefix = str(tmp_path / "prefix")
    assert find(tmp_path, "tool", CMAKE_PREFIX_PATH=prefix) == in_prefix.as_posix()
    assert find(tmp_path, "tool", CMAKE_PROGRAM_PATH=str(in_program_path.parent)) == (
        in_program_path.as_posix()
    )
    assert find(tmp_path, "tool", "NO_CMAKE_PATH", CMAKE_PREFIX_PATH=prefix) != (
        in_prefix.as_posix()
    )
    monkeypatch.setenv("CMAKE_PREFIX_PATH", prefix)
    assert find(tmp_path, "tool") == in_prefix.as_posix()
    assert find(tmp_path, "tool", "NO_CMAKE_ENVIRONMENT_PATH") != in_prefix.as_posix()


def test_find_program_validator(tmp_path: Path) -> None:
    from cja.parser import parse

    rejected = make_program(tmp_path / "rejected")
    accepted = make_program(tmp_path / "accepted")
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    source = f"""\
function(check result candidate)
  list(APPEND candidates "${{candidate}}")
  set(candidates "${{candidates}}" PARENT_SCOPE)
  if(candidate MATCHES "rejected")
    set(${{result}} FALSE PARENT_SCOPE)
  endif()
endfunction()
find_program(PROG tool VALIDATOR check NO_DEFAULT_PATH
             PATHS "{rejected.parent.as_posix()}" "{accepted.parent.as_posix()}")
"""
    process_commands(parse(source), ctx, strict=True)
    assert ctx.variables["PROG"] == accepted.as_posix()
    assert ctx.variables["candidates"] == f"{rejected.as_posix()};{accepted.as_posix()}"


def test_find_program_supported_args_in_strict_mode() -> None:
    """Empty HINTS and arguments without effect are fine in strict mode."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="find_program",
            args=["PROG", "NAMES", "sh", "HINTS", "DOC", "Shell", "NAMES_PER_DIR"],
            line=1,
        )
    ]
    process_commands(commands, ctx, strict=True)
    assert "NOTFOUND" not in ctx.variables["PROG"]
