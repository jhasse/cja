"""Tests for FindPackageHandleStandardArgs."""

from pathlib import Path
import pytest

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


def test_find_package_handle_standard_args_basic() -> None:
    """Test find_package_handle_standard_args basic signature."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MYPACK_LIBRARY"] = "/path/to/lib"
    ctx.variables["MYPACK_INCLUDE_DIR"] = "/path/to/include"

    commands = [
        Command(
            name="find_package_handle_standard_args",
            args=["MYPACK", "DEFAULT_MSG", "MYPACK_LIBRARY", "MYPACK_INCLUDE_DIR"],
            line=1,
        ),
    ]

    process_commands(commands, ctx)
    assert ctx.variables["MYPACK_FOUND"] == "TRUE"


def test_find_package_handle_standard_args_not_found() -> None:
    """Test find_package_handle_standard_args when a variable is missing."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MYPACK_LIBRARY"] = "MYPACK_LIBRARY-NOTFOUND"

    commands = [
        Command(
            name="find_package_handle_standard_args",
            args=["MYPACK", "DEFAULT_MSG", "MYPACK_LIBRARY"],
            line=1,
        ),
    ]

    process_commands(commands, ctx)
    assert ctx.variables["MYPACK_FOUND"] == "FALSE"


def test_find_package_handle_standard_args_extended() -> None:
    """Test find_package_handle_standard_args extended signature."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MYPACK_LIBRARY"] = "/path/to/lib"

    commands = [
        Command(
            name="find_package_handle_standard_args",
            args=[
                "MYPACK",
                "REQUIRED_VARS",
                "MYPACK_LIBRARY",
                "FOUND_VAR",
                "MYPACK_WAS_FOUND",
            ],
            line=1,
        ),
    ]

    process_commands(commands, ctx)
    assert ctx.variables["MYPACK_WAS_FOUND"] == "TRUE"


def test_find_package_handle_standard_args_required_fails() -> None:
    """Test find_package_handle_standard_args with REQUIRED fails when missing."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MYPACK_FIND_REQUIRED"] = "TRUE"
    ctx.variables["MYPACK_LIBRARY"] = "MYPACK_LIBRARY-NOTFOUND"

    commands = [
        Command(
            name="find_package_handle_standard_args",
            args=["MYPACK", "DEFAULT_MSG", "MYPACK_LIBRARY"],
            line=1,
        ),
    ]

    with pytest.raises(SystemExit):
        process_commands(commands, ctx)


def test_include_find_package_handle_standard_args() -> None:
    """Test including FindPackageHandleStandardArgs module."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="include", args=["FindPackageHandleStandardArgs"], line=1),
    ]
    # Should not fail
    process_commands(commands, ctx)
