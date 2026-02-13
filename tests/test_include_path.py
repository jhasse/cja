"""Tests for including .cmake files."""

from pathlib import Path
from cja.generator import configure


def test_include_path(tmp_path: Path) -> None:
    """Test include() with a path to a .cmake file."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    (source_dir / "CMakeLists.txt").write_text(
        "include(extra.cmake)\nadd_executable(main main.c)"
    )
    (source_dir / "extra.cmake").write_text("set(EXTRA_VAR Success)")
    (source_dir / "main.c").write_text("int main() { return 0; }")

    ctx = configure(source_dir, "build")

    # EXTRA_VAR should be set in the current scope
    assert ctx.variables["EXTRA_VAR"] == "Success"


def test_include_path_nested(tmp_path: Path) -> None:
    """Test include() with a nested path."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    (source_dir / "cmake").mkdir()
    (source_dir / "CMakeLists.txt").write_text("include(cmake/vars.cmake)")
    (source_dir / "cmake/vars.cmake").write_text("set(NESTED_VAR Value)")

    ctx = configure(source_dir, "build")

    assert ctx.variables["NESTED_VAR"] == "Value"


def test_include_current_list_file(tmp_path: Path) -> None:
    """Test CMAKE_CURRENT_LIST_FILE inside an included file."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    inc_file = source_dir / "inc.cmake"
    inc_file.write_text("set(INC_FILE ${CMAKE_CURRENT_LIST_FILE})")

    (source_dir / "CMakeLists.txt").write_text("include(inc.cmake)")

    ctx = configure(source_dir, "build")

    assert ctx.variables["INC_FILE"] == str(inc_file.resolve())
