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
    """Calls that don't fit on one line are laid out like cmake-format does."""
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
project(demo VERSION 1.0 LANGUAGES CXX)
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
install(TARGETS demo RUNTIME DESTINATION bin LIBRARY DESTINATION lib)
add_custom_command(
  OUTPUT generated.h
  COMMAND python3 ${CMAKE_CURRENT_SOURCE_DIR}/generate.py --output generated.h
  DEPENDS generate.py
  VERBATIM)
"""
    )


def test_call_that_fits_stays_on_one_line() -> None:
    """Unlike cmake-format, many arguments or groups alone don't force a break."""
    source = """\
set(x "${y}" PARENT_SCOPE)
list(APPEND foo a b c d e f g)
find_package(Boost COMPONENTS coroutine thread REQUIRED) # trailing
"""
    assert fmt(source) == source
    assert (
        fmt(source, line_width=40)
        == """\
set(x "${y}" PARENT_SCOPE)
list(APPEND foo a b c d e f g)
find_package(
  Boost
  COMPONENTS coroutine thread
  REQUIRED) # trailing
"""
    )
    assert fmt(source, line_width=25).startswith("""\
set(x
    "${y}"
    PARENT_SCOPE)
list(
  APPEND
  foo
  a
""")


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

    # Blank lines in a disabled region are only copied once
    source = "# cmake-format: off\nset(a 1)\n\nset(b 2)\n# cmake-format: on\n"
    assert fmt(source) == source


def test_lines() -> None:
    source = """\
SET(a   1)
if(X)
SET(b   2)   # note


SET(c   3) SET(d 4)
endif()
SET(e
  5)
"""

    def fmt_lines(*ranges: tuple[int, int]) -> str:
        return format_source(source, Style(), lines=list(ranges))

    assert fmt_lines() == source
    assert fmt_lines((100, 100)) == source
    # Statements are indented according to the surrounding blocks
    assert fmt_lines((3, 3)) == source.replace("SET(b   2)   # note", "  set(b 2) # note")
    # A range that touches any line of a statement formats all of it
    assert fmt_lines((9, 9)) == source.replace("SET(e\n  5)", "set(e 5)")
    # Statements sharing a line are formatted together, including the blank
    # lines before them
    assert fmt_lines((6, 6)) == source.replace(
        "\n\n\nSET(c   3) SET(d 4)", "\n\n  set(c 3)\n  set(d 4)"
    )
    assert fmt_lines((4, 4)) == fmt_lines((6, 6))
    assert fmt_lines((1, 9)) == fmt(source)


def test_lines_keep_untouched_bytes() -> None:
    source = "set(a  1)\r\nset(b  2)\n\n\n\nset(c  3)"
    style = Style()
    assert format_source(source, style, lines=[(2, 2)]) == (
        "set(a  1)\r\nset(b 2)\n\n\n\nset(c  3)"
    )
    assert format_source(source, style, lines=[(6, 6)]) == (
        "set(a  1)\r\nset(b  2)\n\nset(c 3)\n"
    )
    assert format_source("set(a  1)\n\n\n", style, lines=[(3, 3)]) == "set(a  1)\n"
    assert format_source("\n\n", style, lines=[(1, 1)]) == ""


def test_lines_format_off() -> None:
    source = """\
# cmake-format: off
SET(keep    this)
# cmake-format: on
SET(c   d)
"""
    assert format_source(source, Style(), lines=[(2, 2)]) == source
    assert format_source(source, Style(), lines=[(4, 4)]) == source.replace(
        "SET(c   d)", "set(c d)"
    )


def test_line_endings_and_bom() -> None:
    assert fmt("set(a b)\r\nset(c d)\r\n") == "set(a b)\r\nset(c d)\r\n"
    assert fmt("set(a b)\r\n", line_ending="LF") == "set(a b)\n"
    assert fmt("set(a b)\n", line_ending="CRLF") == "set(a b)\r\n"
    assert fmt("﻿set(a b)") == "﻿set(a b)\n"


def test_tabs() -> None:
    source = (
        "if(a)\nset(SRCS source_a.cpp source_b.cpp source_c.cpp source_d.cpp "
        "source_e.cpp source_f.cpp)\nendif()\n"
    )
    first_line = "if(a)\n\tset(SRCS source_a.cpp source_b.cpp source_c.cpp source_d.cpp source_e.cpp\n"
    # Block indentation uses tabs, alignment uses spaces
    assert fmt(source, use_tab="ForIndentation", indent_width=4, tab_width=4) == (
        first_line + "\t         source_f.cpp)\nendif()\n"
    )
    assert fmt(source, use_tab="Always", indent_width=4, tab_width=4) == (
        first_line + "\t\t\t source_f.cpp)\nendif()\n"
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

    result = run_cja(
        "format",
        "--lines",
        "3:3",
        cwd=tmp_path,
        stdin="IF(a)\nSET(b c)\nENDIF()\n",
    )
    assert result.returncode == 0
    assert result.stdout == "IF(a)\nSET(b c)\nendif()\n"

    result = run_cja("format", "--lines", "2:1", cwd=tmp_path, stdin="")
    assert result.returncode == 2
    assert "invalid line range" in result.stderr

    result = run_cja(
        "format", "--lines", "1:1", "CMakeLists.txt", "CMakeLists.txt", cwd=tmp_path
    )
    assert result.returncode == 1
    assert "one file" in result.stderr

    (tmp_path / "bad.cmake").write_text("set(a\n")
    result = run_cja("format", "bad.cmake", cwd=tmp_path)
    assert result.returncode == 1
    assert "bad.cmake:1:" in result.stderr


def test_cmake_format_json(tmp_path: Path) -> None:
    (tmp_path / ".clang-format").write_text("IndentWidth: 4\nColumnLimit: 100\n")
    (tmp_path / ".cmake-format.json").write_text(
        '{"parse": {"additional_commands": {}},'
        ' "format": {"tab_size": 3, "use_tabchars": true, "line_ending": "windows",'
        ' "command_case": "upper", "max_pargs_hwrap": 2}}'
    )
    style = find_style(tmp_path / "sub")
    assert style.line_width == 100
    assert style.indent_width == 3
    assert style.tab_width == 3
    assert style.use_tab == "Always"
    assert style.line_ending == "CRLF"
    assert style.command_case == "upper"
    assert not style.one_line_if_fits
    assert (
        format_source("if(a)\nset(b c d e)\nendif()\n", style)
        == "IF(a)\r\n\tSET(b\r\n\t\t c\r\n\t\t d\r\n\t\t e)\r\nENDIF()\r\n"
    )

    # Options of cmake-format < 0.6 aren't grouped into sections.
    (tmp_path / ".cmake-format.json").write_text(
        '{"line_width": 60, "command_case": "unchanged", "tab_size": "x"}'
    )
    style = find_style(tmp_path)
    assert style.line_width == 60
    assert style.indent_width == 4
    assert style.one_line_if_fits
    assert format_source("IF(a)\nSET(b c)\nENDIF()\n", style) == (
        "IF(a)\n    SET(b c)\nENDIF()\n"
    )

    (tmp_path / ".cmake-format.json").write_text("{not json")
    assert find_style(tmp_path).indent_width == 4
