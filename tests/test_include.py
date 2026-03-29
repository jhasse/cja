"""Tests for include command."""

from pathlib import Path

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


def test_include_unknown_module() -> None:
    """Test include with unknown module (should be ignored)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="include", args=["UnknownModule"], line=1)]
    process_commands(commands, ctx)

    # Should not crash, just ignore
    assert "BUILD_TESTING" not in ctx.variables


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
