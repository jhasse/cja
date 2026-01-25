"""Tests for CMake comments."""

from pathlib import Path
from cninja.generator import configure
from cninja.parser import parse


def test_line_comment() -> None:
    content = "project(test) # This is a comment\nset(VAR val)"
    commands = parse(content)
    assert len(commands) == 2
    assert commands[1].name == "set"


def test_multiline_comment(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test)\n#[[ multi-line\n   comment ]]\nset(VAR value)\n"
    )

    ctx = configure(source_dir, "build")
    assert ctx.variables["VAR"] == "value"


def test_multiline_comment_with_equals(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test)\n"
        "#[==[ multi-line\n"
        "   comment with ] ] and ]=] ]==]\n"
        "set(VAR value)\n"
    )

    ctx = configure(source_dir, "build")
    assert ctx.variables["VAR"] == "value"


def test_unclosed_multiline_comment() -> None:
    # Just ensure it doesn't crash and skips to end
    content = "project(test)\n#[[ multi-line comment"
    commands = parse(content)
    assert len(commands) == 1
