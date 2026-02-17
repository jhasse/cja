"""Tests for configure_file command."""

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

    assert (binary_subdir / "nested" / "out.txt").read_text() == "value"


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
