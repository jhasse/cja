"""Tests for the commands of the FeatureSummary module.

The expected summaries are the output of CMake 4.3 for the same projects.
"""

from pathlib import Path

import pytest

from cja.generator import BuildContext, configure


def _configure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str, capsys
) -> BuildContext:
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(summary NONE)\n"
        "include(FeatureSummary)\n" + body
    )
    monkeypatch.chdir(tmp_path)
    # Not quiet=True, which would make find_dependency() QUIET.
    ctx = configure(tmp_path, "build", strict=True)
    assert "warning" not in capsys.readouterr().err
    return ctx


def test_feature_summary_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    (tmp_path / "cmake").mkdir()
    (tmp_path / "cmake" / "FindLocalThing.cmake").write_text(
        "set(LocalThing_FOUND TRUE)\n"
    )
    ctx = _configure(
        tmp_path,
        monkeypatch,
        "list(APPEND CMAKE_MODULE_PATH ${CMAKE_SOURCE_DIR}/cmake)\n"
        "find_package(LocalThing 1.2 EXACT)\n"
        "find_package(NotAThing 2.0 QUIET)\n"
        "find_package(AlsoMissing 1.0...2.0 MODULE)\n"
        "set_package_properties(LocalThing PROPERTIES URL https://example.com\n"
        '  DESCRIPTION "A local thing" PURPOSE "Makes things local" TYPE RECOMMENDED)\n'
        "set_package_properties(AlsoMissing PROPERTIES TYPE REQUIRED PURPOSE Needed)\n"
        "set(WITH_X ON)\n"
        "set(WITH_Y OFF)\n"
        'add_feature_info(X WITH_X "the X feature")\n'
        'add_feature_info(Y "WITH_X;WITH_Y" "the Y feature")\n'
        'add_feature_info(Z "WITH_Y OR WITH_X" "the Z feature")\n'
        "feature_summary(WHAT ALL VAR all)\n"
        "feature_summary(WHAT PACKAGES_NOT_FOUND INCLUDE_QUIET_PACKAGES\n"
        "  DEFAULT_DESCRIPTION VAR not_found)\n",
        capsys,
    )

    assert ctx.variables["all"] == (
        "The following features have been enabled:\n"
        "\n"
        " * X, the X feature\n"
        " * Z, the Z feature\n"
        "\n"
        "-- The following RECOMMENDED packages have been found:\n"
        "\n"
        " * LocalThing (required version == 1.2), A local thing, <https://example.com>\n"
        "   Makes things local\n"
        "\n"
        "-- The following features have been disabled:\n"
        "\n"
        " * Y, the Y feature\n"
        "\n"
        "-- The following REQUIRED packages have not been found:\n"
        "\n"
        " * AlsoMissing (required version 1.0...2.0)\n"
        "   Needed\n"
    )
    assert ctx.variables["not_found"] == (
        "The following packages have not been found:\n"
        "\n"
        " * NotAThing (required version >= 2.0)\n"
        " * AlsoMissing (required version 1.0...2.0)\n"
        "   Needed\n"
    )


def test_feature_summary_hides_transitive_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    prefix = tmp_path / "prefix" / "lib" / "cmake"
    for name in ("CjaDep", "CjaOwnDep"):
        (prefix / name).mkdir(parents=True)
        (prefix / name / f"{name}Config.cmake").write_text("")
    (prefix / "CjaPkg").mkdir()
    (prefix / "CjaPkg" / "CjaPkgConfig.cmake").write_text(
        "include(CMakeFindDependencyMacro)\n"
        "find_dependency(CjaDep)\n"
        "find_dependency(CjaOwnDep)\n"
    )
    ctx = _configure(
        tmp_path,
        monkeypatch,
        f"set(CMAKE_PREFIX_PATH {(tmp_path / 'prefix').as_posix()})\n"
        "find_package(CjaOwnDep CONFIG)\n"
        "find_package(CjaPkg CONFIG)\n"
        "feature_summary(WHAT PACKAGES_FOUND VAR found)\n",
        capsys,
    )

    assert ctx.variables["found"] == "\n * CjaOwnDep\n * CjaPkg\n"
    assert ctx.global_properties["PACKAGES_FOUND"] == "CjaDep;CjaOwnDep;CjaPkg"


def test_feature_summary_writes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _configure(
        tmp_path,
        monkeypatch,
        'add_feature_info(X ON "the X feature")\n'
        "feature_summary(WHAT ENABLED_FEATURES DESCRIPTION Enabled:\n"
        "  FILENAME ${CMAKE_BINARY_DIR}/summary.txt)\n",
        capsys,
    )

    assert (tmp_path / "build" / "summary.txt").read_text() == (
        "Enabled:\n * X, the X feature\n"
    )


def test_feature_summary_fatal_on_missing_required_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(summary NONE)\n"
        "include(FeatureSummary)\n"
        "find_package(NotAThing QUIET)\n"
        "set_package_properties(NotAThing PROPERTIES TYPE REQUIRED)\n"
        "feature_summary(WHAT ALL FATAL_ON_MISSING_REQUIRED_PACKAGES)\n"
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        configure(tmp_path, "build", strict=True, quiet=True)

    assert "REQUIRED package(s) are missing" in capsys.readouterr().err


def test_set_package_properties_type_is_not_lowered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    ctx = _configure(
        tmp_path,
        monkeypatch,
        "set_package_properties(Pkg PROPERTIES TYPE REQUIRED)\n"
        "set_package_properties(Pkg PROPERTIES TYPE OPTIONAL PURPOSE a)\n"
        "set_package_properties(Pkg PROPERTIES PURPOSE b)\n",
        capsys,
    )

    assert ctx.global_properties["_CMAKE_Pkg_TYPE"] == "REQUIRED"
    assert ctx.global_properties["_CMAKE_Pkg_PURPOSE"] == "a;b"


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (
            "set_package_properties(Pkg PROPERTIES TYPE BAD)\n",
            "Bad package property type BAD used in SET_PACKAGE_PROPERTIES(). "
            "Valid types are RUNTIME, OPTIONAL, RECOMMENDED and REQUIRED.",
        ),
        (
            "feature_summary(WHAT ENABLED_FEATURES BAD)\n",
            "The WHAT argument of FEATURE_SUMMARY() contains BAD, "
            "which is not a valid value.",
        ),
        ("feature_summary(VAR v)\n", "doesn't set the required WHAT argument"),
    ],
)
def test_feature_summary_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, body: str, error: str
) -> None:
    with pytest.raises(SystemExit):
        _configure(tmp_path, monkeypatch, body, capsys)

    assert error in capsys.readouterr().err


def test_feature_summary_quiet_on_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    ctx = _configure(
        tmp_path,
        monkeypatch,
        "set(v before)\n"
        "feature_summary(WHAT DISABLED_FEATURES QUIET_ON_EMPTY VAR v)\n"
        "feature_summary(WHAT DISABLED_FEATURES VAR w)\n",
        capsys,
    )

    assert ctx.variables["v"] == "before"
    assert ctx.variables["w"] == "\n"


def test_deprecated_feature_summary_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(summary NONE)\n"
        "include(FeatureSummary)\n"
        "set_package_info(Pkg desc https://example.com purpose)\n"
        "add_feature_info(X ON x)\n"
        "print_enabled_features()\n"
    )
    monkeypatch.chdir(tmp_path)
    ctx = configure(tmp_path, "build")
    captured = capsys.readouterr()

    assert ctx.global_properties["_CMAKE_Pkg_URL"] == "https://example.com"
    assert ctx.global_properties["_CMAKE_Pkg_PURPOSE"] == "purpose"
    assert "SET_PACKAGE_INFO is deprecated" in captured.err
    assert "PRINT_ENABLED_FEATURES is deprecated" in captured.err
    assert "Enabled features:\n * X, x\n" in captured.out
