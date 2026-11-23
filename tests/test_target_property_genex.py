"""Tests for $<TARGET_PROPERTY:prop>, which is about the target being built."""

import re
from pathlib import Path

from cja.generator import configure
from cja.utils import to_posix_path


def _cflags(ninja_content: str, obj_suffix: str) -> list[str]:
    """The cflags of the build edge whose output ends with obj_suffix."""
    unwrapped = re.sub(r"\$\n *", "", ninja_content)
    match = re.search(
        rf"^build \S*{re.escape(obj_suffix)}: .*\n(?:  cflags = (.*))?",
        unwrapped,
        re.MULTILINE,
    )
    assert match, f"no build edge for {obj_suffix}"
    return to_posix_path(match.group(1) or "").split()


def _configure(tmp_path: Path, cmake: str) -> str:
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(TargetPropertyTest C)\n"
        "add_library(mylib STATIC lib.c)\n"
        "add_executable(app main.c)\n"
        "target_link_libraries(app PRIVATE mylib)\n"
        "set_property(TARGET mylib PROPERTY KIND lib)\n"
        "set_property(TARGET app PROPERTY KIND app)\n" + cmake
    )
    (tmp_path / "lib.c").write_text("int f(void) { return 0; }\n")
    (tmp_path / "main.c").write_text("int main(void) { return 0; }\n")
    configure(tmp_path, "build")
    return (tmp_path / "build.ninja").read_text()


def test_target_property_in_compile_definitions(tmp_path: Path) -> None:
    """A library's own definitions are about itself, the ones it passes on
    about each target that uses it."""
    ninja_content = _configure(
        tmp_path,
        "target_compile_definitions(mylib\n"
        "    PRIVATE OWN=$<TARGET_PROPERTY:KIND>\n"
        "    PUBLIC BOTH=$<TARGET_PROPERTY:KIND>\n"
        "    INTERFACE USER=$<TARGET_PROPERTY:NAME>\n"
        "    INTERFACE $<$<STREQUAL:$<TARGET_PROPERTY:TYPE>,EXECUTABLE>:IN_EXE;IN_APP>\n"
        "    INTERFACE $<$<BOOL:$<TARGET_PROPERTY:NO_SUCH_PROPERTY>>:UNSET>)\n",
    )

    assert _cflags(ninja_content, "_lib.o") == ["-DOWN=lib", "-DBOTH=lib"]
    assert _cflags(ninja_content, "_main.o") == [
        "-DBOTH=app",
        "-DUSER=app",
        "-DIN_EXE",
        "-DIN_APP",
    ]


def test_target_property_in_compile_options(tmp_path: Path) -> None:
    ninja_content = _configure(
        tmp_path,
        "target_compile_options(mylib\n"
        "    PRIVATE -DOWN=$<TARGET_PROPERTY:KIND>\n"
        "    PUBLIC -DBOTH=$<TARGET_PROPERTY:KIND>\n"
        "    INTERFACE -DOTHER=$<TARGET_PROPERTY:mylib,KIND>)\n",
    )

    assert _cflags(ninja_content, "_lib.o") == ["-DOWN=lib", "-DBOTH=lib"]
    assert _cflags(ninja_content, "_main.o") == ["-DBOTH=app", "-DOTHER=lib"]


def test_target_property_in_include_directories(tmp_path: Path) -> None:
    ninja_content = _configure(
        tmp_path,
        "target_include_directories(mylib\n"
        "    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/$<TARGET_PROPERTY:KIND>/own\n"
        "    INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/$<TARGET_PROPERTY:KIND>/include)\n",
    )

    assert _cflags(ninja_content, "_lib.o") == ["-Ilib/own"]
    assert _cflags(ninja_content, "_main.o") == ["-Iapp/include"]


def test_target_property_in_relative_include_directories(tmp_path: Path) -> None:
    """A relative directory is about the directory of the library that has it,
    also if it's evaluated for the target using it."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "CMakeLists.txt").write_text(
        "add_library(sublib INTERFACE)\n"
        "target_include_directories(sublib INTERFACE include/$<TARGET_PROPERTY:KIND>)\n"
    )
    ninja_content = _configure(
        tmp_path,
        "add_subdirectory(sub)\ntarget_link_libraries(app PRIVATE sublib)\n",
    )

    assert _cflags(ninja_content, "app_main.o") == ["-Isub/include/app"]


def test_target_property_in_link_options(tmp_path: Path) -> None:
    ninja_content = _configure(
        tmp_path,
        "target_link_options(mylib INTERFACE -Wl,--kind=$<TARGET_PROPERTY:KIND>)\n",
    )

    assert "-Wl,--kind=app" in ninja_content


def test_target_property_in_post_build_command(tmp_path: Path) -> None:
    ninja_content = _configure(
        tmp_path,
        "add_custom_command(TARGET app POST_BUILD\n"
        "    COMMAND tool --kind=$<TARGET_PROPERTY:KIND>)\n",
    )

    assert "tool --kind=app" in ninja_content


def _libs(ninja_content: str, output_suffix: str) -> list[str]:
    """The libs of the build edge whose output ends with output_suffix."""
    unwrapped = re.sub(r"\$\n *", "", ninja_content)
    match = re.search(
        rf"^build \S*{re.escape(output_suffix)}: .*\n(?:  libs = (.*))?",
        unwrapped,
        re.MULTILINE,
    )
    assert match, f"no build edge for {output_suffix}"
    return to_posix_path(match.group(1) or "").split()


def test_target_property_in_link_libraries(tmp_path: Path) -> None:
    """What a library makes the targets using it link to is about each of them."""
    ninja_content = _configure(
        tmp_path,
        "add_executable(other main.c)\n"
        "target_link_libraries(other PRIVATE mylib)\n"
        "set_property(TARGET app PROPERTY EXTRA_LIBS m dl)\n"
        "target_link_libraries(mylib\n"
        "    INTERFACE $<TARGET_PROPERTY:EXTRA_LIBS>\n"
        "    PUBLIC $<$<STREQUAL:$<TARGET_PROPERTY:KIND>,app>:rt>)\n"
        "target_link_libraries(app PRIVATE $<TARGET_PROPERTY:KIND>_private)\n",
    )

    assert sorted(_libs(ninja_content, "/app")) == [
        "-lapp_private",
        "-ldl",
        "-lm",
        "-lrt",
    ]
    assert _libs(ninja_content, "/other") == []


def test_target_property_in_link_directories(tmp_path: Path) -> None:
    ninja_content = _configure(
        tmp_path,
        "add_executable(other main.c)\n"
        "target_link_libraries(other PRIVATE mylib)\n"
        "set_property(TARGET other PROPERTY KIND other)\n"
        "target_link_directories(mylib INTERFACE\n"
        "    ${CMAKE_CURRENT_SOURCE_DIR}/$<TARGET_PROPERTY:KIND>/lib\n"
        "    $<$<BOOL:$<TARGET_PROPERTY:NO_SUCH_PROPERTY>>:unset>)\n",
    )

    assert _libs(ninja_content, "/app") == ["-Lapp/lib"]
    assert _libs(ninja_content, "/other") == ["-Lother/lib"]


def test_target_property_in_relative_link_directories(tmp_path: Path) -> None:
    """A relative directory is about the directory of the library that has it,
    also if it's evaluated for the target using it."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "CMakeLists.txt").write_text(
        "add_library(sublib INTERFACE)\n"
        "target_link_directories(sublib INTERFACE lib/$<TARGET_PROPERTY:KIND>)\n"
    )
    ninja_content = _configure(
        tmp_path,
        "add_subdirectory(sub)\ntarget_link_libraries(app PRIVATE sublib)\n",
    )

    assert _libs(ninja_content, "/app") == ["-Lsub/lib/app"]


def test_target_property_in_directory_include_directories(tmp_path: Path) -> None:
    """include_directories() is about each target of the directory."""
    ninja_content = _configure(
        tmp_path,
        "include_directories(inc/$<TARGET_PROPERTY:KIND>\n"
        "    $<$<BOOL:$<TARGET_PROPERTY:NO_SUCH_PROPERTY>>:unset>)\n"
        "add_library(late STATIC lib.c)\n"
        "set_property(TARGET late PROPERTY KIND late)\n"
        "get_directory_property(DIRECTORY_INCLUDES INCLUDE_DIRECTORIES)\n"
        'message("includes: ${DIRECTORY_INCLUDES}")\n',
    )

    assert _cflags(ninja_content, "mylib_lib.o") == ["-Iinc/lib"]
    assert _cflags(ninja_content, "app_main.o") == ["-Iinc/app"]
    assert _cflags(ninja_content, "late_lib.o") == ["-Iinc/late"]
