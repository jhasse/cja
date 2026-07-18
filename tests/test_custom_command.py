"""Tests for add_custom_command support."""

import platform
from pathlib import Path

from cja.generator import BuildContext, process_commands
from cja.parser import Command

EXE_EXT = ".exe" if platform.system() == "Windows" else ""


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
    assert custom.outputs == ["generated.txt"]
    assert custom.commands == [["echo", "hello"]]
    assert custom.depends == ["input.txt"]


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
    assert custom.outputs == ["out1.txt", "out2.txt"]
    assert custom.commands == [["python", "-c", "print('hi')"]]
    assert custom.depends == ["input1.txt", "input2.txt"]


def test_add_custom_command_integration() -> None:
    """Integration test: verify custom command generates build.ninja correctly."""
    import tempfile
    from cja.generator import configure

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
    from cja.generator import configure

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


def test_add_custom_command_main_dependency(tmp_path: Path) -> None:
    """Test that MAIN_DEPENDENCY is correctly handled."""
    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """cmake_minimum_required(VERSION 3.10)
project(MainDepTest)

add_custom_command(
    OUTPUT out.txt
    COMMAND cat in.txt > out.txt
    MAIN_DEPENDENCY in.txt
    DEPENDS extra.txt
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)
    (source_dir / "in.txt").write_text("in")
    (source_dir / "extra.txt").write_text("extra")

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    ninja_content = ninja_file.read_text()

    # in.txt should be the first dependency
    assert "build $builddir/out.txt: custom_command in.txt extra.txt" in ninja_content


def test_add_custom_command_absolute_output(tmp_path: Path) -> None:
    """Test that absolute paths in OUTPUT are converted to relative."""
    from cja.generator import configure

    source_dir = tmp_path
    build_dir = tmp_path / "build"
    build_dir.mkdir()

    output_file = build_dir / "generated.txt"

    cmake_content = f"""cmake_minimum_required(VERSION 3.10)
project(AbsOutTest)

add_custom_command(
    OUTPUT {output_file}
    COMMAND echo "hello" > {output_file}
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    ninja_content = ninja_file.read_text()

    # It should be prefixed with $builddir/ and the filename
    assert "$builddir/generated.txt" in ninja_content
    # And NOT the absolute path in the build statement
    assert f"build {output_file}" not in ninja_content


def test_add_custom_command_working_dir_verbatim(tmp_path: Path) -> None:
    """Test that WORKING_DIRECTORY and VERBATIM are correctly handled."""
    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """cmake_minimum_required(VERSION 3.10)
project(WorkDirTest)

add_custom_command(
    OUTPUT out.txt
    COMMAND echo "hello world"
    WORKING_DIRECTORY scripts
    VERBATIM
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)
    (source_dir / "scripts").mkdir()

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    ninja_content = ninja_file.read_text()

    # The command should have 'cd scripts &&' and 'hello world' should be quoted if VERBATIM worked
    # shlex.join(["echo", "hello world"]) -> 'echo "hello world"' or 'echo 'hello world''
    assert (
        "cmd = cd scripts && echo 'hello world'" in ninja_content
        or 'cmd = cd scripts && echo "hello world"' in ninja_content
    )


def test_add_custom_command_multiple_commands(tmp_path: Path) -> None:
    """Test that multiple COMMAND sections are correctly joined with &&."""
    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """cmake_minimum_required(VERSION 3.10)
project(MultiCmdTest)

add_custom_command(
    OUTPUT out.txt
    COMMAND echo "first" > out.txt
    COMMAND echo "second" >> out.txt
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    ninja_content = ninja_file.read_text()

    assert "cmd = echo first > out.txt && echo second >> out.txt" in ninja_content


def test_add_custom_command_target_file_dir_working_directory(tmp_path: Path) -> None:
    """Test that $<TARGET_FILE_DIR:target> is resolved in WORKING_DIRECTORY."""
    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """\
cmake_minimum_required(VERSION 3.10)
project(TargetFileDirTest)

add_executable(myapp main.c)

add_custom_command(
    OUTPUT out.txt
    COMMAND echo hello
    WORKING_DIRECTORY $<TARGET_FILE_DIR:myapp>
    VERBATIM
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)
    (source_dir / "main.c").write_text("int main() { return 0; }\n")

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    ninja_content = ninja_file.read_text()

    assert "cd $builddir && echo" in ninja_content


def test_add_custom_command_target_file_in_command(tmp_path: Path) -> None:
    """Test that $<TARGET_FILE:target> is resolved in COMMAND arguments."""
    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """\
cmake_minimum_required(VERSION 3.10)
project(TargetFileTest)

add_executable(myapp main.c)

add_custom_command(
    OUTPUT out.txt
    COMMAND $<TARGET_FILE:myapp> --generate out.txt
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


def test_add_custom_command_target_post_build(tmp_path: Path) -> None:
    """Test add_custom_command(TARGET ... POST_BUILD COMMAND ...) support."""
    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """\
cmake_minimum_required(VERSION 3.10)
project(PostBuildTest)

add_executable(videoplayer main.c)

add_custom_command(TARGET videoplayer POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy ${PROJECT_SOURCE_DIR}/data/verysmall.ogv
            $<TARGET_FILE_DIR:videoplayer>
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)
    (source_dir / "main.c").write_text("int main() { return 0; }\n")
    (source_dir / "data").mkdir()
    (source_dir / "data" / "verysmall.ogv").write_text("")

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    assert ninja_file.exists()
    ninja_content = ninja_file.read_text()

    # A stamp file for post_build should be generated
    assert "videoplayer.post_build" in ninja_content
    # The copy command should appear
    assert "-E" in ninja_content
    assert "copy" in ninja_content
    assert "verysmall.ogv" in ninja_content


def test_add_custom_command_output_strips_generator_expressions(
    tmp_path: Path,
) -> None:
    """Generator expressions in OUTPUT must be evaluated rather than emitted
    verbatim, which would produce an invalid $-escape in build.ninja."""
    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """\
cmake_minimum_required(VERSION 3.10)
project(GenexOutputTest)

add_custom_command(
    OUTPUT out$<$<BOOL:0>:_dbg>.txt
    COMMAND echo hi
)
add_custom_target(gen ALL DEPENDS out$<$<BOOL:0>:_dbg>.txt)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)

    configure(source_dir, "build")

    ninja_content = (source_dir / "build.ninja").read_text()
    assert "build $builddir/out.txt: custom_command" in ninja_content
    assert "$<" not in ninja_content


def test_add_custom_command_source_dependency_no_cycle(tmp_path: Path) -> None:
    """A relative DEPENDS that names an existing source file must resolve to the
    source (no $builddir prefix), even when an output shares that name, so we
    don't create a self-dependency cycle."""
    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """\
cmake_minimum_required(VERSION 3.10)
project(CopyCycleTest)

add_custom_command(
    OUTPUT data.bin
    COMMAND ${CMAKE_COMMAND} -E copy ${CMAKE_CURRENT_SOURCE_DIR}/data.bin data.bin
    DEPENDS data.bin
)
add_custom_target(copydata ALL DEPENDS data.bin)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)
    (source_dir / "data.bin").write_text("payload")

    configure(source_dir, "build")

    ninja_content = (source_dir / "build.ninja").read_text()
    # Output is in $builddir, but the source dependency stays unprefixed so the
    # build edge does not depend on itself.
    assert "build $builddir/data.bin: custom_command data.bin" in ninja_content
    assert "custom_command $builddir/data.bin" not in ninja_content


def test_add_custom_command_target_post_build_depends_on_exe(tmp_path: Path) -> None:
    """Post_build stamp should depend on the executable."""
    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """\
cmake_minimum_required(VERSION 3.10)
project(PostBuildDepTest)

add_executable(myapp main.c)

add_custom_command(TARGET myapp POST_BUILD COMMAND echo done)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)
    (source_dir / "main.c").write_text("int main() { return 0; }\n")

    configure(source_dir, "build")

    ninja_content = (source_dir / "build.ninja").read_text()

    # Stamp depends on the executable
    assert "myapp.post_build" in ninja_content
    # The executable itself should appear as a dependency of the stamp
    assert "$builddir/myapp" in ninja_content


def test_add_custom_command_comment_not_in_depends(tmp_path: Path) -> None:
    """COMMENT keyword and its value must not appear as dependencies."""
    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """\
cmake_minimum_required(VERSION 3.10)
project(CommentTest)

add_custom_command(
    OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/out.txt
    COMMAND echo hello
    DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/input.txt
    COMMENT "Generating out.txt"
    VERBATIM
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)
    (source_dir / "input.txt").write_text("")

    configure(source_dir, "build")

    ninja_content = (source_dir / "build.ninja").read_text()

    assert "COMMENT" not in ninja_content
    assert "Generating" not in ninja_content
    assert "input.txt" in ninja_content


def test_add_custom_command_depends_on_executable_target(tmp_path: Path) -> None:
    """DEPENDS on an executable target name resolves to the built binary."""
    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """\
cmake_minimum_required(VERSION 3.10)
project(TargetDepTest)

add_executable(tool tool.c)

add_custom_command(
    OUTPUT generated.txt
    COMMAND tool ARGS --write generated.txt
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    DEPENDS tool
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)
    (source_dir / "tool.c").write_text("int main() { return 0; }\n")

    configure(source_dir, "build")

    ninja_content = (source_dir / "build.ninja").read_text()

    # DEPENDS should reference the build output, not a source-relative path.
    assert (
        f"build $builddir/generated.txt: custom_command $builddir/tool{EXE_EXT}"
        in ninja_content
    )
    # ARGS must not appear in the shell command.
    assert " ARGS " not in ninja_content
    # COMMAND tool is substituted with an absolute path to the built binary.
    expected_tool = (tmp_path / "build" / f"tool{EXE_EXT}").as_posix()
    assert expected_tool in ninja_content
    assert "&& tool --write" not in ninja_content
