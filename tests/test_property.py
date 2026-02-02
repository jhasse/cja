"""Tests for set_property and get_property commands."""

from pathlib import Path

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


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
    """Test get_property for non-existent global property."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="get_property",
            args=["MY_VAR", "GLOBAL", "PROPERTY", "NONEXISTENT"],
            line=1,
        )
    ]
    process_commands(commands, ctx)
    assert ctx.variables["MY_VAR"] == ""


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
