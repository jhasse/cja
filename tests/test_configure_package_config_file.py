"""Tests for configure_package_config_file command."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_configure_package_config_file_basic(tmp_path: Path) -> None:
    """configure_package_config_file should expand @PACKAGE_INIT@ and PATH_VARS."""
    source_dir = tmp_path / "src"
    build_dir = tmp_path / "build"
    source_dir.mkdir()
    build_dir.mkdir()

    template = source_dir / "Config.cmake.in"
    template.write_text(
        "@PACKAGE_INIT@\n"
        'set(pkg_name "@PROJECT_NAME@")\n'
        'set(pkg_inc "@PACKAGE_CMAKE_INSTALL_INCLUDEDIR@")\n'
    )

    ctx = BuildContext(source_dir=source_dir, build_dir=build_dir)
    ctx.variables["PROJECT_NAME"] = "gtest"
    ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(build_dir)
    ctx.variables["CMAKE_INSTALL_INCLUDEDIR"] = "include"

    commands = [
        Command(
            name="configure_package_config_file",
            args=[
                "Config.cmake.in",
                "gtestConfig.cmake",
                "INSTALL_DESTINATION",
                "lib/cmake/GTest",
                "PATH_VARS",
                "CMAKE_INSTALL_INCLUDEDIR",
            ],
            line=1,
        )
    ]
    process_commands(commands, ctx, strict=True)

    out_file = build_dir / "gtestConfig.cmake"
    assert out_file.exists()
    content = out_file.read_text()
    assert "PACKAGE_PREFIX_DIR" in content
    assert "set(pkg_name \"gtest\")" in content
    assert "set(pkg_inc \"include\")" in content
    assert "@PACKAGE_INIT@" not in content


def test_configure_package_config_file_requires_install_destination_strict(
    tmp_path: Path,
) -> None:
    """Missing INSTALL_DESTINATION should fail in strict mode."""
    source_dir = tmp_path / "src"
    build_dir = tmp_path / "build"
    source_dir.mkdir()
    build_dir.mkdir()

    (source_dir / "Config.cmake.in").write_text("@PACKAGE_INIT@\n")
    ctx = BuildContext(source_dir=source_dir, build_dir=build_dir)
    ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(build_dir)

    commands = [
        Command(
            name="configure_package_config_file",
            args=["Config.cmake.in", "gtestConfig.cmake"],
            line=1,
        )
    ]

    with pytest.raises(SystemExit):
        process_commands(commands, ctx, strict=True)


def test_configure_package_config_file_undefined_vars_warn_in_strict(
    tmp_path: Path,
    capsys,
) -> None:
    """Undefined vars in package config template should warn, not fail, in strict mode."""
    source_dir = tmp_path / "src"
    build_dir = tmp_path / "build"
    source_dir.mkdir()
    build_dir.mkdir()

    (source_dir / "Config.cmake.in").write_text(
        "@PACKAGE_INIT@\n"
        'set(missing "@DOES_NOT_EXIST@")\n'
    )
    ctx = BuildContext(source_dir=source_dir, build_dir=build_dir)
    ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(build_dir)

    commands = [
        Command(
            name="configure_package_config_file",
            args=[
                "Config.cmake.in",
                "gtestConfig.cmake",
                "INSTALL_DESTINATION",
                "lib/cmake/GTest",
            ],
            line=1,
        )
    ]

    process_commands(commands, ctx, strict=True)

    out = (build_dir / "gtestConfig.cmake").read_text()
    assert 'set(missing "")' in out
    captured = capsys.readouterr()
    assert "warning:" in captured.err
    assert "undefined variable referenced: DOES_NOT_EXIST" in captured.err
