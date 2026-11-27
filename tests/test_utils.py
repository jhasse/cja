"""Tests for utility helpers."""

import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from cja.utils import (
    archive_filename_from_url,
    extract_archive,
    ipo_flag,
    make_relative,
    status_marker,
    strip_generator_expressions,
)


def test_archive_filename_from_url_sourceforge_download() -> None:
    """SourceForge …/archive.tar.xz/download URLs still yield the archive name."""
    url = (
        "https://sourceforge.net/projects/freetype/files/freetype2/2.14.1/"
        "freetype-2.14.1.tar.xz/download"
    )
    assert archive_filename_from_url(url) == "freetype-2.14.1.tar.xz"


def test_archive_filename_from_url_plain() -> None:
    """Normal archive URLs use the final path segment."""
    assert (
        archive_filename_from_url("https://example.com/releases/lib-1.0.tar.gz")
        == "lib-1.0.tar.gz"
    )
    assert archive_filename_from_url("https://example.com/pkg.zip") == "pkg.zip"


def test_archive_filename_from_url_unknown() -> None:
    """URLs without a known archive suffix return None."""
    assert archive_filename_from_url("https://example.com/download") is None


def test_extract_archive_tar_xz(tmp_path: Path) -> None:
    """extract_archive unpacks tar.xz by filename."""
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "hello.txt").write_text("hi\n")
    archive = tmp_path / "payload.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(payload / "hello.txt", arcname="hello.txt")

    dest = tmp_path / "out"
    dest.mkdir()
    extract_archive(archive, dest)
    assert (dest / "hello.txt").read_text() == "hi\n"


def test_extract_archive_content_probe(tmp_path: Path) -> None:
    """extract_archive probes contents when the filename has no archive suffix."""
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "hello.txt").write_text("hi\n")
    archive = tmp_path / "download"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(payload / "hello.txt", arcname="hello.txt")

    dest = tmp_path / "out"
    dest.mkdir()
    extract_archive(archive, dest)
    assert (dest / "hello.txt").read_text() == "hi\n"


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


def test_strip_generator_expressions_link_library() -> None:
    """$<LINK_LIBRARY:feature,...> links each library the way the feature says."""
    assert (
        strip_generator_expressions("$<LINK_LIBRARY:FRAMEWORK,Cocoa,IOKit;Metal>")
        == "-framework Cocoa;-framework IOKit;-framework Metal"
    )
    assert (
        strip_generator_expressions("$<LINK_LIBRARY:WEAK_FRAMEWORK,CoreHaptics>")
        == "-Wl,-weak_framework,CoreHaptics"
    )
    assert strip_generator_expressions("$<LINK_LIBRARY:DEFAULT,m,dl>") == "m;dl"


def test_strip_generator_expressions_target_objects() -> None:
    """$<TARGET_OBJECTS:tgt> is what it's told that target's objects are,
    and nothing if it isn't told."""
    value = "main.c;$<TARGET_OBJECTS:objs>"
    assert strip_generator_expressions(value) == "main.c;"
    assert (
        strip_generator_expressions(value, target_objects=lambda target: f"{target}.o")
        == "main.c;objs.o"
    )


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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("$<JOIN:a;b;c,+>", "a+b+c"),
        ("-I$<JOIN:inc;other, -I>", "-Iinc -Iother"),
        # The glue is everything after the first comma
        ("$<JOIN:a;b,,>", "a,b"),
        ("$<JOIN:a;b,$<COMMA>>", "a,b"),
        ("$<JOIN:a;b,>", "ab"),
        # Like in any list, empty elements are dropped
        ("$<JOIN:a;;c,->", "a-c"),
        ("$<JOIN:,->", ""),
        ("$<JOIN:$<TARGET_PROPERTY:tgt,FILES>,$<SEMICOLON>>", "a.md;b.md"),
    ],
)
def test_strip_generator_expressions_join(value: str, expected: str) -> None:
    def target_property(target: str, prop: str) -> str | None:
        return {("tgt", "FILES"): "a.md;b.md"}.get((target, prop))

    assert (
        strip_generator_expressions(value, target_property=target_property) == expected
    )


def test_status_marker_unicode_encoding() -> None:
    """Unicode-capable terminals should keep check/cross markers."""
    assert status_marker(True) == "✓"
    assert status_marker(False) == "✗"


def test_status_marker_cp1252_fallback(monkeypatch) -> None:
    """cp1252 terminals should get ASCII-safe fallback markers."""
    monkeypatch.setattr("cja.utils.sys.stdout", SimpleNamespace(encoding="cp1252"))
    assert status_marker(True) == "+"
    assert status_marker(False) == "x"


@pytest.mark.parametrize(
    "compiler_id, expected",
    [
        ("GNU", "-flto=auto"),
        ("Clang", "-flto=thin"),
        ("AppleClang", "-flto=thin"),
    ],
)
def test_ipo_flag(compiler_id: str, expected: str) -> None:
    """Clang and AppleClang use ThinLTO, GCC -flto=auto."""
    variables = {
        "CMAKE_C_COMPILER_ID": compiler_id,
        "CMAKE_CXX_COMPILER_ID": compiler_id,
    }
    assert ipo_flag(variables) == expected
