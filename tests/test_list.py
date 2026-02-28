"""Tests for list command."""

from pathlib import Path

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_list_length() -> None:
    """Test list(LENGTH) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "a;b;c;d"
    commands = [Command(name="list", args=["LENGTH", "MY_LIST", "LIST_LEN"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["LIST_LEN"] == "4"


def test_list_length_empty() -> None:
    """Test list(LENGTH) on empty list."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="list", args=["LENGTH", "MY_LIST", "LIST_LEN"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["LIST_LEN"] == "0"


def test_list_get() -> None:
    """Test list(GET) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "a;b;c;d"
    commands = [
        Command(name="list", args=["GET", "MY_LIST", "0", "2", "RESULT"], line=1)
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "a;c"


def test_list_get_negative_index() -> None:
    """Test list(GET) with negative index."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "a;b;c;d"
    commands = [Command(name="list", args=["GET", "MY_LIST", "-1", "RESULT"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "d"


def test_list_append() -> None:
    """Test list(APPEND) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "a;b"
    commands = [Command(name="list", args=["APPEND", "MY_LIST", "c", "d"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "a;b;c;d"


def test_list_append_to_empty() -> None:
    """Test list(APPEND) to empty list."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="list", args=["APPEND", "MY_LIST", "a", "b"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "a;b"


def test_list_prepend() -> None:
    """Test list(PREPEND) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "c;d"
    commands = [Command(name="list", args=["PREPEND", "MY_LIST", "a", "b"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "a;b;c;d"


def test_list_insert() -> None:
    """Test list(INSERT) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "a;b;d"
    commands = [Command(name="list", args=["INSERT", "MY_LIST", "2", "c"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "a;b;c;d"


def test_list_remove_item() -> None:
    """Test list(REMOVE_ITEM) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "a;b;c;b;d"
    commands = [Command(name="list", args=["REMOVE_ITEM", "MY_LIST", "b"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "a;c;d"


def test_list_remove_at() -> None:
    """Test list(REMOVE_AT) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "a;b;c;d"
    commands = [Command(name="list", args=["REMOVE_AT", "MY_LIST", "1", "2"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "a;d"


def test_list_remove_at_negative() -> None:
    """Test list(REMOVE_AT) with negative index."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "a;b;c;d"
    commands = [Command(name="list", args=["REMOVE_AT", "MY_LIST", "-1"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "a;b;c"


def test_list_remove_duplicates() -> None:
    """Test list(REMOVE_DUPLICATES) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "a;b;c;b;a;d"
    commands = [Command(name="list", args=["REMOVE_DUPLICATES", "MY_LIST"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "a;b;c;d"


def test_list_reverse() -> None:
    """Test list(REVERSE) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "a;b;c;d"
    commands = [Command(name="list", args=["REVERSE", "MY_LIST"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "d;c;b;a"


def test_list_sort() -> None:
    """Test list(SORT) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "d;b;a;c"
    commands = [Command(name="list", args=["SORT", "MY_LIST"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "a;b;c;d"


def test_list_find() -> None:
    """Test list(FIND) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "a;b;c;d"
    commands = [Command(name="list", args=["FIND", "MY_LIST", "c", "INDEX"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["INDEX"] == "2"


def test_list_find_not_found() -> None:
    """Test list(FIND) when element not found."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "a;b;c;d"
    commands = [Command(name="list", args=["FIND", "MY_LIST", "z", "INDEX"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["INDEX"] == "-1"


def test_list_join() -> None:
    """Test list(JOIN) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "a;b;c;d"
    commands = [Command(name="list", args=["JOIN", "MY_LIST", ", ", "RESULT"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "a, b, c, d"


def test_list_join_empty() -> None:
    """Test list(JOIN) on empty list."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="list", args=["JOIN", "MY_LIST", ", ", "RESULT"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == ""


def test_list_sublist() -> None:
    """Test list(SUBLIST) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "a;b;c;d;e"
    commands = [
        Command(name="list", args=["SUBLIST", "MY_LIST", "1", "3", "RESULT"], line=1)
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "b;c;d"


def test_list_sublist_negative_length() -> None:
    """Test list(SUBLIST) with negative length (all remaining)."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "a;b;c;d;e"
    commands = [
        Command(name="list", args=["SUBLIST", "MY_LIST", "2", "-1", "RESULT"], line=1)
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "c;d;e"


def test_list_transform_toupper() -> None:
    """Test list(TRANSFORM TOUPPER) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "hello;world"
    commands = [Command(name="list", args=["TRANSFORM", "MY_LIST", "TOUPPER"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "HELLO;WORLD"


def test_list_transform_tolower() -> None:
    """Test list(TRANSFORM TOLOWER) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "HELLO;WORLD"
    commands = [Command(name="list", args=["TRANSFORM", "MY_LIST", "TOLOWER"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "hello;world"


def test_list_transform_strip() -> None:
    """Test list(TRANSFORM STRIP) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = " hello ; world "
    commands = [Command(name="list", args=["TRANSFORM", "MY_LIST", "STRIP"], line=1)]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "hello;world"


def test_list_transform_output_variable() -> None:
    """Test list(TRANSFORM) with OUTPUT_VARIABLE."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "hello;world"
    commands = [
        Command(
            name="list",
            args=["TRANSFORM", "MY_LIST", "TOUPPER", "OUTPUT_VARIABLE", "RESULT"],
            line=1,
        )
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "HELLO;WORLD"
    assert ctx.variables["MY_LIST"] == "hello;world"  # Original unchanged


def test_list_transform_prepend() -> None:
    """Test list(TRANSFORM PREPEND) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "lapi.c;lauxlib.c"
    commands = [
        Command(
            name="list",
            args=["TRANSFORM", "MY_LIST", "PREPEND", "upstream/"],
            line=1,
        )
    ]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "upstream/lapi.c;upstream/lauxlib.c"


def test_list_transform_prepend_output_variable() -> None:
    """PREPEND with OUTPUT_VARIABLE should not modify original list."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "a.c;b.c"
    commands = [
        Command(
            name="list",
            args=[
                "TRANSFORM",
                "MY_LIST",
                "PREPEND",
                "src/",
                "OUTPUT_VARIABLE",
                "RESULT",
            ],
            line=1,
        )
    ]
    process_commands(commands, ctx)
    assert ctx.variables["RESULT"] == "src/a.c;src/b.c"
    assert ctx.variables["MY_LIST"] == "a.c;b.c"


def test_list_filter_include() -> None:
    """Test list(FILTER INCLUDE) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "hello;world;help;test"
    commands = [
        Command(
            name="list", args=["FILTER", "MY_LIST", "INCLUDE", "REGEX", "hel.*"], line=1
        )
    ]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "hello;help"


def test_list_filter_exclude() -> None:
    """Test list(FILTER EXCLUDE) command."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["MY_LIST"] = "hello;world;help;test"
    commands = [
        Command(
            name="list", args=["FILTER", "MY_LIST", "EXCLUDE", "REGEX", "hel.*"], line=1
        )
    ]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "world;test"


def test_list_multiple_operations() -> None:
    """Test multiple list operations in sequence."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="list", args=["APPEND", "MY_LIST", "c", "a", "b"], line=1),
        Command(name="list", args=["SORT", "MY_LIST"], line=2),
        Command(name="list", args=["LENGTH", "MY_LIST", "LEN"], line=3),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["MY_LIST"] == "a;b;c"
    assert ctx.variables["LEN"] == "3"
