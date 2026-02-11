"""Tests for add_test command."""

from pathlib import Path

from cja.generator import BuildContext, process_commands, generate_ninja
from cja.parser import Command


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
    assert "command = cd $builddir && $cmd" in ninja_content
    assert "pool = console" in ninja_content

    # Check for individual test build statements
    assert "build test_mytest: test_run" in ninja_content
    # It should have resolved 'myapp' to './myapp' (since we cd to $builddir)
    assert "./myapp --arg" in ninja_content
    assert (
        "implicit = $builddir/myapp" in ninja_content
        or "| $builddir/myapp" in ninja_content
    )

    assert "build test_simple_test: test_run" in ninja_content
    assert "echo hello" in ninja_content

    # Check for phony test target
    assert "build test: phony test_mytest test_simple_test" in ninja_content
