"""Tests for config-mode find_package() (<Pkg>Config.cmake lookup)."""

from pathlib import Path

import pytest

from cja.generator import configure


def _config(prefix: Path, subdir: str, filename: str, content: str) -> Path:
    path = prefix / subdir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _configure(tmp_path: Path, body: str, prefix: Path) -> tuple[Path, dict[str, str]]:
    source = tmp_path / "src"
    source.mkdir()
    (source / "main.cpp").write_text("int main() { return 0; }\n")
    (source / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.20)\nproject(cfg CXX)\n" + body
    )
    ctx = configure(
        source,
        "build",
        variables={"CMAKE_PREFIX_PATH": prefix.as_posix()},
        quiet=True,
    )
    return source, dict(ctx.variables)


TARGETS_CONFIG = """\
add_library(CjaPkg::lib STATIC IMPORTED)
set_target_properties(CjaPkg::lib PROPERTIES
  INTERFACE_COMPILE_FEATURES cxx_std_17
  INTERFACE_INCLUDE_DIRECTORIES "${CMAKE_CURRENT_LIST_DIR}/include")
set_target_properties(CjaPkg::lib PROPERTIES
  IMPORTED_LOCATION_RELEASE "${CMAKE_CURRENT_LIST_DIR}/libcjapkg.a")
"""


@pytest.mark.parametrize("keyword", ["CONFIG", "NO_MODULE", ""])
def test_config_file_found_via_prefix_path(tmp_path: Path, keyword: str) -> None:
    """Without a Find module, find_package() falls back to config mode."""
    prefix = tmp_path / "prefix"
    config = _config(prefix, "lib/cmake/CjaPkg", "CjaPkgConfig.cmake", TARGETS_CONFIG)

    source, variables = _configure(
        tmp_path,
        f"find_package(CjaPkg {keyword} REQUIRED)\n"
        "add_executable(app main.cpp)\n"
        "target_link_libraries(app PRIVATE CjaPkg::lib)\n",
        prefix,
    )

    assert variables["CjaPkg_FOUND"] == "TRUE"
    assert variables["CjaPkg_DIR"] == config.parent.as_posix()
    ninja = (source / "build.ninja").read_text()
    assert "-std=c++17" in ninja
    assert f"{config.parent.as_posix()}/libcjapkg.a" in ninja


def test_lowercase_config_file_under_share(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    _config(prefix, "share/cjapkg", "cjapkg-config.cmake", "set(CJAPKG_MARKER yes)\n")

    _, variables = _configure(tmp_path, "find_package(CjaPkg CONFIG REQUIRED)\n", prefix)

    assert variables["CjaPkg_FOUND"] == "TRUE"
    assert variables["CJAPKG_MARKER"] == "yes"


@pytest.mark.parametrize(
    ("request_version", "found"),
    [("1.0", "TRUE"), ("1.2.3", "TRUE"), ("2.0", "FALSE"), ("1.0 EXACT", "FALSE")],
)
def test_config_version_file(tmp_path: Path, request_version: str, found: str) -> None:
    prefix = tmp_path / "prefix"
    _config(prefix, "lib/cmake/CjaPkg", "CjaPkgConfig.cmake", "")
    _config(
        prefix,
        "lib/cmake/CjaPkg",
        "CjaPkgConfigVersion.cmake",
        'set(PACKAGE_VERSION "1.2.3")\n',
    )

    _, variables = _configure(
        tmp_path, f"find_package(CjaPkg {request_version} CONFIG QUIET)\n", prefix
    )

    assert variables["CjaPkg_FOUND"] == found
    if found == "TRUE":
        assert variables["CjaPkg_VERSION"] == "1.2.3"


def test_config_file_can_reject_itself(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    _config(
        prefix, "lib/cmake/CjaPkg", "CjaPkgConfig.cmake", "set(CjaPkg_FOUND FALSE)\n"
    )

    _, variables = _configure(tmp_path, "find_package(CjaPkg CONFIG QUIET)\n", prefix)

    assert variables["CjaPkg_FOUND"] == "FALSE"


def test_find_dependency_missing_marks_package_not_found(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    _config(
        prefix,
        "lib/cmake/CjaPkg",
        "CjaPkgConfig.cmake",
        "include(CMakeFindDependencyMacro)\n"
        "find_dependency(CjaMissingDep)\n"
        "set(CJAPKG_AFTER_DEPENDENCY yes)\n",
    )

    _, variables = _configure(tmp_path, "find_package(CjaPkg CONFIG QUIET)\n", prefix)

    assert variables["CjaPkg_FOUND"] == "FALSE"
    assert "CJAPKG_AFTER_DEPENDENCY" not in variables


def test_find_dependency_found(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    _config(prefix, "lib/cmake/CjaDep", "CjaDepConfig.cmake", "")
    _config(
        prefix,
        "lib/cmake/CjaPkg",
        "CjaPkgConfig.cmake",
        "include(CMakeFindDependencyMacro)\nfind_dependency(CjaDep)\n",
    )

    _, variables = _configure(tmp_path, "find_package(CjaPkg CONFIG REQUIRED)\n", prefix)

    assert variables["CjaPkg_FOUND"] == "TRUE"
    assert variables["CjaDep_FOUND"] == "TRUE"


def test_missing_config_required_fails(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        _configure(
            tmp_path, "find_package(CjaPkg CONFIG REQUIRED)\n", tmp_path / "empty"
        )
