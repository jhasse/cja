"""Tests for generate_export_header."""

from pathlib import Path

from cja.configurator import process_commands
from cja.generator import BuildContext
from cja.parser import Command
from cja.targets import Library


def test_generate_export_header_shared_linux(tmp_path: Path) -> None:
    """Shared libraries get visibility attributes in the export header."""
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    ctx = BuildContext(source_dir=tmp_path, build_dir=build_dir)
    ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(build_dir)
    ctx.variables["WIN32"] = "FALSE"
    ctx.libraries.append(
        Library(name="mylib", sources=["a.c"], lib_type="SHARED", binary_dir=str(build_dir))
    )

    process_commands(
        [
            Command(
                name="generate_export_header",
                args=["mylib"],
                line=1,
            ),
        ],
        ctx,
    )

    header = build_dir / "mylib_export.h"
    assert header.is_file()
    text = header.read_text()
    assert "#ifndef MYLIB_EXPORT_H" in text
    assert "mylib_EXPORTS" in text
    assert '__attribute__((visibility("default")))' in text
    assert '__attribute__((visibility("hidden")))' in text
    assert "__attribute__ ((__deprecated__))" in text


def test_generate_export_header_static_empty_macros(tmp_path: Path) -> None:
    """Static libraries get empty export macros."""
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    ctx = BuildContext(source_dir=tmp_path, build_dir=build_dir)
    ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(build_dir)
    ctx.variables["WIN32"] = "FALSE"
    ctx.libraries.append(
        Library(name="mylib", sources=["a.c"], lib_type="STATIC", binary_dir=str(build_dir))
    )

    process_commands(
        [
            Command(
                name="generate_export_header",
                args=["mylib"],
                line=1,
            ),
        ],
        ctx,
    )

    text = (build_dir / "mylib_export.h").read_text()
    # Inside the static-define branch macros are empty; outside that branch
    # DEFINE_EXPORT/IMPORT stay empty for STATIC libraries.
    assert "visibility" not in text
    assert "dllexport" not in text


def test_generate_export_header_base_name_and_custom_file(tmp_path: Path) -> None:
    """BASE_NAME and EXPORT_FILE_NAME customize output."""
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    ctx = BuildContext(source_dir=tmp_path, build_dir=build_dir)
    ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(build_dir)
    ctx.variables["WIN32"] = "FALSE"
    ctx.libraries.append(
        Library(name="example", sources=["a.c"], lib_type="SHARED", binary_dir=str(build_dir))
    )

    process_commands(
        [
            Command(
                name="generate_export_header",
                args=[
                    "example",
                    "BASE_NAME",
                    "other_name",
                    "EXPORT_FILE_NAME",
                    "custom_export.h",
                ],
                line=1,
            ),
        ],
        ctx,
    )

    header = build_dir / "custom_export.h"
    assert header.is_file()
    text = header.read_text()
    assert "OTHER_NAME_EXPORT" in text
    assert "example_EXPORTS" in text


def test_include_generate_export_header_is_known(tmp_path: Path) -> None:
    """include(GenerateExportHeader) should not error as an unknown module."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    process_commands(
        [
            Command(name="include", args=["GenerateExportHeader"], line=1),
        ],
        ctx,
        strict=True,
    )
