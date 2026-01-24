"""Tests for add_custom_command support."""

from pathlib import Path

from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


def test_add_custom_command_minimal() -> None:
    """Test minimal add_custom_command parsing for OUTPUT/COMMAND/DEPENDS."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="add_custom_command",
            args=[
                "OUTPUT",
                "generated.txt",
                "COMMAND",
                "echo",
                "hello",
                "DEPENDS",
                "input.txt",
            ],
            line=1,
        ),
    ]

    process_commands(commands, ctx)

    assert len(ctx.custom_commands) == 1
    custom = ctx.custom_commands[0]
    assert custom["outputs"] == ["generated.txt"]
    assert custom["command"] == ["echo", "hello"]
    assert custom["depends"] == ["input.txt"]


def test_add_custom_command_multiple_outputs() -> None:
    """Test parsing multiple outputs and dependencies."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="add_custom_command",
            args=[
                "OUTPUT",
                "out1.txt",
                "out2.txt",
                "COMMAND",
                "python",
                "-c",
                "print('hi')",
                "DEPENDS",
                "input1.txt",
                "input2.txt",
            ],
            line=1,
        ),
    ]

    process_commands(commands, ctx)

    assert len(ctx.custom_commands) == 1
    custom = ctx.custom_commands[0]
    assert custom["outputs"] == ["out1.txt", "out2.txt"]
    assert custom["command"] == ["python", "-c", "print('hi')"]
    assert custom["depends"] == ["input1.txt", "input2.txt"]


def test_add_custom_command_integration() -> None:
    """Integration test: verify custom command generates build.ninja correctly."""
    import tempfile
    import shutil
    from cninja.generator import configure

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        # Create CMakeLists.txt with custom command
        cmake_content = """cmake_minimum_required(VERSION 3.10)
project(CustomCommandTest)

add_custom_command(
    OUTPUT generated.txt
    COMMAND echo "Hello from custom command" > generated.txt
    DEPENDS input.txt
)
"""
        (tmppath / "CMakeLists.txt").write_text(cmake_content)
        (tmppath / "input.txt").write_text("input")

        # Configure
        configure(tmppath, "build")

        # Verify build.ninja was generated
        ninja_file = tmppath / "build.ninja"
        assert ninja_file.exists()

        # Check that custom command is in the ninja file
        ninja_content = ninja_file.read_text()
        assert "rule custom_command" in ninja_content
        assert "$builddir/generated.txt" in ninja_content
        assert "echo Hello from custom command > generated.txt" in ninja_content
        assert "input.txt" in ninja_content


def test_add_custom_command_dependency(tmp_path: Path) -> None:
    """Test that a target depending on custom command output uses builddir."""
    from cninja.generator import configure

    source_dir = tmp_path
    cmake_content = """cmake_minimum_required(VERSION 3.10)
project(DepTest)

add_custom_command(
    OUTPUT generated.cpp
    COMMAND echo "int main() { return 0; }" > generated.cpp
    DEPENDS input.txt
)

add_executable(myapp generated.cpp)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)
    (source_dir / "input.txt").write_text("input")

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    assert ninja_file.exists()
    ninja_content = ninja_file.read_text()

    # The custom command output should be prefixed
    assert "build $builddir/generated.cpp: custom_command input.txt" in ninja_content
    # The executable should depend on the prefixed source
    assert (
        "build $builddir/myapp_generated.o: cxx $builddir/generated.cpp"
        in ninja_content
    )
