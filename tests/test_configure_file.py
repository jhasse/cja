"""Tests for configure_file command."""

import os
from pathlib import Path

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_configure_file_substitutes_vars(tmp_path: Path) -> None:
    """configure_file should replace ${VAR} and @VAR@."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "config.in").write_text("A=${FOO}\nB=@BAR@\n")

    ctx = BuildContext(source_dir=src_dir, build_dir=tmp_path / "build")
    ctx.variables["FOO"] = "hello"
    ctx.variables["BAR"] = "world"
    commands = [Command(name="configure_file", args=["config.in", "config.out"], line=1)]

    process_commands(commands, ctx)

    out = (tmp_path / "build" / "config.out").read_text()
    assert out == "A=hello\nB=world\n"


def test_configure_file_at_only(tmp_path: Path) -> None:
    """configure_file(@ONLY) should only replace @VAR@."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "config.in").write_text("A=${FOO}\nB=@BAR@\n")

    ctx = BuildContext(source_dir=src_dir, build_dir=tmp_path / "build")
    ctx.variables["FOO"] = "hello"
    ctx.variables["BAR"] = "world"
    commands = [
        Command(
            name="configure_file",
            args=["config.in", "config.out", "@ONLY"],
            line=1,
        )
    ]

    process_commands(commands, ctx)

    out = (tmp_path / "build" / "config.out").read_text()
    assert out == "A=${FOO}\nB=world\n"


def test_configure_file_copyonly(tmp_path: Path) -> None:
    """configure_file(COPYONLY) should copy content unchanged."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    original = "A=${FOO}\nB=@BAR@\n"
    (src_dir / "config.in").write_text(original)

    ctx = BuildContext(source_dir=src_dir, build_dir=tmp_path / "build")
    ctx.variables["FOO"] = "hello"
    ctx.variables["BAR"] = "world"
    commands = [
        Command(
            name="configure_file",
            args=["config.in", "config.out", "COPYONLY"],
            line=1,
        )
    ]

    process_commands(commands, ctx)

    out = (tmp_path / "build" / "config.out").read_text()
    assert out == original


def test_configure_file_uses_current_binary_dir(tmp_path: Path) -> None:
    """Relative output path should be resolved against CMAKE_CURRENT_BINARY_DIR."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "config.in").write_text("value")
    binary_subdir = tmp_path / "build" / "subdir"

    ctx = BuildContext(source_dir=src_dir, build_dir=tmp_path / "build")
    ctx.variables["CMAKE_CURRENT_BINARY_DIR"] = str(binary_subdir)
    commands = [Command(name="configure_file", args=["config.in", "nested/out.txt"], line=1)]

    process_commands(commands, ctx)

    assert (binary_subdir / "nested" / "out.txt").read_text() == "value\n"


def test_configure_file_cmakedefine(tmp_path: Path) -> None:
    """configure_file should handle #cmakedefine for true/false values."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "config.h.in").write_text(
        "#cmakedefine ENABLE_FOO\n"
        "#cmakedefine ENABLE_BAR @BAR_VALUE@\n"
        "#cmakedefine ENABLE_BAZ ${BAZ_VALUE}\n"
    )

    ctx = BuildContext(source_dir=src_dir, build_dir=tmp_path / "build")
    ctx.variables["ENABLE_FOO"] = "ON"
    ctx.variables["ENABLE_BAR"] = "OFF"
    ctx.variables["ENABLE_BAZ"] = "1"
    ctx.variables["BAR_VALUE"] = "42"
    ctx.variables["BAZ_VALUE"] = "24"
    commands = [
        Command(name="configure_file", args=["config.h.in", "config.h"], line=1),
    ]

    process_commands(commands, ctx)

    out = (tmp_path / "build" / "config.h").read_text()
    assert "#define ENABLE_FOO" in out
    assert "/* #undef ENABLE_BAR */" in out
    assert "#define ENABLE_BAZ 24" in out


def test_configure_file_cmakedefine01(tmp_path: Path) -> None:
    """configure_file should handle #cmakedefine01 for true/false values."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "config.h.in").write_text(
        "#cmakedefine01 HAVE_A\n"
        "#cmakedefine01 HAVE_B\n"
    )

    ctx = BuildContext(source_dir=src_dir, build_dir=tmp_path / "build")
    ctx.variables["HAVE_A"] = "YES"
    ctx.variables["HAVE_B"] = "0"
    commands = [
        Command(name="configure_file", args=["config.h.in", "config.h"], line=1),
    ]

    process_commands(commands, ctx)

    out = (tmp_path / "build" / "config.h").read_text()
    assert "#define HAVE_A 1" in out
    assert "#define HAVE_B 0" in out


def test_configure_file_undefined_vars_warn_in_strict(
    tmp_path: Path,
    capsys,
) -> None:
    """Undefined vars in template content should warn, not fail, in strict mode."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "config.in").write_text("A=@MISSING_A@\nB=${MISSING_B}\n")

    ctx = BuildContext(source_dir=src_dir, build_dir=tmp_path / "build")
    commands = [Command(name="configure_file", args=["config.in", "config.out"], line=1)]

    process_commands(commands, ctx, strict=True)

    out = (tmp_path / "build" / "config.out").read_text()
    assert out == "A=\nB=\n"

    captured = capsys.readouterr()
    assert "warning:" in captured.err
    assert "undefined variable referenced: MISSING_A" in captured.err
    assert "undefined variable referenced: MISSING_B" in captured.err


def test_configure_file_keeps_mtime_when_unchanged(tmp_path: Path) -> None:
    """configure_file should only rewrite the output when its content changes."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "config.in").write_text("A=${FOO}\r\nB=2\r\n")
    out = tmp_path / "build" / "config.out"
    commands = [Command(name="configure_file", args=["config.in", "config.out"], line=1)]

    def configure(foo: str) -> None:
        ctx = BuildContext(source_dir=src_dir, build_dir=tmp_path / "build")
        ctx.variables["FOO"] = foo
        process_commands(commands, ctx)

    configure("hello")
    os.utime(out, ns=(0, 0))

    configure("hello")
    assert out.stat().st_mtime_ns == 0

    configure("world")
    assert out.stat().st_mtime_ns != 0
    assert out.read_bytes().startswith(b"A=world")


def test_configure_file_like_cmake(tmp_path: Path) -> None:
    """The expected output is CMake 4.3's: ESCAPE_QUOTES only escapes the values,
    #cmakedefine may be anywhere in a line and @VAR@ values aren't expanded again.
    """
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "config.in").write_text(
        '@A@ ${A} "lit" \\${A}\n'
        "  #cmakedefine01 ON_VAR trailing\n"
        "  #cmakedefine OFF_VAR trailing\n"
        "x #  cmakedefine ON_VAR y\n"
        "#cmakedefine TEXT_VAR\n"
        "@REF@ @a.b/c+d@\n"
    )

    ctx = BuildContext(source_dir=src_dir, build_dir=tmp_path / "build")
    ctx.variables["A"] = 'x"y'
    ctx.variables["ON_VAR"] = "ON"
    ctx.variables["OFF_VAR"] = "OFF"
    ctx.variables["TEXT_VAR"] = "text"
    ctx.variables["REF"] = "${ON_VAR}"
    commands = [
        Command(
            name="configure_file",
            args=["config.in", "config.out", "ESCAPE_QUOTES"],
            line=1,
        )
    ]

    process_commands(commands, ctx)

    out = (tmp_path / "build" / "config.out").read_text()
    assert out == (
        'x\\"y x\\"y "lit" \\x\\"y\n'
        "  #define ON_VAR trailing 1\n"
        "/* #undef OFF_VAR */\n"
        "x #  define ON_VAR y\n"
        "#define TEXT_VAR\n"
        "${ON_VAR} \n"
    )


def test_configure_file_newlines(tmp_path: Path) -> None:
    """Like CMake, end the last line, but copy COPYONLY files as they are."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "empty.in").write_bytes(b"")
    (src_dir / "crlf.in").write_bytes(b"a\r\n@B@")

    ctx = BuildContext(source_dir=src_dir, build_dir=tmp_path / "build")
    ctx.variables["B"] = "b"
    commands = [
        Command(name="configure_file", args=["empty.in", "empty.out"], line=1),
        Command(name="configure_file", args=["crlf.in", "crlf.out"], line=2),
        Command(
            name="configure_file", args=["crlf.in", "copy.out", "COPYONLY"], line=3
        ),
    ]

    process_commands(commands, ctx)

    build_dir = tmp_path / "build"
    assert (build_dir / "empty.out").read_bytes() == b""
    assert (build_dir / "crlf.out").read_text() == "a\nb\n"
    assert (build_dir / "copy.out").read_bytes() == b"a\r\n@B@"
