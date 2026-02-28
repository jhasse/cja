"""Tests for utility helpers."""

from pathlib import Path

from cja.utils import make_relative
from cja.utils import strip_generator_expressions


def test_make_relative_with_relative_root(tmp_path: Path, monkeypatch) -> None:
    """make_relative should work when root is a relative path."""
    project = tmp_path / "project"
    project.mkdir()
    child = project / "sub" / "file.hpp"
    child.parent.mkdir(parents=True)
    child.write_text("x\n")

    monkeypatch.chdir(project)
    result = make_relative(str(child), Path("."))
    assert result == "sub/file.hpp"


def test_make_relative_outside_root_stays_absolute(tmp_path: Path) -> None:
    """Absolute paths outside root should not be relativized."""
    root = tmp_path / "root"
    other = tmp_path / "other"
    root.mkdir()
    other.mkdir()
    header = other / "x.hpp"
    header.write_text("x\n")

    result = make_relative(str(header), root)
    assert result == str(header)


def test_strip_generator_expressions_conditional_bool() -> None:
    """Nested conditional genex should evaluate to the true branch."""
    value = "$<$<NOT:$<BOOL:ON>>:YAML_CPP_NO_CONTRIB>"
    assert strip_generator_expressions(value) == ""


def test_strip_generator_expressions_strequal_and_bool() -> None:
    """STREQUAL and BOOL expressions should collapse to 1/0 values."""
    value = "JSON_USE_IMPLICIT_CONVERSIONS=$<BOOL:ON> JSON_DIAGNOSTICS=$<BOOL:OFF>"
    assert (
        strip_generator_expressions(value)
        == "JSON_USE_IMPLICIT_CONVERSIONS=1 JSON_DIAGNOSTICS=0"
    )
