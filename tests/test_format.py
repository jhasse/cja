"""Tests for `cja format`."""

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from cja.format import (
    NEWLINE,
    SPACE,
    Style,
    find_style,
    format_source,
    lex,
    parse_clang_format,
)

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def fmt(source: str, **style: Any) -> str:
    return format_source(source, Style(**style))


def test_matches_cmake_format_defaults() -> None:
    """Layout follows cmake-format's default configuration."""
    source = """\
cmake_minimum_required(VERSION 3.20)
project(demo VERSION 1.0 LANGUAGES CXX)
set(SOURCES src/main.cpp src/foo.cpp src/bar.cpp src/baz.cpp src/qux.cpp src/quux.cpp src/corge.cpp)
add_library(demo_lib STATIC src/foo.cpp src/bar.cpp)
target_link_libraries(demo PRIVATE demo_lib fmt::fmt spdlog::spdlog PUBLIC Threads::Threads)
if(WIN32 AND (MSVC OR CLANG_CL) AND NOT DEFINED SOME_VERY_LONG_OPTION_NAME_FOR_TESTING)
target_compile_definitions(demo PRIVATE _CRT_SECURE_NO_WARNINGS)
endif()
install(TARGETS demo RUNTIME DESTINATION bin LIBRARY DESTINATION lib)
add_custom_command(OUTPUT generated.h COMMAND python3 ${CMAKE_CURRENT_SOURCE_DIR}/generate.py --output generated.h DEPENDS generate.py VERBATIM)
"""
    assert (
        fmt(source)
        == """\
cmake_minimum_required(VERSION 3.20)
project(
  demo
  VERSION 1.0
  LANGUAGES CXX)
set(SOURCES
    src/main.cpp
    src/foo.cpp
    src/bar.cpp
    src/baz.cpp
    src/qux.cpp
    src/quux.cpp
    src/corge.cpp)
add_library(demo_lib STATIC src/foo.cpp src/bar.cpp)
target_link_libraries(
  demo
  PRIVATE demo_lib fmt::fmt spdlog::spdlog
  PUBLIC Threads::Threads)
if(WIN32
   AND (MSVC OR CLANG_CL)
   AND NOT DEFINED SOME_VERY_LONG_OPTION_NAME_FOR_TESTING)
  target_compile_definitions(demo PRIVATE _CRT_SECURE_NO_WARNINGS)
endif()
install(
  TARGETS demo
  RUNTIME DESTINATION bin
  LIBRARY DESTINATION lib)
add_custom_command(
  OUTPUT generated.h
  COMMAND python3 ${CMAKE_CURRENT_SOURCE_DIR}/generate.py --output generated.h
  DEPENDS generate.py
  VERBATIM)
"""
    )


def test_block_indentation() -> None:
    source = """\
function(foo)
foreach(x IN LISTS ARGN)
if(x)
message(STATUS ${x})
elseif(y)
else()
endif()
endforeach()
endfunction()
block()
set(a b)
endblock()
"""
    assert (
        fmt(source)
        == """\
function(foo)
  foreach(x IN LISTS ARGN)
    if(x)
      message(STATUS ${x})
    elseif(y)
    else()
    endif()
  endforeach()
endfunction()
block()
  set(a b)
endblock()
"""
    )


def test_command_case() -> None:
    """Known commands are lowercased, other commands keep their spelling."""
    source = (
        "ADD_EXECUTABLE(foo main.c)\nFETCHCONTENT_DECLARE(x URL y)\nMy_Function(a)\n"
    )
    assert (
        fmt(source)
        == "add_executable(foo main.c)\nFetchContent_Declare(x URL y)\nMy_Function(a)\n"
    )


def test_unknown_command_keywords_are_guessed() -> None:
    source = (
        "CPMAddPackage(NAME cereal URL https://github.com/USCiLab/cereal/archive/refs/tags/v1.3.2.tar.gz "
        'OPTIONS "SKIP_PORTABILITY_TEST ON" "JUST_INSTALL_CEREAL ON")\n'
        "my_add_test(NAME foo SOURCES a.cpp b.cpp LIBRARIES some_really_long_library_name)\n"
    )
    assert (
        fmt(source)
        == """\
CPMAddPackage(
  NAME cereal
  URL https://github.com/USCiLab/cereal/archive/refs/tags/v1.3.2.tar.gz
  OPTIONS "SKIP_PORTABILITY_TEST ON" "JUST_INSTALL_CEREAL ON")
my_add_test(
  NAME foo
  SOURCES a.cpp b.cpp
  LIBRARIES some_really_long_library_name)
"""
    )


def test_comments_are_kept_verbatim() -> None:
    source = """\
# A header comment that is longer than eighty characters is not reflowed by cja format
#   indented example: cja build -DFOO=ON
set(SRCS
  # first
  a.cpp # trailing
  b.cpp
)
message(STATUS "done") # trailing comment after the statement that goes past the column limit
"""
    assert (
        fmt(source)
        == """\
# A header comment that is longer than eighty characters is not reflowed by cja format
#   indented example: cja build -DFOO=ON
set(SRCS
    # first
    a.cpp # trailing
    b.cpp)
message(STATUS "done") # trailing comment after the statement that goes past the column limit
"""
    )


def test_comment_on_own_line_stays_on_own_line() -> None:
    source = """\
target_compile_definitions(hidapi
  # prevent marking functions as dllexport
  PUBLIC HID_API_NO_EXPORT_DEFINE)
"""
    assert (
        fmt(source)
        == """\
target_compile_definitions(
  hidapi
  # prevent marking functions as dllexport
  PUBLIC HID_API_NO_EXPORT_DEFINE)
"""
    )


def test_blank_lines() -> None:
    source = "\n\nset(a 1)\n\n\n\nset(b 2)\nset(c 3) set(d 4)\n\n"
    assert fmt(source) == "set(a 1)\n\nset(b 2)\nset(c 3)\nset(d 4)\n"
    assert (
        fmt(source, max_empty_lines=2) == "set(a 1)\n\n\nset(b 2)\nset(c 3)\nset(d 4)\n"
    )
    assert fmt(source, max_empty_lines=0) == "set(a 1)\nset(b 2)\nset(c 3)\nset(d 4)\n"


def test_literal_arguments_are_preserved() -> None:
    source = """\
file(WRITE out.txt "first line
  second line   ")
set(x [=[ bracket
   argument ]=])
target_compile_options(foo PRIVATE $<$<CONFIG:Debug>:-fsanitize=address -fno-omit-frame-pointer>)
#[[ bracket
    comment ]]
"""
    assert (
        fmt(source)
        == """\
file(WRITE out.txt "first line
  second line   ")
set(x [=[ bracket
   argument ]=])
target_compile_options(
  foo PRIVATE $<$<CONFIG:Debug>:-fsanitize=address -fno-omit-frame-pointer>)
#[[ bracket
    comment ]]
"""
    )


def test_format_off() -> None:
    source = """\
SET(a   b)
# cmake-format: off
SET(keep    this)
  # as is
# cmake-format: on
SET(c   d)
"""
    assert (
        fmt(source)
        == """\
set(a b)
# cmake-format: off
SET(keep    this)
  # as is
# cmake-format: on
set(c d)
"""
    )


def test_line_endings_and_bom() -> None:
    assert fmt("set(a b)\r\nset(c d)\r\n") == "set(a b)\r\nset(c d)\r\n"
    assert fmt("set(a b)\r\n", line_ending="LF") == "set(a b)\n"
    assert fmt("set(a b)\n", line_ending="CRLF") == "set(a b)\r\n"
    assert fmt("﻿set(a b)") == "﻿set(a b)\n"


def test_tabs() -> None:
    source = "if(a)\nset(SRCS a.cpp b.cpp c.cpp d.cpp e.cpp f.cpp g.cpp)\nendif()\n"
    assert fmt(source, use_tab="ForIndentation", indent_width=4, tab_width=4) == (
        "if(a)\n\tset(SRCS\n\t    a.cpp\n\t    b.cpp\n\t    c.cpp\n\t    d.cpp\n"
        "\t    e.cpp\n\t    f.cpp\n\t    g.cpp)\nendif()\n"
    )
    assert fmt(source, use_tab="Always", indent_width=4, tab_width=4) == (
        "if(a)\n\tset(SRCS\n\t\ta.cpp\n\t\tb.cpp\n\t\tc.cpp\n\t\td.cpp\n"
        "\t\te.cpp\n\t\tf.cpp\n\t\tg.cpp)\nendif()\n"
    )


def test_column_limit() -> None:
    source = "target_link_libraries(foo PRIVATE bar baz)\n"
    assert (
        fmt(source, line_width=30) == "target_link_libraries(\n  foo PRIVATE bar baz)\n"
    )


def test_syntax_error() -> None:
    with pytest.raises(SyntaxError, match="Expected '\\)'"):
        fmt("set(a b\n")


def test_examples_are_stable() -> None:
    """Formatting is idempotent and keeps every token."""

    def tokens(text: str) -> list[str]:
        return [
            t.text.rstrip().lower()
            for t in lex(text, "")
            if t.kind not in (SPACE, NEWLINE)
        ]

    for path in EXAMPLES_DIR.glob("*/CMakeLists.txt"):
        source = path.read_text()
        once = fmt(source)
        assert fmt(once) == once, path
        assert tokens(once) == tokens(source), path


def test_parse_clang_format() -> None:
    text = """\
---
# comment
BasedOnStyle: Google
ColumnLimit: 100  # trailing
IncludeCategories:
  - Regex: '^<'
    Priority: 1
---
Language: Cpp
IndentWidth: 4
...
"""
    assert parse_clang_format(text) == [
        {"BasedOnStyle": "Google", "ColumnLimit": "100", "IncludeCategories": ""},
        {"Language": "Cpp", "IndentWidth": "4"},
    ]


def test_find_style(tmp_path: Path) -> None:
    assert find_style(tmp_path) == Style()

    (tmp_path / ".clang-format").write_text(
        "BasedOnStyle: Microsoft\nUseTab: Always\nMaxEmptyLinesToKeep: 3\nLineEnding: CRLF\n"
    )
    style = find_style(tmp_path / "sub" / "dir")
    assert style.line_width == 120
    assert style.indent_width == 4
    assert style.use_tab == "Always"
    assert style.max_empty_lines == 3
    assert style.line_ending == "CRLF"

    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / ".clang-format").write_text(
        "BasedOnStyle: InheritParentConfig\nColumnLimit: 0\n"
    )
    style = find_style(sub)
    assert style.indent_width == 4
    assert style.line_width == sys.maxsize

    (sub / ".clang-format").write_text(
        "---\nLanguage: Cpp\nIndentWidth: 3\n---\nLanguage: Json\nIndentWidth: 5\n"
    )
    assert find_style(sub).indent_width == 3

    (sub / ".clang-format").write_text("DisableFormat: true\n")
    assert format_source("SET(a   b)", find_style(sub)) == "SET(a   b)"


def run_cja(
    *args: str, cwd: Path, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "cja", *args],
        cwd=cwd,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli(tmp_path: Path) -> None:
    (tmp_path / ".clang-format").write_text("IndentWidth: 4\n")
    cmake_file = tmp_path / "CMakeLists.txt"
    cmake_file.write_text("IF(a)\nSET(b c)\nENDIF()\n")
    expected = "if(a)\n    set(b c)\nendif()\n"

    result = run_cja("format", "CMakeLists.txt", cwd=tmp_path)
    assert result.returncode == 0
    assert result.stdout == expected

    result = run_cja("format", "--check", "CMakeLists.txt", cwd=tmp_path)
    assert result.returncode == 1
    assert "CMakeLists.txt" in result.stderr

    result = run_cja("format", "-i", "CMakeLists.txt", cwd=tmp_path)
    assert result.returncode == 0
    assert cmake_file.read_text() == expected

    result = run_cja("format", "--check", "CMakeLists.txt", cwd=tmp_path)
    assert result.returncode == 0

    result = run_cja("format", cwd=tmp_path, stdin="IF(a)\nSET(b c)\nENDIF()\n")
    assert result.returncode == 0
    assert result.stdout == expected

    (tmp_path / "bad.cmake").write_text("set(a\n")
    result = run_cja("format", "bad.cmake", cwd=tmp_path)
    assert result.returncode == 1
    assert "bad.cmake:1:" in result.stderr
