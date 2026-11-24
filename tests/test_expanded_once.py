"""Tests that commands don't expand their arguments a second time.

Like in CMake, the "${...}" that is left after expanding an argument once, from
a bracket argument or from "\\${...}", is literal text.
"""

from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import parse


def _process(tmp_path: Path, code: str) -> BuildContext:
    """Process CMake code that has VAR set and a target called app."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    code = "set(VAR value)\nadd_executable(app main.c)\n" + code
    process_commands(parse(code), ctx, strict=True)
    return ctx


def test_requirements_are_expanded_once(tmp_path: Path) -> None:
    """The compile and link requirements of directories and targets."""
    ctx = _process(
        tmp_path,
        r"""
include_directories([[/inc/${VAR}]])
add_compile_options([[-DOPTION=${VAR}]])
add_compile_definitions([[DEFINITION=${VAR}]])
add_definitions([[-DLEGACY=${VAR}]])
target_include_directories(app PRIVATE [[/target/${VAR}]])
target_link_directories(app PRIVATE [[/lib/${VAR}]])
target_compile_definitions(app PRIVATE [[TARGET=${VAR}]] "ESCAPED=\${VAR}")
target_compile_options(app PRIVATE [[-DTARGET_OPTION=${VAR}]])
target_link_options(app PRIVATE [[-Wl,--option=${VAR}]])
target_precompile_headers(app PRIVATE [[/pch/${VAR}.h]])
foreach(property INCLUDE_DIRECTORIES LINK_DIRECTORIES COMPILE_DEFINITIONS
        COMPILE_OPTIONS LINK_OPTIONS PRECOMPILE_HEADERS)
  get_target_property(TARGET_${property} app ${property})
endforeach()
get_directory_property(DIRECTORY_INCLUDES INCLUDE_DIRECTORIES)
get_directory_property(DIRECTORY_OPTIONS COMPILE_OPTIONS)
get_directory_property(DIRECTORY_DEFINITIONS COMPILE_DEFINITIONS)
""",
    )

    assert ctx.variables["DIRECTORY_INCLUDES"] == "/inc/${VAR}"
    assert ctx.variables["DIRECTORY_OPTIONS"] == "-DOPTION=${VAR}"
    assert ctx.variables["DIRECTORY_DEFINITIONS"] == "DEFINITION=${VAR};LEGACY=${VAR}"
    assert ctx.variables["TARGET_INCLUDE_DIRECTORIES"] == "/inc/${VAR};/target/${VAR}"
    assert ctx.variables["TARGET_LINK_DIRECTORIES"] == "/lib/${VAR}"
    assert ctx.variables["TARGET_COMPILE_DEFINITIONS"] == (
        "TARGET=${VAR};ESCAPED=${VAR}"
    )
    assert ctx.variables["TARGET_COMPILE_OPTIONS"] == "-DTARGET_OPTION=${VAR}"
    assert ctx.variables["TARGET_LINK_OPTIONS"] == "-Wl,--option=${VAR}"
    assert ctx.variables["TARGET_PRECOMPILE_HEADERS"] == "/pch/${VAR}.h"


def test_source_file_properties_are_expanded_once(tmp_path: Path) -> None:
    """The names of source files and the values of their properties."""
    ctx = _process(
        tmp_path,
        r"""
set_property(SOURCE [[${VAR}.c]] PROPERTY BY_SET_PROPERTY x)
set_property(SOURCE a.c PROPERTY INCLUDE_DIRECTORIES [[/inc/${VAR}]])
set_source_files_properties([[${VAR}.c]] PROPERTIES BY_SET_SOURCE_FILES y)
set_source_files_properties(a.c PROPERTIES
    OTHER [[other${VAR}]] COMPILE_DEFINITIONS [[DEFINITION=${VAR}]])
get_property(BY_SET_PROPERTY SOURCE [[${VAR}.c]] PROPERTY BY_SET_PROPERTY)
get_source_file_property(BY_SET_SOURCE_FILES [[${VAR}.c]] BY_SET_SOURCE_FILES)
get_property(OF_EXPANDED_NAME SOURCE value.c PROPERTY BY_SET_PROPERTY SET)
get_property(INCLUDES SOURCE a.c PROPERTY INCLUDE_DIRECTORIES)
get_source_file_property(OTHER a.c OTHER)
get_source_file_property(DEFINITIONS a.c COMPILE_DEFINITIONS)
""",
    )

    assert ctx.variables["BY_SET_PROPERTY"] == "x"
    assert ctx.variables["BY_SET_SOURCE_FILES"] == "y"
    assert ctx.variables["OF_EXPANDED_NAME"] == "0"
    assert ctx.variables["INCLUDES"] == "/inc/${VAR}"
    assert ctx.variables["OTHER"] == "other${VAR}"
    assert ctx.variables["DEFINITIONS"] == "DEFINITION=${VAR}"


def test_variable_names_are_expanded_once(tmp_path: Path) -> None:
    """The names that set() and unset() get."""
    ctx = _process(
        tmp_path,
        r"""
set(NAME [[${VAR}]])
set(value before)
set(${NAME} 1)
set(AFTER_SET "${value}")
unset(${NAME})
set(AFTER_UNSET "${value}")
""",
    )

    # Neither is about the variable that VAR names.
    assert ctx.variables["AFTER_SET"] == "before"
    assert ctx.variables["AFTER_UNSET"] == "before"


def test_file_names_are_expanded_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The paths that file() and configure_file() get."""
    tmp_path = tmp_path.resolve()
    # file(WRITE) wants the build directory to be below the current one.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "template.in").write_text("@VAR@")
    (tmp_path / "source.txt").write_text("source")
    out = tmp_path / "build" / "out"
    ctx = _process(
        tmp_path,
        r"""
set(DIR "@OUT@")
set(LITERAL [[${VAR}]])
file(MAKE_DIRECTORY "${DIR}/${LITERAL}.dir")
file(WRITE "${DIR}/${LITERAL}.txt" "written")
file(APPEND "${DIR}/${LITERAL}.txt" " twice")
file(READ "${DIR}/${LITERAL}.txt" READ)
file(STRINGS "${DIR}/${LITERAL}.txt" STRINGS)
file(TOUCH "${DIR}/${LITERAL}.touched")
file(TOUCH "${DIR}/${LITERAL}.removed")
file(REMOVE "${DIR}/${LITERAL}.removed")
file(COPY "@SOURCE@/source.txt" DESTINATION "${DIR}/${LITERAL}.copy")
configure_file("@SOURCE@/template.in" "${DIR}/${LITERAL}.configured")
file(GLOB GLOBBED RELATIVE "${DIR}" "${DIR}/${LITERAL}.t*")
""".replace("@OUT@", out.as_posix()).replace("@SOURCE@", tmp_path.as_posix()),
    )

    assert sorted(path.name for path in out.iterdir()) == [
        "${VAR}.configured",
        "${VAR}.copy",
        "${VAR}.dir",
        "${VAR}.touched",
        "${VAR}.txt",
    ]
    assert ctx.variables["READ"] == "written twice"
    assert ctx.variables["STRINGS"] == "written twice"
    assert (out / "${VAR}.configured").read_text() == "value\n"
    assert (out / "${VAR}.copy" / "source.txt").read_text() == "source"
    assert sorted(ctx.variables["GLOBBED"].split(";")) == [
        "${VAR}.touched",
        "${VAR}.txt",
    ]
