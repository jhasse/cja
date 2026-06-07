"""Tests for cmake_push_check_state / pop / reset commands."""

from pathlib import Path

from cja.generator import BuildContext, process_commands
from cja.parser import parse


def test_push_pop_restores_required_vars() -> None:
    content = (
        'set(CMAKE_REQUIRED_LIBRARIES "-loriginal")\n'
        "cmake_push_check_state()\n"
        'set(CMAKE_REQUIRED_LIBRARIES "-lextra")\n'
        "cmake_pop_check_state()\n"
    )
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(parse(content), ctx)

    assert ctx.variables["CMAKE_REQUIRED_LIBRARIES"] == "-loriginal"


def test_push_reset_clears_then_pop_restores() -> None:
    content = (
        'set(CMAKE_REQUIRED_FLAGS "-Wall")\n'
        "cmake_push_check_state(RESET)\n"
    )
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(parse(content), ctx)
    assert ctx.variables["CMAKE_REQUIRED_FLAGS"] == ""

    content2 = (
        'set(CMAKE_REQUIRED_FLAGS "-Wall")\n'
        "cmake_push_check_state(RESET)\n"
        'set(CMAKE_REQUIRED_FLAGS "-Werror")\n'
        "cmake_pop_check_state()\n"
    )
    ctx2 = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(parse(content2), ctx2)
    assert ctx2.variables["CMAKE_REQUIRED_FLAGS"] == "-Wall"


def test_reset_clears_required_vars() -> None:
    content = (
        'set(CMAKE_REQUIRED_DEFINITIONS "-DFOO")\n'
        'set(CMAKE_REQUIRED_INCLUDES "/usr/include")\n'
        "cmake_reset_check_state()\n"
    )
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(parse(content), ctx)

    assert ctx.variables["CMAKE_REQUIRED_DEFINITIONS"] == ""
    assert ctx.variables["CMAKE_REQUIRED_INCLUDES"] == ""


def test_nested_push_pop() -> None:
    content = (
        'set(CMAKE_REQUIRED_LIBRARIES "a")\n'
        "cmake_push_check_state()\n"
        'set(CMAKE_REQUIRED_LIBRARIES "b")\n'
        "cmake_push_check_state()\n"
        'set(CMAKE_REQUIRED_LIBRARIES "c")\n'
        "cmake_pop_check_state()\n"
    )
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(parse(content), ctx)
    assert ctx.variables["CMAKE_REQUIRED_LIBRARIES"] == "b"
