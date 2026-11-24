"""Tests that commands don't expand their arguments a second time.

Like in CMake, the "${...}" that is left after expanding an argument once, from
a bracket argument or from "\\${...}", is literal text.
"""

from pathlib import Path

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
