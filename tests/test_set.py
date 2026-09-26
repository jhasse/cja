"""Tests for set command."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, configure, process_commands
from cja.parser import Command


def test_set_basic() -> None:
    """Test basic set command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="set", args=["MY_VAR", "hello"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["MY_VAR"] == "hello"


def test_set_multiple_values() -> None:
    """Test set with multiple values (creates semicolon-separated string)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="set", args=["MY_LIST", "a", "b", "c"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "a;b;c"


def test_set_unset() -> None:
    """Test that set with no value unsets the variable."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_VAR"] = "old_value"
    commands = [Command(name="set", args=["MY_VAR"], line=1)]
    process_commands(commands, ctx)
    assert "MY_VAR" not in ctx.variables


def test_set_with_cache() -> None:
    """Test set with CACHE keyword (should ignore CACHE and set value)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="set",
            args=["MY_VAR", "value", "CACHE", "STRING", "description"],
            line=1,
        )
    ]
    process_commands(commands, ctx)
    assert ctx.variables["MY_VAR"] == "value"


def test_set_with_parent_scope() -> None:
    """Test set with PARENT_SCOPE at top level (no effect, there's no parent)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="set", args=["MY_VAR", "value", "PARENT_SCOPE"], line=1)]
    process_commands(commands, ctx)
    # At top level, PARENT_SCOPE has no effect since there's no parent scope
    assert "MY_VAR" not in ctx.variables


def test_set_with_cache_and_force() -> None:
    """Test set with CACHE and FORCE keywords."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="set",
            args=["MY_VAR", "value", "CACHE", "STRING", "desc", "FORCE"],
            line=1,
        )
    ]
    process_commands(commands, ctx)
    assert ctx.variables["MY_VAR"] == "value"


def test_unset_cache() -> None:
    """Test unset(CACHE) removes cache variable tracking."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.cache_variables.add("CACHED")
    ctx.variables["CACHED"] = "1"
    commands = [
        Command(name="unset", args=["CACHED", "CACHE"], line=1),
    ]
    process_commands(commands, ctx)

    assert "CACHED" not in ctx.cache_variables
    assert "CACHED" not in ctx.variables


def test_set_expands_variable_name() -> None:
    """Test set with variable name expansion."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["VAR_NAME", "FOO"], line=1),
        Command(name="set", args=["${VAR_NAME}", "bar"], line=2),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["FOO"] == "bar"


def test_set_expands_nested_variable_reference() -> None:
    """Nested variable references like ${A_${B}_C} should expand in passes."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["PACKAGE", "Box2D"], line=1),
        Command(name="set", args=["CPM_PACKAGE_Box2D_SOURCE_DIR", "/tmp/box2d"], line=2),
        Command(
            name="set",
            args=["OUT", "${CPM_PACKAGE_${PACKAGE}_SOURCE_DIR}"],
            line=3,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["OUT"] == "/tmp/box2d"


def test_set_cache_persists_outside_function() -> None:
    """set(... CACHE ...) inside a function should persist globally."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="function", args=["set_cached"], line=1),
        Command(
            name="set",
            args=["CACHED_VAR", "cached-value", "CACHE", "STRING", "doc"],
            line=2,
        ),
        Command(name="endfunction", args=[], line=3),
        Command(name="set_cached", args=[], line=4),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["CACHED_VAR"] == "cached-value"
    assert "CACHED_VAR" in ctx.cache_variables


def test_normal_variable_hides_cache_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Normal and cache variables interact like in CMake (CMP0126 NEW)."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "CMakeLists.txt").write_text(
        'set(C6 from-sub CACHE STRING "" FORCE)\n'
    )
    (tmp_path / "CMakeLists.txt").write_text(
        """
project(p NONE)
set(C2 cache CACHE STRING "")
set(C2 normal)
message(STATUS "shadow: [${C2}]")
set(C2 forced CACHE STRING "" FORCE)
message(STATUS "force-while-shadowed: [${C2}]")
unset(C2)
message(STATUS "unset-normal: [${C2}]")
set(N3 normal)
set(N3 cache CACHE STRING "")
message(STATUS "normal-before-cache: [${N3}]")
set(C4 cache CACHE STRING "")
function(f)
  set(C4 in-func)
  set(C5 new-in-func CACHE STRING "")
endfunction()
f()
message(STATUS "func: [${C4}] [${C5}]")
set(C6 parent-normal)
add_subdirectory(sub)
message(STATUS "subdir: [${C6}]")
unset(C6)
message(STATUS "subdir-after-unset: [${C6}]")
set(D1 set-in-list)
message(STATUS "cli: [${D1}]")
"""
    )

    configure(tmp_path, "build", variables={"D1": "cli"})

    out = capsys.readouterr().out
    assert "shadow: [normal]" in out
    assert "force-while-shadowed: [normal]" in out
    assert "unset-normal: [forced]" in out
    assert "normal-before-cache: [normal]" in out
    assert "func: [cache] [new-in-func]" in out
    assert "subdir: [parent-normal]" in out
    assert "subdir-after-unset: [from-sub]" in out
    assert "cli: [set-in-list]" in out
