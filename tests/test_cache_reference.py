"""Tests for $CACHE{VAR} references and if(DEFINED CACHE{VAR})."""

from pathlib import Path

import pytest

from cja.build_context import BuildContext
from cja.generator import configure


def _configure(tmp_path: Path, content: str, strict: bool = False) -> BuildContext:
    (tmp_path / "CMakeLists.txt").write_text(content)
    return configure(tmp_path, "build", {"FROM_CLI": "cli"}, strict=strict)


def test_cache_reference(tmp_path: Path) -> None:
    """The expected values are the output of CMake 4.3."""
    ctx = _configure(
        tmp_path,
        "set(X normal)\n"
        'set(X cached CACHE STRING "")\n'
        'set(R1 "${X} $CACHE{X}")\n'
        'set(R2 "[$CACHE{UNDEFINED}] [$CACHE{}]")\n'
        'set(R3 "\\$CACHE{X}")\n'
        "set(name X)\n"
        'set(R4 "$CACHE{${name}} [${$CACHE{name}}]")\n'
        'set(name2 X CACHE STRING "")\n'
        'set(R5 "${$CACHE{name2}} $CACHE{$CACHE{name2}}")\n'
        "function(f)\n"
        '  set(F cache CACHE STRING "")\n'
        "  set(F local)\n"
        '  set(R6 "${F} $CACHE{F}" PARENT_SCOPE)\n'
        "endfunction()\n"
        "f()\n"
        'set(R7 "${F} $CACHE{F}")\n'
        'set(R8 "$CACHE{FROM_CLI} $CACHE{CMAKE_GENERATOR}")\n'
        "unset(X CACHE)\n"
        'set(R9 "${X} [$CACHE{X}]")\n',
    )
    assert ctx.variables["R1"] == "normal cached"
    assert ctx.variables["R2"] == "[] []"
    assert ctx.variables["R3"] == "$CACHE{X}"
    assert ctx.variables["R4"] == "cached []"
    assert ctx.variables["R5"] == "normal cached"
    assert ctx.variables["R6"] == "local cache"
    assert ctx.variables["R7"] == "cache cache"
    assert ctx.variables["R8"] == "cli Ninja"
    assert ctx.variables["R9"] == "normal []"


def test_cache_reference_in_condition(tmp_path: Path) -> None:
    ctx = _configure(
        tmp_path,
        "set(X normal)\n"
        'set(X cached CACHE STRING "")\n'
        "set(N normal)\n"
        "if($CACHE{X} STREQUAL cached)\n"
        "  list(APPEND RESULT expanded)\n"
        "endif()\n"
        "if(DEFINED CACHE{X})\n"
        "  list(APPEND RESULT X)\n"
        "endif()\n"
        "if(DEFINED CACHE{N})\n"
        "  list(APPEND RESULT N)\n"
        "endif()\n"
        "unset(X CACHE)\n"
        "if(DEFINED CACHE{X})\n"
        "  list(APPEND RESULT unset)\n"
        "endif()\n",
    )
    assert ctx.variables["RESULT"] == "expanded;X"


def test_undefined_cache_reference_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Like CMake, only warn if there's no normal variable of that name either."""
    _configure(
        tmp_path,
        "set(N normal)\n"
        'set(R "$CACHE{N} $CACHE{UNDEFINED}")\n'
        'if("$CACHE{IN_CONDITION}" STREQUAL "")\n'
        "endif()\n",
        strict=True,
    )
    err = capsys.readouterr().err
    assert "CMakeLists.txt:2: warning: undefined variable referenced: UNDEFINED" in err
    assert ": N" not in err
    assert "IN_CONDITION" not in err


def test_builtin_cache_entries(tmp_path: Path) -> None:
    """The cache entries CMake creates at the start and in project()."""
    sub_dir = tmp_path / "sub"
    sub_dir.mkdir()
    (sub_dir / "CMakeLists.txt").write_text(
        "project(s)\n"
        'set(SUB "${PROJECT_IS_TOP_LEVEL} $CACHE{s_IS_TOP_LEVEL}'
        ' $CACHE{CMAKE_PROJECT_NAME}" PARENT_SCOPE)\n'
    )
    ctx = _configure(
        tmp_path,
        "set(BEFORE_COMMAND $CACHE{CMAKE_COMMAND})\n"
        "set(BEFORE_HOME $CACHE{CMAKE_HOME_DIRECTORY})\n"
        'set(BEFORE_BUILD_TYPE "$CACHE{CMAKE_BUILD_TYPE}")\n'
        "project(t)\n"
        "foreach(v BUILD_TYPE INSTALL_PREFIX C_COMPILER CXX_COMPILER MAKE_PROGRAM"
        " PROJECT_NAME)\n"
        "  set(CACHED_${v} $CACHE{CMAKE_${v}})\n"
        "endforeach()\n"
        'set(TOP "${PROJECT_IS_TOP_LEVEL} $CACHE{t_IS_TOP_LEVEL}")\n'
        "add_subdirectory(sub)\n",
    )
    assert ctx.variables["BEFORE_COMMAND"] == ctx.variables["CMAKE_COMMAND"]
    assert ctx.variables["BEFORE_HOME"] == tmp_path.as_posix()
    assert ctx.variables["BEFORE_BUILD_TYPE"] == ""
    assert ctx.variables["CACHED_BUILD_TYPE"] == "Debug"
    assert (
        ctx.variables["CACHED_INSTALL_PREFIX"]
        == (tmp_path / "build/install").as_posix()
    )
    assert ctx.variables["CACHED_C_COMPILER"] == ctx.c_compiler
    assert ctx.variables["CACHED_CXX_COMPILER"] == ctx.cxx_compiler
    assert ctx.variables["CACHED_MAKE_PROGRAM"]
    assert ctx.variables["CACHED_PROJECT_NAME"] == "t"
    assert ctx.variables["TOP"] == "ON ON"
    assert ctx.variables["SUB"] == "OFF OFF t"
    assert ctx.variables["CMAKE_PROJECT_NAME"] == "t"
    assert ctx.variables["PROJECT_IS_TOP_LEVEL"] == "ON"


def test_builtin_cache_entries_keep_earlier_values(tmp_path: Path) -> None:
    """-D values and cache entries set before project() take precedence."""
    (tmp_path / "CMakeLists.txt").write_text(
        'set(CMAKE_BUILD_TYPE Release CACHE STRING "")\n'
        "project(t)\n"
        'set(CMAKE_INSTALL_PREFIX /ignored CACHE PATH "")\n'
    )
    ctx = configure(tmp_path, "build", {"CMAKE_INSTALL_PREFIX": "/cli"})
    assert ctx.cache_values["CMAKE_BUILD_TYPE"] == "Release"
    assert ctx.cache_values["CMAKE_INSTALL_PREFIX"] == "/cli"
