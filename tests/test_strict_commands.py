"""Tests for arguments that cja ignores, which are errors in strict mode."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def make_ctx(tmp_path: Path) -> BuildContext:
    return BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")


def target(name: str) -> Command:
    return Command(name="add_library", args=[name, "STATIC", "a.c"], line=1)


@pytest.mark.parametrize(
    ("setup", "command", "expected"),
    [
        ([], Command("include_directories", ["SYSTEM", "inc"]), "SYSTEM"),
        ([], Command("include_directories", ["BEFORE", "inc"]), "BEFORE"),
        (
            [target("t")],
            Command("target_include_directories", ["t", "SYSTEM", "PUBLIC", "inc"]),
            "SYSTEM",
        ),
        (
            [target("t")],
            Command("target_include_directories", ["t", "BEFORE", "PUBLIC", "inc"]),
            "BEFORE",
        ),
        (
            [target("t")],
            Command("target_compile_options", ["t", "BEFORE", "PRIVATE", "-O1"]),
            "BEFORE",
        ),
        (
            [target("t")],
            Command("target_link_directories", ["t", "BEFORE", "PRIVATE", "lib"]),
            "BEFORE",
        ),
        (
            [target("t")],
            Command("target_link_libraries", ["t", "debug", "food", "optimized", "foo"]),
            "debug, optimized",
        ),
        (
            [target("t")],
            Command("target_sources", ["t", "PUBLIC", "FILE_SET", "HEADERS", "FILES", "a.h"]),
            "FILE_SET",
        ),
        ([], Command("add_executable", ["tool", "IMPORTED"]), "IMPORTED"),
        ([], Command("add_executable", ["tool2", "ALIAS", "tool"]), "ALIAS"),
        ([], Command("add_library", ["alias", "ALIAS", "missing"]), "ALIAS"),
        ([], Command("list", ["SORT", "l", "ORDER", "DESCENDING"]), "ORDER DESCENDING"),
        ([], Command("list", ["TRANSFORM", "l", "GENEX_STRIP"]), "GENEX_STRIP"),
        ([], Command("list", ["TRANSFORM", "l", "REPLACE", "a", "b", "AT", "0"]), "AT"),
        ([], Command("list", ["TRANSFORM", "l", "PREPEND", "x", "AT", "0"]), "AT"),
        ([], Command("list", ["TRANSFORM", "l", "TOUPPER", "REGEX", "a"]), "REGEX"),
        ([], Command("list", ["FILTER", "l", "KEEP", "REGEX", "a"]), "KEEP REGEX"),
        ([], Command("get_filename_component", ["v", "a.c", "STEM"]), "STEM"),
        ([], Command("string", ["COMPARE", "LESS_EQUAL", "a", "b", "v"]), "LESS_EQUAL"),
        ([], Command("file", ["RELATIVE_PATH", "v", "/a", "/a/b"]), "RELATIVE_PATH"),
        ([], Command("file", ["READ", "f.txt", "v", "HEX"]), "HEX"),
        (
            [],
            Command("file", ["COPY", "d", "DESTINATION", "out", "FILES_MATCHING", "PATTERN", "*.h"]),
            "FILES_MATCHING, PATTERN",
        ),
        (
            [],
            Command("file", ["GENERATE", "OUTPUT", "o", "CONTENT", "x", "TARGET", "t"]),
            "TARGET",
        ),
        (
            [],
            Command("configure_file", ["in", "out", "NEWLINE_STYLE", "CRLF"]),
            "NEWLINE_STYLE",
        ),
        ([], Command("set_property", ["CACHE", "X", "PROPERTY", "VALUE", "1"]), "CACHE"),
        ([], Command("get_property", ["v", "DIRECTORY", "PROPERTY", "P"]), "DIRECTORY"),
        (
            [],
            Command("get_directory_property", ["v", "DIRECTORY", "sub", "P"]),
            "DIRECTORY",
        ),
        (
            [],
            Command("math", ["EXPR", "v", "1", "OUTPUT_FORMAT", "OCTAL"]),
            "OUTPUT_FORMAT OCTAL",
        ),
    ],
)
def test_unsupported_args_in_strict_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    setup: list[Command],
    command: Command,
    expected: str,
) -> None:
    ctx = make_ctx(tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        process_commands([*setup, command], ctx, strict=True)
    assert exc_info.value.code == 1
    assert f"to {command.name}(): {expected}\n" in capsys.readouterr().err


@pytest.mark.parametrize(
    "command",
    [
        Command("target_include_directories", ["t", "AFTER", "PUBLIC", "inc"]),
        Command("target_link_libraries", ["t", "general", "foo"]),
        Command(
            "list",
            ["SORT", "l", "COMPARE", "STRING", "CASE", "SENSITIVE", "ORDER", "ASCENDING"],
        ),
        Command("list", ["TRANSFORM", "l", "PREPEND", "x", "OUTPUT_VARIABLE", "o"]),
        Command("file", ["GLOB_RECURSE", "v", "FOLLOW_SYMLINKS", "*.c"]),
        Command("file", ["LOCK", "lock", "RESULT_VARIABLE", "r"]),
        Command("set_property", ["SOURCE", "a.c", "DIRECTORY", "sub", "PROPERTY", "P", "1"]),
        Command("set_tests_properties", ["t", "DIRECTORY", "sub", "PROPERTIES", "P", "1"]),
    ],
)
def test_supported_args_in_strict_mode(tmp_path: Path, command: Command) -> None:
    ctx = make_ctx(tmp_path)
    process_commands([target("t"), command], ctx, strict=True)


def test_ignored_keywords_are_not_values(tmp_path: Path) -> None:
    """Without strict mode, ignored keywords aren't mistaken for values."""
    ctx = make_ctx(tmp_path)
    commands = [
        target("t"),
        Command("target_include_directories", ["t", "BEFORE", "PRIVATE", "inc"]),
        Command("target_link_directories", ["t", "BEFORE", "PRIVATE", "lib"]),
        Command(
            "target_sources",
            ["t", "PUBLIC", "FILE_SET", "api", "TYPE", "HEADERS", "BASE_DIRS", "inc", "FILES", "inc/a.h"],
        ),
        Command("target_link_libraries", ["t", "general", "foo"]),
        Command("add_executable", ["tool", "IMPORTED", "GLOBAL"]),
        Command("add_executable", ["tool2", "ALIAS", "tool"]),
        Command("set_property", ["SOURCE", "a.c", "DIRECTORY", "sub", "PROPERTY", "OBJECT_DEPENDS", "x"]),
        Command("file", ["LOCK", "lock", "RESULT_VARIABLE", "r"]),
    ]
    process_commands(commands, ctx)

    lib = ctx.get_library("t")
    assert lib is not None
    assert [Path(d).name for d in lib.include_directories] == ["inc"]
    assert [Path(d).name for d in lib.link_directories] == ["lib"]
    assert [Path(s).name for s in lib.sources] == ["a.c", "a.h"]
    assert lib.link_libraries == ["foo"]
    assert ctx.executables == []
    assert "tool" in ctx.imported_targets
    assert not any(Path(f).name == "sub" for f in ctx.source_file_properties)
    assert ctx.variables["r"] == "0"


def test_cmake_parse_arguments_parse_argv(tmp_path: Path) -> None:
    from cja.parser import parse_file

    cmake_file = tmp_path / "CMakeLists.txt"
    cmake_file.write_text(
        "function(f first)\n"
        "  cmake_parse_arguments(PARSE_ARGV 1 arg \"OPT\" \"ONE\" \"MULTI\")\n"
        "  set(r \"${first}|${arg_OPT}|${arg_ONE}|${arg_MULTI}|${arg_UNPARSED_ARGUMENTS}\""
        " PARENT_SCOPE)\n"
        "endfunction()\n"
        "f(x OPT ONE 1 MULTI a b extra)\n"
    )
    ctx = make_ctx(tmp_path)
    ctx.current_list_file = cmake_file
    process_commands(parse_file(cmake_file), ctx, strict=True)
    assert ctx.variables["r"] == "x|TRUE|1|a;b;extra|"


def test_file_to_cmake_path(tmp_path: Path) -> None:
    import os

    ctx = make_ctx(tmp_path)
    native = os.pathsep.join(["\\a\\b", "/c/d"])
    commands = [
        Command("file", ["TO_CMAKE_PATH", native, "cmake_path"]),
        Command("file", ["TO_NATIVE_PATH", "/x/y", "native_path"]),
    ]
    process_commands(commands, ctx, strict=True)
    assert ctx.variables["cmake_path"] == "/a/b;/c/d"
    expected_native = "\\x\\y" if os.name == "nt" else "/x/y"
    assert ctx.variables["native_path"] == expected_native


def test_list_transform_append_and_replace(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    ctx.variables["l"] = "foo.c;bar.c"
    commands = [
        Command("list", ["TRANSFORM", "l", "APPEND", ".in", "OUTPUT_VARIABLE", "a"]),
        Command("list", ["TRANSFORM", "l", "REPLACE", "([a-z]+)\\.c", "\\1.h"]),
    ]
    process_commands(commands, ctx, strict=True)
    assert ctx.variables["a"] == "foo.c.in;bar.c.in"
    assert ctx.variables["l"] == "foo.h;bar.h"


@pytest.mark.parametrize(
    "command",
    ["target_link_libraries", "target_include_directories", "target_compile_options"],
)
def test_target_command_on_unknown_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    """Like CMake, target_*() on a target that doesn't exist is an error."""
    commands = [Command(command, ["missing", "PRIVATE", "x"], line=1)]
    process_commands(commands, make_ctx(tmp_path))
    assert f'warning: {command} called on unknown target "missing"' in capsys.readouterr().err
    with pytest.raises(SystemExit):
        process_commands(commands, make_ctx(tmp_path), strict=True)
