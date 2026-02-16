"""Tests for get_directory_property command."""

from pathlib import Path

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_get_directory_property_parent_root(tmp_path: Path) -> None:
    """Test get_directory_property(PARENT_DIRECTORY) in root directory."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(
            name="get_directory_property",
            args=["hasParent", "PARENT_DIRECTORY"],
            line=1,
        ),
    ]
    process_commands(commands, ctx)
    # In root directory, PARENT_DIRECTORY should be empty
    assert ctx.variables["hasParent"] == ""


def test_get_directory_property_parent_sub(tmp_path: Path) -> None:
    """Test get_directory_property(PARENT_DIRECTORY) in subdirectory."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    sub_dir = tmp_path / "sub"
    sub_dir.mkdir()
    (sub_dir / "CMakeLists.txt").write_text(
        "get_directory_property(hasParent PARENT_DIRECTORY)"
    )

    commands = [
        Command(name="add_subdirectory", args=["sub"], line=1),
    ]
    process_commands(commands, ctx)

    # We can't easily check ctx.variables here because it's restored after add_subdirectory.
    # Let's use a message or set a variable in parent scope to verify.

    (sub_dir / "CMakeLists.txt").write_text("""
get_directory_property(hasParent PARENT_DIRECTORY)
set(SUB_PARENT "${hasParent}" PARENT_SCOPE)
""")

    process_commands(commands, ctx)
    assert ctx.variables["SUB_PARENT"] == str(tmp_path)
