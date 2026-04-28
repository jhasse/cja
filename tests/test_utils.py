"""Tests for utility helpers."""

from pathlib import Path
from types import SimpleNamespace

from cja.utils import make_relative
from cja.utils import status_marker
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


def test_strip_generator_expressions_compiler_version_condition() -> None:
    """Compiler-id/version genex should resolve with provided CMake variables."""
    value = "$<$<AND:$<CXX_COMPILER_ID:GNU>,$<VERSION_LESS:$<CXX_COMPILER_VERSION>,9.0>>:stdc++fs>"
    variables = {
        "CMAKE_CXX_COMPILER_ID": "GNU",
        "CMAKE_CXX_COMPILER_VERSION": "8.4.0",
    }
    assert strip_generator_expressions(value, variables) == "stdc++fs"


def test_strip_generator_expressions_target_file() -> None:
    """$<TARGET_FILE:name> should resolve to the target's output file path."""
    target_files = {"myapp": "$builddir/myapp", "mylib": "$builddir/libmylib.a"}
    assert (
        strip_generator_expressions(
            "$<TARGET_FILE:myapp>", target_files=target_files
        )
        == "$builddir/myapp"
    )
    assert (
        strip_generator_expressions(
            "$<TARGET_FILE:mylib>", target_files=target_files
        )
        == "$builddir/libmylib.a"
    )
    assert strip_generator_expressions("$<TARGET_FILE:unknown>") == ""


def test_strip_generator_expressions_multiline_content() -> None:
    """Newlines inside genex results should be normalized to spaces."""
    value = (
        "$<$<OR:$<C_COMPILER_ID:Clang>,$<C_COMPILER_ID:GNU>>:\n"
        "    -Wextra -Wshadow\n"
        "    -Wdisabled-optimization -Waggregate-return>"
    )
    variables = {"CMAKE_C_COMPILER_ID": "GNU"}
    result = strip_generator_expressions(value, variables)
    assert "\n" not in result
    assert "-Wextra" in result
    assert "-Wshadow" in result
    assert "-Wdisabled-optimization" in result
    assert "-Waggregate-return" in result


def test_status_marker_unicode_encoding() -> None:
    """Unicode-capable terminals should keep check/cross markers."""
    assert status_marker(True) == "✓"
    assert status_marker(False) == "✗"


def test_status_marker_cp1252_fallback(monkeypatch) -> None:
    """cp1252 terminals should get ASCII-safe fallback markers."""
    monkeypatch.setattr("cja.utils.sys.stdout", SimpleNamespace(encoding="cp1252"))
    assert status_marker(True) == "+"
    assert status_marker(False) == "x"
