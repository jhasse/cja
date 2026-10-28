"""Tests for include command."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, configure, process_commands
from cja.parser import Command


def test_include_ctest() -> None:
    """Test include(CTest) sets BUILD_TESTING to ON."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="include", args=["CTest"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["BUILD_TESTING"] == "ON"


def test_include_ctest_respects_existing() -> None:
    """Test include(CTest) does not override existing BUILD_TESTING."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["BUILD_TESTING"] = "OFF"
    commands = [Command(name="include", args=["CTest"], line=1)]
    process_commands(commands, ctx)

    assert ctx.variables["BUILD_TESTING"] == "OFF"


def test_include_unknown_module(capsys: pytest.CaptureFixture[str]) -> None:
    """Test include with unknown module (should be ignored with a warning)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="include", args=["UnknownModule"], line=1)]
    process_commands(commands, ctx)

    # Should not crash, just warn and ignore
    assert "BUILD_TESTING" not in ctx.variables
    assert "unknown module: UnknownModule" in capsys.readouterr().err


def test_include_missing_file_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test that include() of a missing file warns without --strict."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [Command(name="include", args=["nope/path.cmake"], line=1)]
    process_commands(commands, ctx)

    err = capsys.readouterr().err
    assert "include() could not find file: nope/path.cmake" in err


def test_include_missing_optional_is_silent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test that include(... OPTIONAL) of a missing file or module is silent."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="include", args=["nope/path.cmake", "OPTIONAL"], line=1),
        Command(name="include", args=["UnknownModule", "OPTIONAL"], line=2),
    ]
    process_commands(commands, ctx)

    assert capsys.readouterr().err == ""


def test_include_txt_file(tmp_path: Path) -> None:
    """Test that include() works with .txt files, not just .cmake."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "Options.txt").write_text(
        'option(MY_OPTION "Enable my option" ON)\n'
    )
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_include_txt)\n"
        "include(Options.txt)\n"
        "if(MY_OPTION)\n"
        "  add_executable(main main.c)\n"
        "endif()\n"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    assert ninja_file.exists()
    content = ninja_file.read_text()
    assert "main" in content
