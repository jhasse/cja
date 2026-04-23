"""Tests for add_custom_target support."""

from pathlib import Path

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_add_custom_target_minimal() -> None:
    """Test minimal add_custom_target with just a name."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="add_custom_target",
            args=["my_target"],
            line=1,
        ),
    ]

    process_commands(commands, ctx)

    assert len(ctx.custom_targets) == 1
    ct = ctx.custom_targets[0]
    assert ct.name == "my_target"
    assert ct.commands == []
    assert ct.depends == []
    assert ct.all is False


def test_add_custom_target_all() -> None:
    """Test add_custom_target with ALL keyword."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="add_custom_target",
            args=["my_target", "ALL"],
            line=1,
        ),
    ]

    process_commands(commands, ctx)

    assert len(ctx.custom_targets) == 1
    ct = ctx.custom_targets[0]
    assert ct.name == "my_target"
    assert ct.all is True


def test_add_custom_target_with_command() -> None:
    """Test add_custom_target with COMMAND."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="add_custom_target",
            args=[
                "generate",
                "COMMAND",
                "echo",
                "hello",
            ],
            line=1,
        ),
    ]

    process_commands(commands, ctx)

    assert len(ctx.custom_targets) == 1
    ct = ctx.custom_targets[0]
    assert ct.name == "generate"
    assert ct.commands == [["echo", "hello"]]


def test_add_custom_target_with_depends() -> None:
    """Test add_custom_target with DEPENDS."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="add_custom_target",
            args=[
                "my_target",
                "DEPENDS",
                "file1.txt",
                "file2.txt",
            ],
            line=1,
        ),
    ]

    process_commands(commands, ctx)

    assert len(ctx.custom_targets) == 1
    ct = ctx.custom_targets[0]
    assert ct.depends == ["file1.txt", "file2.txt"]


def test_add_custom_target_all_command_depends() -> None:
    """Test add_custom_target with ALL, COMMAND, and DEPENDS."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="add_custom_target",
            args=[
                "my_target",
                "ALL",
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

    ct = ctx.custom_targets[0]
    assert ct.name == "my_target"
    assert ct.all is True
    assert ct.commands == [["echo", "hello"]]
    assert ct.depends == ["input.txt"]


def test_add_custom_target_multiple_commands() -> None:
    """Test add_custom_target with multiple COMMAND sections."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="add_custom_target",
            args=[
                "my_target",
                "COMMAND",
                "echo",
                "first",
                "COMMAND",
                "echo",
                "second",
            ],
            line=1,
        ),
    ]

    process_commands(commands, ctx)

    ct = ctx.custom_targets[0]
    assert ct.commands == [["echo", "first"], ["echo", "second"]]


def test_add_custom_target_working_directory_verbatim() -> None:
    """Test add_custom_target with WORKING_DIRECTORY and VERBATIM."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(
            name="add_custom_target",
            args=[
                "my_target",
                "COMMAND",
                "echo",
                "hello",
                "WORKING_DIRECTORY",
                "subdir",
                "VERBATIM",
            ],
            line=1,
        ),
    ]

    process_commands(commands, ctx)

    ct = ctx.custom_targets[0]
    assert ct.working_directory == "subdir"
    assert ct.verbatim is True


def test_add_custom_target_integration(tmp_path: Path) -> None:
    """Integration test: verify custom target generates build.ninja correctly."""
    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """cmake_minimum_required(VERSION 3.10)
project(CustomTargetTest)

add_custom_target(
    run_script
    COMMAND echo "Running script"
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    assert ninja_file.exists()
    ninja_content = ninja_file.read_text()

    # Custom target should create a phony rule
    assert "build run_script: phony" in ninja_content


def test_add_custom_target_all_in_default(tmp_path: Path) -> None:
    """Test that ALL custom targets appear in default build."""
    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """cmake_minimum_required(VERSION 3.10)
project(CustomTargetAllTest)

add_custom_target(
    always_build ALL
    COMMAND echo "Always built"
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    ninja_content = ninja_file.read_text()

    # The custom target with ALL should be in the "all" phony target
    assert "build all: phony" in ninja_content
    assert "always_build" in ninja_content


def test_add_custom_target_depends_on_custom_command(tmp_path: Path) -> None:
    """Test custom target depending on custom command outputs."""
    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """cmake_minimum_required(VERSION 3.10)
project(DepTest)

add_custom_command(
    OUTPUT generated.txt
    COMMAND echo "hello" > generated.txt
)

add_custom_target(gen_target DEPENDS generated.txt)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    ninja_content = ninja_file.read_text()

    # The custom target should depend on the custom command output with $builddir prefix
    assert "build gen_target: phony $builddir/generated.txt" in ninja_content


def test_add_custom_target_target_file_dir_working_directory(tmp_path: Path) -> None:
    """Test that $<TARGET_FILE_DIR:target> is resolved in WORKING_DIRECTORY."""
    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """\
cmake_minimum_required(VERSION 3.10)
project(TargetFileDirTest)

add_executable(myapp main.c)

add_custom_target(
    run_in_output_dir
    COMMAND echo hello
    WORKING_DIRECTORY $<TARGET_FILE_DIR:myapp>
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)
    (source_dir / "main.c").write_text("int main() { return 0; }\n")

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    ninja_content = ninja_file.read_text()

    assert "cd $builddir && echo hello" in ninja_content


def test_add_custom_target_target_file_in_command(tmp_path: Path) -> None:
    """Test that $<TARGET_FILE:target> is resolved in COMMAND arguments."""
    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """\
cmake_minimum_required(VERSION 3.10)
project(TargetFileTest)

add_executable(myapp main.c)

add_custom_target(
    run_app
    COMMAND $<TARGET_FILE:myapp> --flag
    VERBATIM
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)
    (source_dir / "main.c").write_text("int main() { return 0; }\n")

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    ninja_content = ninja_file.read_text()

    assert "$builddir/myapp" in ninja_content
    assert "TARGET_FILE" not in ninja_content
