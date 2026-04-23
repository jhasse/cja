"""Tests for add_test command."""

from pathlib import Path
import platform

from cja.generator import BuildContext, process_commands, generate_ninja
from cja.parser import Command

EXE_EXT = ".exe" if platform.system() == "Windows" else ""


def test_add_test(tmp_path: Path) -> None:
    """Test that add_test correctly creates test targets in Ninja."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(name="add_executable", args=["myapp", "main.cpp"], line=1),
        Command(
            name="add_test",
            args=["NAME", "mytest", "COMMAND", "myapp", "--arg"],
            line=2,
        ),
        Command(name="add_test", args=["simple_test", "echo", "hello"], line=3),
    ]
    process_commands(commands, ctx)

    assert len(ctx.tests) == 2
    assert ctx.tests[0].name == "mytest"
    assert ctx.tests[0].command == ["myapp", "--arg"]
    assert ctx.tests[1].name == "simple_test"
    assert ctx.tests[1].command == ["echo", "hello"]

    # Test propagation to Ninja file
    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    ninja_content = ninja_path.read_text()

    # Check for test rule
    assert "rule test_run" in ninja_content
    assert "command = $cmd" in ninja_content
    assert "pool = console" in ninja_content

    # Check for individual test build statements
    assert "build test_mytest: test_run" in ninja_content
    # It should have resolved 'myapp' to './myapp' (since we cd to $builddir)
    assert f"./myapp{EXE_EXT} --arg" in ninja_content
    assert (
        f"implicit = $builddir/myapp{EXE_EXT}" in ninja_content
        or f"| $builddir/myapp{EXE_EXT}" in ninja_content
    )

    assert "build test_simple_test: test_run" in ninja_content
    assert "echo hello" in ninja_content

    # Check for phony test target
    assert "build test: phony test_mytest test_simple_test" in ninja_content


def test_add_test_working_directory(tmp_path: Path) -> None:
    """Test that add_test supports WORKING_DIRECTORY."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(name="add_executable", args=["myapp", "main.cpp"], line=1),
        Command(
            name="add_test",
            args=[
                "NAME",
                "mytest",
                "COMMAND",
                "myapp",
                "WORKING_DIRECTORY",
                "/tmp/testdir",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    assert len(ctx.tests) == 1
    assert ctx.tests[0].name == "mytest"
    assert ctx.tests[0].command == ["myapp"]
    assert ctx.tests[0].working_directory == "/tmp/testdir"

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    ninja_content = ninja_path.read_text()

    # Absolute path outside source dir: cd with full path
    assert "cd /tmp/testdir && $builddir/myapp" in ninja_content


def test_add_test_working_directory_source_dir(tmp_path: Path) -> None:
    """Test that WORKING_DIRECTORY equal to source dir omits cd."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(
            name="add_test",
            args=[
                "NAME",
                "mytest",
                "COMMAND",
                "echo",
                "hello",
                "WORKING_DIRECTORY",
                str(tmp_path),
            ],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    ninja_content = ninja_path.read_text()
    # No cd prefix when working directory is the source directory
    assert "cmd = echo hello\n" in ninja_content


def test_add_test_working_directory_subdir(tmp_path: Path) -> None:
    """Test that WORKING_DIRECTORY below source dir uses relative cd."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    subdir = tmp_path / "sub" / "dir"
    subdir.mkdir(parents=True)

    commands = [
        Command(
            name="add_test",
            args=[
                "NAME",
                "mytest",
                "COMMAND",
                "echo",
                "hello",
                "WORKING_DIRECTORY",
                str(subdir),
            ],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    ninja_content = ninja_path.read_text()
    # Should cd to relative path
    assert "cd sub/dir && echo hello" in ninja_content


def test_add_test_target_file_in_command(tmp_path: Path) -> None:
    """Test that $<TARGET_FILE:target> is resolved in test COMMAND."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(name="add_executable", args=["myapp", "main.cpp"], line=1),
        Command(
            name="add_test",
            args=[
                "NAME",
                "mytest",
                "COMMAND",
                "$<TARGET_FILE:myapp>",
                "--arg",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    ninja_content = ninja_path.read_text()

    assert "TARGET_FILE" not in ninja_content
    expected_path = str(tmp_path / "build" / f"myapp{EXE_EXT}")
    assert expected_path in ninja_content
    assert "--arg" in ninja_content
