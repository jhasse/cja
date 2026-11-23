"""Tests for set_property and get_property commands."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command, parse


def test_set_property_global() -> None:
    """Test set_property(GLOBAL PROPERTY ...)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="set_property",
            args=["GLOBAL", "PROPERTY", "CPM_INITIALIZED", "true"],
            line=1,
        )
    ]
    process_commands(commands, ctx)
    assert ctx.global_properties["CPM_INITIALIZED"] == "true"


def test_set_property_global_multiple_values() -> None:
    """Test set_property(GLOBAL PROPERTY ...) with multiple values."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="set_property",
            args=["GLOBAL", "PROPERTY", "MY_LIST", "a", "b", "c"],
            line=1,
        )
    ]
    process_commands(commands, ctx)
    assert ctx.global_properties["MY_LIST"] == "a;b;c"


def test_set_property_global_append() -> None:
    """Test set_property(GLOBAL APPEND PROPERTY ...)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="set_property",
            args=["GLOBAL", "PROPERTY", "MY_LIST", "a", "b"],
            line=1,
        ),
        Command(
            name="set_property",
            args=["GLOBAL", "APPEND", "PROPERTY", "MY_LIST", "c", "d"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.global_properties["MY_LIST"] == "a;b;c;d"


def test_set_property_global_append_string() -> None:
    """Test set_property(GLOBAL APPEND_STRING PROPERTY ...)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="set_property",
            args=["GLOBAL", "PROPERTY", "MY_STRING", "hello"],
            line=1,
        ),
        Command(
            name="set_property",
            args=["GLOBAL", "APPEND_STRING", "PROPERTY", "MY_STRING", "world"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.global_properties["MY_STRING"] == "helloworld"


def test_get_property_global() -> None:
    """Test get_property(GLOBAL PROPERTY ...)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="set_property",
            args=["GLOBAL", "PROPERTY", "CPM_INITIALIZED", "true"],
            line=1,
        ),
        Command(
            name="get_property",
            args=["MY_VAR", "GLOBAL", "PROPERTY", "CPM_INITIALIZED"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["MY_VAR"] == "true"


def test_get_property_global_not_set() -> None:
    """Like CMake, get_property unsets the variable for a property that isn't set."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["MY_VAR", "before"], line=1),
        Command(
            name="get_property",
            args=["MY_VAR", "GLOBAL", "PROPERTY", "NONEXISTENT"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)
    assert "MY_VAR" not in ctx.variables


def test_get_property_global_set_to_empty_is_set() -> None:
    """Like CMake, a global property set to an empty string counts as SET."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set_property", args=["GLOBAL", "PROPERTY", "P", ""], line=1),
        Command(name="get_property", args=["v", "GLOBAL", "PROPERTY", "P", "SET"], line=2),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["v"] == "1"


def test_get_property_global_defined() -> None:
    """Test get_property with DEFINED query."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="set_property",
            args=["GLOBAL", "PROPERTY", "MY_PROP", "value"],
            line=1,
        ),
        Command(
            name="get_property",
            args=["IS_DEFINED", "GLOBAL", "PROPERTY", "MY_PROP", "DEFINED"],
            line=2,
        ),
        Command(
            name="get_property",
            args=["NOT_DEFINED", "GLOBAL", "PROPERTY", "NONEXISTENT", "DEFINED"],
            line=3,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["IS_DEFINED"] == "1"
    assert ctx.variables["NOT_DEFINED"] == "0"


def test_set_property_target() -> None:
    """Test set_property(TARGET PROPERTY ...)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["mylib", "STATIC", "lib.cpp"], line=1),
        Command(
            name="set_property",
            args=[
                "TARGET",
                "mylib",
                "PROPERTY",
                "INTERFACE_INCLUDE_DIRECTORIES",
                "include",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)
    lib = ctx.get_library("mylib")
    assert lib is not None
    assert any("include" in d for d in lib.public_include_directories)


def test_set_property_target_append() -> None:
    """Test set_property(TARGET APPEND PROPERTY ...)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["mylib", "STATIC", "lib.cpp"], line=1),
        Command(
            name="set_property",
            args=[
                "TARGET",
                "mylib",
                "PROPERTY",
                "INTERFACE_INCLUDE_DIRECTORIES",
                "include1",
            ],
            line=2,
        ),
        Command(
            name="set_property",
            args=[
                "TARGET",
                "mylib",
                "APPEND",
                "PROPERTY",
                "INTERFACE_INCLUDE_DIRECTORIES",
                "include2",
            ],
            line=3,
        ),
    ]
    process_commands(commands, ctx)
    lib = ctx.get_library("mylib")
    assert lib is not None
    assert len(lib.public_include_directories) >= 2


def test_get_property_target() -> None:
    """Test get_property(TARGET PROPERTY ...)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["mylib", "STATIC", "lib.cpp"], line=1),
        Command(
            name="set_property",
            args=[
                "TARGET",
                "mylib",
                "PROPERTY",
                "COMPILE_DEFINITIONS",
                "FOO=1",
                "BAR=2",
            ],
            line=2,
        ),
        Command(
            name="get_property",
            args=["MY_DEFS", "TARGET", "mylib", "PROPERTY", "COMPILE_DEFINITIONS"],
            line=3,
        ),
    ]
    process_commands(commands, ctx)
    assert "FOO=1" in ctx.variables["MY_DEFS"]
    assert "BAR=2" in ctx.variables["MY_DEFS"]


def test_set_property_source() -> None:
    """Test set_property(SOURCE PROPERTY ...)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="set_property",
            args=["SOURCE", "main.cpp", "PROPERTY", "COMPILE_DEFINITIONS", "DEBUG=1"],
            line=1,
        )
    ]
    process_commands(commands, ctx)
    source_path = str(ctx.source_dir / "main.cpp")
    assert source_path in ctx.source_file_properties
    assert "DEBUG=1" in ctx.source_file_properties[source_path].compile_definitions


def test_set_property_source_append() -> None:
    """Test set_property(SOURCE APPEND PROPERTY ...)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="set_property",
            args=["SOURCE", "main.cpp", "PROPERTY", "COMPILE_DEFINITIONS", "DEBUG=1"],
            line=1,
        ),
        Command(
            name="set_property",
            args=[
                "SOURCE",
                "main.cpp",
                "APPEND",
                "PROPERTY",
                "COMPILE_DEFINITIONS",
                "VERBOSE=1",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)
    source_path = str(ctx.source_dir / "main.cpp")
    assert source_path in ctx.source_file_properties
    props = ctx.source_file_properties[source_path].compile_definitions
    assert "DEBUG=1" in props
    assert "VERBOSE=1" in props


def test_get_property_source() -> None:
    """Test get_property(SOURCE PROPERTY ...)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="set_property",
            args=["SOURCE", "main.cpp", "PROPERTY", "COMPILE_DEFINITIONS", "FOO=1"],
            line=1,
        ),
        Command(
            name="get_property",
            args=[
                "MY_DEFS",
                "SOURCE",
                "main.cpp",
                "PROPERTY",
                "COMPILE_DEFINITIONS",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["MY_DEFS"] == "FOO=1"


def test_set_property_source_include_directories() -> None:
    """Test set_property(SOURCE PROPERTY INCLUDE_DIRECTORIES)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="set_property",
            args=["SOURCE", "main.cpp", "PROPERTY", "INCLUDE_DIRECTORIES", "include"],
            line=1,
        )
    ]
    process_commands(commands, ctx)
    source_path = str(ctx.source_dir / "main.cpp")
    assert source_path in ctx.source_file_properties
    assert any(
        "include" in d
        for d in ctx.source_file_properties[source_path].include_directories
    )


def test_set_property_multiple_targets() -> None:
    """Test set_property with multiple targets."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_library", args=["lib1", "STATIC", "lib1.cpp"], line=1),
        Command(name="add_library", args=["lib2", "STATIC", "lib2.cpp"], line=2),
        Command(
            name="set_property",
            args=[
                "TARGET",
                "lib1",
                "lib2",
                "PROPERTY",
                "COMPILE_DEFINITIONS",
                "SHARED_DEF=1",
            ],
            line=3,
        ),
    ]
    process_commands(commands, ctx)
    lib1 = ctx.get_library("lib1")
    lib2 = ctx.get_library("lib2")
    assert lib1 is not None
    assert lib2 is not None
    assert "SHARED_DEF=1" in lib1.compile_definitions
    assert "SHARED_DEF=1" in lib2.compile_definitions


def test_set_property_multiple_sources() -> None:
    """Test set_property with multiple source files."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="set_property",
            args=[
                "SOURCE",
                "file1.cpp",
                "file2.cpp",
                "PROPERTY",
                "COMPILE_DEFINITIONS",
                "SHARED_DEF=1",
            ],
            line=1,
        )
    ]
    process_commands(commands, ctx)
    file1_path = str(ctx.source_dir / "file1.cpp")
    file2_path = str(ctx.source_dir / "file2.cpp")
    assert file1_path in ctx.source_file_properties
    assert file2_path in ctx.source_file_properties
    assert "SHARED_DEF=1" in ctx.source_file_properties[file1_path].compile_definitions
    assert "SHARED_DEF=1" in ctx.source_file_properties[file2_path].compile_definitions


def test_set_property_empty_value_unsets() -> None:
    """Test that set_property with no values unsets the property."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="set_property",
            args=["GLOBAL", "PROPERTY", "MY_PROP", "value"],
            line=1,
        ),
        Command(name="set_property", args=["GLOBAL", "PROPERTY", "MY_PROP"], line=2),
    ]
    process_commands(commands, ctx)
    assert "MY_PROP" not in ctx.global_properties


@pytest.mark.parametrize(
    ("setup", "scope"),
    [
        ("", "GLOBAL"),
        ("", "DIRECTORY"),
        ("add_test(NAME tst COMMAND cmd)", "TEST tst"),
        ("add_library(tgt STATIC lib.c)", "TARGET tgt"),
        ("add_executable(tgt main.c)", "TARGET tgt"),
        ("add_library(tgt UNKNOWN IMPORTED)", "TARGET tgt"),
        ("add_custom_target(tgt)", "TARGET tgt"),
    ],
)
def test_set_property_without_values(setup: str, scope: str) -> None:
    """No values unset a property, unless they're appended."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(
        parse(
            f"{setup}\n"
            f"set_property({scope} PROPERTY MY_PROP x)\n"
            f"set_property({scope} APPEND PROPERTY MY_PROP)\n"
            f"set_property({scope} APPEND PROPERTY OTHER_PROP)\n"
            f"get_property(APPENDED {scope} PROPERTY MY_PROP)\n"
            f"get_property(OTHER_IS_SET {scope} PROPERTY OTHER_PROP SET)\n"
            f"set_property({scope} PROPERTY MY_PROP)\n"
            f"get_property(IS_SET {scope} PROPERTY MY_PROP SET)\n"
            f'set_property({scope} PROPERTY MY_PROP "")\n'
            f"get_property(EMPTY_IS_SET {scope} PROPERTY MY_PROP SET)\n"
        ),
        ctx,
        strict=True,
    )

    assert ctx.variables["APPENDED"] == "x"
    assert ctx.variables["OTHER_IS_SET"] == "0"
    assert ctx.variables["IS_SET"] == "0"
    assert ctx.variables["EMPTY_IS_SET"] == "1"


def test_set_property_append_string_multiple_values() -> None:
    """APPEND_STRING appends the values as the list that they are."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(
        parse(
            "set_property(GLOBAL PROPERTY MY_PROP a)\n"
            "set_property(GLOBAL APPEND_STRING PROPERTY MY_PROP b c)\n"
            'set_property(GLOBAL PROPERTY EMPTY_PROP "")\n'
            "set_property(GLOBAL APPEND PROPERTY EMPTY_PROP d)\n"
        ),
        ctx,
        strict=True,
    )

    assert ctx.global_properties["MY_PROP"] == "ab;c"
    assert ctx.global_properties["EMPTY_PROP"] == "d"


def test_get_test_property() -> None:
    """get_test_property() stores NOTFOUND for what isn't set."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(
        parse(
            "add_test(NAME tst COMMAND cmd)\n"
            'set_tests_properties(tst PROPERTIES LABELS "a;b" EMPTY "")\n'
            "get_test_property(tst LABELS LABELS)\n"
            "get_test_property(tst LABELS DIRECTORY . LABELS_IN_DIRECTORY)\n"
            "get_test_property(tst EMPTY EMPTY)\n"
            "get_test_property(tst NO_SUCH_PROPERTY UNSET)\n"
            "get_test_property(no_such_test LABELS NO_TEST)\n"
        ),
        ctx,
        strict=True,
    )

    assert ctx.variables["LABELS"] == "a;b"
    assert ctx.variables["LABELS_IN_DIRECTORY"] == "a;b"
    assert ctx.variables["EMPTY"] == ""
    assert ctx.variables["UNSET"] == "NOTFOUND"
    assert ctx.variables["NO_TEST"] == "NOTFOUND"

    with pytest.raises(SystemExit):
        process_commands(parse("get_test_property(tst LABELS)\n"), ctx, strict=True)


def test_get_cmake_property() -> None:
    """get_cmake_property() lists variables and reads global properties."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["B_NORMAL", "1"], line=1),
        Command(name="set", args=["A_CACHED", "1", "CACHE", "BOOL", ""], line=2),
        Command(name="set", args=["REMOVED", "1"], line=3),
        Command(name="unset", args=["REMOVED"], line=4),
        Command(name="set_property", args=["GLOBAL", "PROPERTY", "MY_PROP", "x"], line=5),
        Command(name="get_cmake_property", args=["VARS", "VARIABLES"], line=6),
        Command(name="get_cmake_property", args=["CACHED", "CACHE_VARIABLES"], line=7),
        Command(name="get_cmake_property", args=["PROP", "MY_PROP"], line=8),
        Command(name="get_cmake_property", args=["MISSING", "NO_SUCH_PROP"], line=9),
    ]
    process_commands(commands, ctx, strict=True)

    variables = ctx.variables["VARS"].split(";")
    assert variables == sorted(variables)
    assert {"A_CACHED", "B_NORMAL"} <= set(variables)
    assert "REMOVED" not in variables
    assert ctx.variables["CACHED"].split(";") == ["A_CACHED"]
    assert ctx.variables["PROP"] == "x"
    assert ctx.variables["MISSING"] == "NOTFOUND"
