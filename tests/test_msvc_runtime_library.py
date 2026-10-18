"""Tests for selecting the MSVC runtime library (CMAKE_MSVC_RUNTIME_LIBRARY)."""

import re
from pathlib import Path

import pytest

from cja.generator import configure


def _cflags(ninja_content: str, obj_suffix: str) -> str:
    """The cflags of the build edge whose output ends with obj_suffix."""
    unwrapped = re.sub(r"\$\n *", "", ninja_content)
    match = re.search(
        rf"^build \S*{re.escape(obj_suffix)}: .*\n(?:  cflags = (.*))?",
        unwrapped,
        re.MULTILINE,
    )
    assert match, f"no build edge for {obj_suffix}"
    return match.group(1) or ""


def _configure(
    tmp_path: Path, extra_cmake: str = "", **variables: str
) -> tuple[str, str]:
    """Configure a static library and an executable, return their cflags."""
    (tmp_path / "CMakeLists.txt").write_text(
        "project(RuntimeLib C)\n"
        "add_library(mylib STATIC lib.c)\n"
        "add_executable(app main.c)\n"
        "target_link_libraries(app mylib)\n" + extra_cmake
    )
    (tmp_path / "lib.c").write_text("int f(void) { return 0; }\n")
    (tmp_path / "main.c").write_text("int f(void);\nint main(void) { return f(); }\n")
    configure(tmp_path, "build", variables=variables)
    content = (tmp_path / "build.ninja").read_text()
    return _cflags(content, "mylib_lib.o"), _cflags(content, "app_main.o")


@pytest.mark.parametrize(
    ("build_type", "runtime"), [("Debug", "dll_dbg"), ("Release", "dll")]
)
def test_default_is_multithreaded_dll(
    tmp_path: Path, build_type: str, runtime: str
) -> None:
    """Like CMake: MultiThreaded$<$<CONFIG:Debug>:Debug>DLL, so that _MT is defined."""
    lib_flags, app_flags = _configure(
        tmp_path, CMAKE_BUILD_TYPE=build_type, MSVC_VERSION="1930"
    )
    assert f"-fms-runtime-lib={runtime}" in lib_flags.split()
    assert f"-fms-runtime-lib={runtime}" in app_flags.split()


def test_cmake_msvc_runtime_library_variable(tmp_path: Path) -> None:
    lib_flags, app_flags = _configure(
        tmp_path,
        'set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")\n',
        CMAKE_BUILD_TYPE="Debug",
        MSVC_VERSION="1930",
    )
    assert "-fms-runtime-lib=static_dbg" in lib_flags.split()
    assert "-fms-runtime-lib=static_dbg" in app_flags.split()


def test_msvc_runtime_library_property_overrides_variable(tmp_path: Path) -> None:
    """The target property wins; an empty one selects no runtime library at all."""
    lib_flags, app_flags = _configure(
        tmp_path,
        "set(CMAKE_MSVC_RUNTIME_LIBRARY MultiThreaded)\n"
        "set_target_properties(mylib PROPERTIES MSVC_RUNTIME_LIBRARY MultiThreadedDLL)\n"
        'set_target_properties(app PROPERTIES MSVC_RUNTIME_LIBRARY "")\n',
        CMAKE_BUILD_TYPE="Release",
        MSVC_VERSION="1930",
    )
    assert "-fms-runtime-lib=dll" in lib_flags.split()
    assert "-fms-runtime-lib" not in app_flags


def test_no_runtime_library_flag_without_msvc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("cja.generator.platform.system", lambda: "Linux")
    (tmp_path / "CMakeLists.txt").write_text(
        "project(RuntimeLib C)\nadd_executable(app main.c)\n"
    )
    (tmp_path / "main.c").write_text("int main(void) { return 0; }\n")
    configure(tmp_path, "build")
    assert "-fms-runtime-lib" not in (tmp_path / "build.ninja").read_text()


def test_runtime_flag_is_passed_when_linking(tmp_path: Path) -> None:
    """The link must select the same runtime, else the driver links libcmt."""
    _configure(tmp_path, CMAKE_BUILD_TYPE="Debug", MSVC_VERSION="1930")
    content = re.sub(r"\$\n *", "", (tmp_path / "build.ninja").read_text())
    match = re.search(r"^build \S*app\S*: link\S* .*\n  libs = (.*)", content, re.M)
    assert match
    assert "-fms-runtime-lib=dll_dbg" in match.group(1).split()
