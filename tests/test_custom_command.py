"""Tests for add_custom_command support."""

import platform
import re
from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command
from tests.helpers import cd_command, join_command_lines

EXE_EXT = ".exe" if platform.system() == "Windows" else ""
LIB_EXT = ".lib" if platform.system() == "Windows" else ".a"


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
        # Like in CMake, the spaces are escaped also without VERBATIM
        if platform.system() == "Windows":
            message = '"Hello from custom command"'
        else:
            message = r"Hello\ from\ custom\ command"
        assert f"echo {message} > generated.txt" in ninja_content
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

    # The command should cd to scripts in the binary directory, like in CMake,
    # and 'hello world' should be quoted if VERBATIM worked
    # shlex.join(["echo", "hello world"]) -> 'echo "hello world"' or 'echo 'hello world''
    cd = cd_command("build/scripts")
    assert any(
        f"cmd = {join_command_lines(cd, f'echo {q}hello world{q}')}" in ninja_content
        for q in "'\""
    )


def test_add_custom_command_working_dir_under_source_is_relative(
    tmp_path: Path,
) -> None:
    """Absolute WORKING_DIRECTORY under the source tree becomes a relative cd."""
    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """\
cmake_minimum_required(VERSION 3.10)
project(WorkDirRelTest)

add_custom_command(
    OUTPUT out.txt
    COMMAND echo hello
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}/generated
    VERBATIM
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)

    configure(source_dir, "build")

    ninja_content = (source_dir / "build.ninja").read_text()
    assert f"{cd_command('build/generated')} && echo hello" in ninja_content
    assert f"{cd_command(source_dir.as_posix())}/build/generated" not in ninja_content


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

    expected = join_command_lines(
        cd_command("build"), "echo first > out.txt", "echo second >> out.txt"
    )
    assert f"cmd = {expected}" in ninja_content


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

    assert f"{cd_command('$builddir')} && echo" in ninja_content


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


def test_add_custom_command_target_post_build_cmake_command_with_spaces(
    tmp_path: Path,
) -> None:
    """CMAKE_COMMAND containing spaces (e.g. 'python3 -m cja') must not be quoted
    as a single shell token in POST_BUILD commands."""
    from unittest.mock import patch

    import cja.generator
    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """\
cmake_minimum_required(VERSION 3.10)
project(PostBuildSpacesTest)

add_executable(audioplayer main.c)

add_custom_command(TARGET audioplayer POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy ${PROJECT_SOURCE_DIR}/data/test.ogg build
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)
    (source_dir / "main.c").write_text("int main() { return 0; }\n")
    (source_dir / "data").mkdir()
    (source_dir / "data" / "test.ogg").write_text("")

    # Patch _resolve_cja_cmd to return a multi-word command (simulating a venv
    # where cja is not on PATH and must be invoked as "python3 -m cja").
    with patch.object(cja.generator, "_resolve_cja_cmd", return_value=["/fake/python3", "-m", "cja"]):
        configure(source_dir, "build")

    ninja_content = (source_dir / "build.ninja").read_text()

    # The multi-word command must be split into individually-quoted tokens, not
    # wrapped as one quoted string that the shell cannot find as a file.
    assert "'/fake/python3 -m cja'" not in ninja_content
    assert "/fake/python3" in ninja_content
    assert "-m" in ninja_content


def test_post_build_cmake_command_path_with_spaces(tmp_path: Path) -> None:
    """A cja path containing spaces must stay one token in POST_BUILD and
    reconfigure commands rather than being split at the space."""
    from unittest.mock import patch

    import cja.generator
    from cja.generator import _quote_ninja_cmd_part, configure

    source_dir = tmp_path
    cmake_content = """\
cmake_minimum_required(VERSION 3.10)
project(PostBuildPathSpacesTest)

add_executable(myapp main.c)

add_custom_command(TARGET myapp POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E echo done
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)
    (source_dir / "main.c").write_text("int main() { return 0; }\n")

    cja_path = "/fake dir/My Tools/cja"
    with patch.object(cja.generator, "_resolve_cja_cmd", return_value=[cja_path]):
        configure(source_dir, "build")

    # Unwrap ninja "$" line continuations (and their indent) so the full cmd
    # is searchable.
    unwrapped = re.sub(r"\$\n\s*", "", (source_dir / "build.ninja").read_text())
    edge = unwrapped.find("CMakeFiles/myapp.post_build: custom_command")
    assert edge != -1
    cmd_start = unwrapped.find("cmd =", edge)
    cmd = unwrapped[cmd_start : unwrapped.find("\n", cmd_start)]

    quoted = _quote_ninja_cmd_part(cja_path)
    assert f"{quoted} -E echo done" in cmd
    assert f"{quoted} -E touch" in cmd
    assert "/fake " not in cmd.replace(quoted, "")

    reconfigure = unwrapped[unwrapped.find("rule reconfigure") :]
    reconfigure = reconfigure[: reconfigure.find("\n", reconfigure.find("command ="))]
    assert f"{quoted} --regenerate-during-build" in reconfigure


@pytest.mark.parametrize("verbatim", [True, False])
@pytest.mark.parametrize(
    "cja_cmd",
    [["/fake dir/My Tools/cja"], ["/fake/python3", "-m", "cja"]],
    ids=["path-with-spaces", "multi-word"],
)
def test_add_custom_command_cmake_command_argv(
    tmp_path: Path, cja_cmd: list[str], verbatim: bool
) -> None:
    """${CMAKE_COMMAND} in OUTPUT and custom target commands must expand to
    the individually quoted cja argv, with or without VERBATIM."""
    from unittest.mock import patch

    import cja.generator
    from cja.generator import _quote_ninja_cmd_part, configure

    verbatim_kw = "VERBATIM" if verbatim else ""
    source_dir = tmp_path
    cmake_content = f"""\
cmake_minimum_required(VERSION 3.10)
project(CustomCommandArgvTest)

add_custom_command(
    OUTPUT out.txt
    COMMAND ${{CMAKE_COMMAND}} -E touch out.txt
    {verbatim_kw}
)
add_custom_target(gen ALL
    COMMAND ${{CMAKE_COMMAND}} -E echo hi
    DEPENDS out.txt
    {verbatim_kw}
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)

    with patch.object(cja.generator, "_resolve_cja_cmd", return_value=cja_cmd):
        configure(source_dir, "build")

    unwrapped = re.sub(r"\$\n\s*", "", (source_dir / "build.ninja").read_text())
    quoted = " ".join(_quote_ninja_cmd_part(p) for p in cja_cmd)
    assert f"{quoted} -E touch out.txt" in unwrapped
    assert f"{quoted} -E echo hi" in unwrapped
    if len(cja_cmd) > 1:
        assert _quote_ninja_cmd_part(" ".join(cja_cmd)) not in unwrapped


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


def test_post_build_target_file_is_absolute(tmp_path: Path) -> None:
    """Like in other custom commands, $<TARGET_FILE:...> is absolute in
    POST_BUILD, so it stays valid when used in another working directory."""
    from cja.generator import configure

    (tmp_path / "CMakeLists.txt").write_text(
        """\
cmake_minimum_required(VERSION 3.10)
project(PostBuildTargetFile)
add_executable(myapp main.c)
add_custom_command(TARGET myapp POST_BUILD COMMAND echo $<TARGET_FILE:myapp>)
"""
    )
    (tmp_path / "main.c").write_text("int main() { return 0; }\n")

    configure(tmp_path, "build")

    unwrapped = re.sub(r"\$\n *", "", (tmp_path / "build.ninja").read_text())
    exe = (tmp_path / "build" / f"myapp{EXE_EXT}").as_posix()
    assert f"echo {exe}" in unwrapped


def test_post_build_windows_paths_not_single_quoted(tmp_path: Path) -> None:
    """POST_BUILD must use Windows-aware quoting, not shlex single quotes.

    Ninja runs commands via cmd.exe on Windows, which ignores single quotes.
    Paths with backslashes must be forward-slash normalized instead.
    """
    if platform.system() != "Windows":
        pytest.skip("Windows-specific quoting behavior")

    from cja.generator import configure

    source_dir = tmp_path
    cmake_content = """\
cmake_minimum_required(VERSION 3.10)
project(PostBuildQuoteTest)

add_executable(myapp main.c)

add_custom_command(TARGET myapp POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy ${PROJECT_SOURCE_DIR}/data/asset.txt
            $<TARGET_FILE_DIR:myapp>
)
"""
    (source_dir / "CMakeLists.txt").write_text(cmake_content)
    (source_dir / "main.c").write_text("int main() { return 0; }\n")
    (source_dir / "data").mkdir()
    (source_dir / "data" / "asset.txt").write_text("")

    configure(source_dir, "build")

    # Unwrap ninja "$" line continuations so the full cmd is searchable.
    unwrapped = re.sub(r"\$\n *", "", (source_dir / "build.ninja").read_text())
    edge = unwrapped.find("CMakeFiles/myapp.post_build: custom_command")
    assert edge != -1
    cmd_start = unwrapped.find("cmd =", edge)
    assert cmd_start != -1
    cmd = unwrapped[cmd_start : unwrapped.find("\n", cmd_start)]

    # Ninja runs commands without a shell, so && needs cmd.exe
    assert cmd.startswith('cmd = cmd.exe /C "') and cmd.endswith('"')
    assert "-E touch" in cmd
    assert "CMakeFiles/myapp.post_build" in cmd
    assert "data/asset.txt" in cmd
    assert "'" not in cmd, f"shlex single quotes break cmd.exe: {cmd}"
    assert "\\" not in cmd, f"backslash paths break cmd.exe: {cmd}"


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


def test_add_custom_command_uses_terminal(tmp_path: Path) -> None:
    """USES_TERMINAL runs the command in ninja's console pool."""
    from cja.generator import configure

    (tmp_path / "CMakeLists.txt").write_text("""\
cmake_minimum_required(VERSION 3.10)
project(UsesTerminalTest)

add_custom_command(
    OUTPUT interactive.txt
    COMMAND echo interactive > interactive.txt
    USES_TERMINAL
    DEPENDS input.txt
)

add_custom_command(
    OUTPUT plain.txt
    COMMAND echo plain > plain.txt
)
""")
    (tmp_path / "input.txt").write_text("")

    configure(tmp_path, "build")

    ninja_content = (tmp_path / "build.ninja").read_text()

    assert (
        "build $builddir/interactive.txt: custom_command input.txt\n"
        "  pool = console\n"
    ) in ninja_content
    assert "build $builddir/plain.txt: custom_command\n  cmd =" in ninja_content


def test_add_custom_command_depends_on_file_in_build_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dependency already in the build directory, like SDL's Wayland protocol
    XMLs in its CPM sources under _deps/, is a $builddir path for ninja."""
    from cja.generator import configure

    cmake_content = """cmake_minimum_required(VERSION 3.10)
project(DepTest)

file(WRITE "${CMAKE_BINARY_DIR}/_deps/dep-src/protocol.xml" "<protocol/>")
add_custom_command(
    OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/protocol.h"
    DEPENDS "${CMAKE_BINARY_DIR}/_deps/dep-src/protocol.xml"
    COMMAND cp "${CMAKE_BINARY_DIR}/_deps/dep-src/protocol.xml" protocol.h
)
add_custom_target(gen ALL DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/protocol.h")
"""
    (tmp_path / "CMakeLists.txt").write_text(cmake_content)
    monkeypatch.chdir(tmp_path)

    configure(tmp_path, "build")

    ninja_content = re.sub(r" \$\n\s*", " ", (tmp_path / "build.ninja").read_text())
    assert (
        "build $builddir/protocol.h: custom_command $builddir/_deps/dep-src/protocol.xml"
        in ninja_content
    )


@pytest.mark.parametrize("system", ["Linux", "Windows"])
def test_custom_command_lines_run_without_shell_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, system: str
) -> None:
    """Ninja uses CreateProcess on Windows, so cd and && need cmd.exe like in CMake."""
    from cja import generator

    monkeypatch.setattr(generator.platform, "system", lambda: system)

    if system == "Windows":
        cd = generator._cd_command(str(tmp_path / "build" / "gen dir"), tmp_path)
        assert cd == 'cd /D "build/gen dir"'
        assert generator._join_command_lines([cd, "python gen.py"]) == (
            'cmd.exe /C "cd /D "build/gen dir" && python gen.py"'
        )
    else:
        cd = generator._cd_command(str(tmp_path / "build" / "gen"), tmp_path)
        assert cd == "cd build/gen"
        assert generator._join_command_lines([cd, "python gen.py"]) == (
            "cd build/gen && python gen.py"
        )
    assert generator._join_command_lines(["python gen.py"]) == "python gen.py"
    assert generator._cd_command(str(tmp_path), tmp_path) is None


def test_custom_command_target_property_genex(tmp_path: Path) -> None:
    """$<TARGET_PROPERTY:...> is evaluated in the command lines and
    dependencies of custom commands and targets."""
    from cja.generator import configure

    (tmp_path / "CMakeLists.txt").write_text("""\
cmake_minimum_required(VERSION 3.10)
project(TargetPropertyGenexTest C)

add_custom_target(docs)
set_property(TARGET docs PROPERTY FILES a.md b.md)
add_custom_command(
    OUTPUT out.txt
    COMMAND tool --type=$<TARGET_PROPERTY:docs,TYPE> --files=$<TARGET_PROPERTY:docs,FILES>
    DEPENDS $<TARGET_PROPERTY:docs,FILES> $<TARGET_PROPERTY:docs,NO_SUCH_PROPERTY>
)
add_custom_target(gen ALL COMMAND tool --name=$<TARGET_PROPERTY:docs,NAME> DEPENDS out.txt)
add_executable(app main.c)
add_custom_command(TARGET app POST_BUILD COMMAND tool --post=$<TARGET_PROPERTY:docs,FILES>)
""")
    (tmp_path / "main.c").write_text("int main() { return 0; }\n")

    configure(tmp_path, "build")

    ninja_content = (tmp_path / "build.ninja").read_text()
    command = join_command_lines(
        cd_command("build"), "tool --type=UTILITY --files=a.md;b.md"
    )
    assert (
        f"build $builddir/out.txt: custom_command a.md b.md\n  cmd = {command}\n"
    ) in ninja_content
    assert "tool --name=docs" in ninja_content
    assert re.search(r"tool \S?--post=a\.md;b\.md", ninja_content)


def test_custom_commands_run_in_binary_directory(tmp_path: Path) -> None:
    """Like in CMake, commands run in the binary directory of where they were
    added, which a relative WORKING_DIRECTORY is about, too."""
    import subprocess

    from cja.generator import configure

    (tmp_path / "CMakeLists.txt").write_text("""\
cmake_minimum_required(VERSION 3.10)
project(WorkingDirectoryTest C)

add_custom_command(OUTPUT gen.txt COMMAND ${CMAKE_COMMAND} -E touch gen.txt)
add_custom_target(gen ALL COMMAND ${CMAKE_COMMAND} -E touch target.txt DEPENDS gen.txt)
file(MAKE_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/rel)
add_custom_target(rel ALL
    COMMAND ${CMAKE_COMMAND} -E touch in_rel.txt WORKING_DIRECTORY rel)
add_executable(app main.c)
add_custom_command(TARGET app POST_BUILD COMMAND ${CMAKE_COMMAND} -E touch post.txt)
add_subdirectory(sub)
""")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "CMakeLists.txt").write_text("""\
add_custom_command(OUTPUT subgen.txt COMMAND ${CMAKE_COMMAND} -E touch subgen.txt)
add_custom_target(subgen ALL DEPENDS subgen.txt)
""")
    (tmp_path / "main.c").write_text("int main(void) { return 0; }\n")

    configure(tmp_path, "build")
    subprocess.run(["ninja"], cwd=tmp_path, check=True, capture_output=True)

    for created in (
        "gen.txt",
        "target.txt",
        "rel/in_rel.txt",
        "post.txt",
        "sub/subgen.txt",
    ):
        assert (tmp_path / "build" / created).is_file(), created
        assert not (tmp_path / created).exists(), created


def test_custom_command_byproducts(tmp_path: Path) -> None:
    """BYPRODUCTS are files that the commands write besides their outputs, so
    they're generated ones and other commands can depend on them."""
    import subprocess

    from cja.generator import configure

    (tmp_path / "CMakeLists.txt").write_text("""\
cmake_minimum_required(VERSION 3.10)
project(ByproductsTest C)

add_custom_command(OUTPUT main.txt BYPRODUCTS by.txt
    COMMAND ${CMAKE_COMMAND} -E touch main.txt
    COMMAND ${CMAKE_COMMAND} -E touch by.txt)
add_custom_command(OUTPUT user.txt DEPENDS by.txt
    COMMAND ${CMAKE_COMMAND} -E touch user.txt)
add_custom_target(gen ALL DEPENDS user.txt BYPRODUCTS target_by.txt
    COMMAND ${CMAKE_COMMAND} -E touch target_by.txt)
add_executable(app main.c)
add_custom_command(TARGET app POST_BUILD BYPRODUCTS post_by.txt
    COMMAND ${CMAKE_COMMAND} -E touch post_by.txt)
foreach(file by.txt target_by.txt post_by.txt other.txt)
  get_property("GENERATED_${file}"
      SOURCE ${CMAKE_CURRENT_BINARY_DIR}/${file} PROPERTY GENERATED)
endforeach()
""")
    (tmp_path / "main.c").write_text("int main(void) { return 0; }\n")

    ctx = configure(tmp_path, "build", strict=True)

    for file in ("by.txt", "target_by.txt", "post_by.txt"):
        assert ctx.variables[f"GENERATED_{file}"] == "1", file
    assert ctx.variables["GENERATED_other.txt"] == "0"

    ninja_content = re.sub(r"\$\n *", "", (tmp_path / "build.ninja").read_text())
    assert (
        "build $builddir/main.txt | $builddir/by.txt: custom_command\n" in ninja_content
    )
    assert (
        "build $builddir/user.txt: custom_command $builddir/by.txt\n" in ninja_content
    )
    assert "build $builddir/gen.stamp | $builddir/target_by.txt: " in ninja_content
    assert (
        "build $builddir/CMakeFiles/app.post_build | $builddir/post_by.txt: "
        in ninja_content
    )

    subprocess.run(["ninja"], cwd=tmp_path, check=True, capture_output=True)
    for created in ("by.txt", "user.txt", "target_by.txt", "post_by.txt"):
        assert (tmp_path / "build" / created).is_file(), created


@pytest.mark.parametrize("verbatim", ["", "VERBATIM"])
def test_post_build_shell_operators(tmp_path: Path, verbatim: str) -> None:
    """Like in CMake, shell operators in POST_BUILD commands aren't quoted,
    also with VERBATIM, and a target name runs that target."""
    import subprocess

    from cja.generator import configure

    (tmp_path / "CMakeLists.txt").write_text(f"""\
cmake_minimum_required(VERSION 3.10)
project(PostBuildShellTest C)
add_executable(app main.c)
add_custom_command(TARGET app POST_BUILD COMMAND echo "a b" > echoed.txt {verbatim})
add_custom_command(TARGET app POST_BUILD COMMAND app --flag {verbatim})
""")
    (tmp_path / "main.c").write_text("int main(void) { return 0; }\n")

    configure(tmp_path, "build")

    unwrapped = re.sub(r"\$\n *", "", (tmp_path / "build.ninja").read_text())
    app = (tmp_path / "build" / f"app{EXE_EXT}").as_posix()
    assert f"{app} --flag" in unwrapped
    subprocess.run(["ninja"], cwd=tmp_path, check=True, capture_output=True)
    # cmd.exe's echo keeps the quotes
    echoed = (tmp_path / "build" / "echoed.txt").read_text().strip().strip('"')
    assert echoed == "a b"


def test_post_build_working_directory(tmp_path: Path) -> None:
    """Like in CMake, each POST_BUILD command runs in its WORKING_DIRECTORY,
    which a relative path is about the binary directory for, and else in the
    binary directory."""
    import subprocess

    from cja.generator import configure

    (tmp_path / "CMakeLists.txt").write_text("""\
cmake_minimum_required(VERSION 3.10)
project(PostBuildWorkingDirectoryTest C)
add_subdirectory(sub)
""")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "assets").mkdir()
    (tmp_path / "sub" / "CMakeLists.txt").write_text("""\
add_executable(app main.c)
file(MAKE_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/rel)
add_custom_command(TARGET app POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E touch first.txt)
add_custom_command(TARGET app POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E touch relative.txt
    COMMAND ${CMAKE_COMMAND} -E touch relative2.txt
    WORKING_DIRECTORY rel)
add_custom_command(TARGET app POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E touch absolute.txt
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/assets)
add_custom_command(TARGET app POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E touch target_dir.txt
    WORKING_DIRECTORY $<TARGET_FILE_DIR:app>/rel)
add_custom_command(TARGET app POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E touch last.txt)
""")
    (tmp_path / "sub" / "main.c").write_text("int main(void) { return 0; }\n")

    configure(tmp_path, "build", strict=True)
    subprocess.run(["ninja"], cwd=tmp_path, check=True, capture_output=True)

    binary_dir = tmp_path / "build" / "sub"
    for created in (
        binary_dir / "first.txt",
        binary_dir / "rel" / "relative.txt",
        binary_dir / "rel" / "relative2.txt",
        tmp_path / "sub" / "assets" / "absolute.txt",
        binary_dir / "rel" / "target_dir.txt",
        binary_dir / "last.txt",
    ):
        assert created.is_file(), created


def _write_generating_directory(directory: Path) -> None:
    """A directory whose library is built from a generated source, and whose
    custom target depends on outputs, byproducts and a source file."""
    directory.mkdir(parents=True)
    (directory / "gen.c.in").write_text("int f(void) { return 0; }\n")
    (directory / "in.txt").write_text("")
    (directory / "CMakeLists.txt").write_text("""\
add_custom_command(OUTPUT gen.c
    COMMAND ${CMAKE_COMMAND} -E copy ${CMAKE_CURRENT_SOURCE_DIR}/gen.c.in gen.c)
add_library(generated STATIC gen.c)
# Depends on the output of a command that is added later
add_custom_command(OUTPUT second.txt DEPENDS first.txt by.txt
    COMMAND ${CMAKE_COMMAND} -E touch second.txt)
add_custom_command(OUTPUT first.txt BYPRODUCTS by.txt DEPENDS in.txt
    COMMAND ${CMAKE_COMMAND} -E touch first.txt
    COMMAND ${CMAKE_COMMAND} -E touch by.txt)
add_custom_target(outputs ALL DEPENDS second.txt)
get_source_file_property(GENERATED_LOCATION gen.c LOCATION)
set(GENERATED_LOCATION "${GENERATED_LOCATION}" PARENT_SCOPE)
""")


def test_custom_command_outputs_in_other_binary_directory(tmp_path: Path) -> None:
    """Like in CMake, relative outputs are in the binary directory of where
    the command is added, also if that isn't the default one."""
    import subprocess

    from cja.generator import configure

    tmp_path = tmp_path.resolve()
    (tmp_path / "CMakeLists.txt").write_text("""\
cmake_minimum_required(VERSION 3.10)
project(OtherBinaryDirectoryTest C)
add_subdirectory(sub other_build)
""")
    _write_generating_directory(tmp_path / "sub")

    ctx = configure(tmp_path, "build", strict=True)
    subprocess.run(["ninja"], cwd=tmp_path, check=True, capture_output=True)

    binary_dir = tmp_path / "build" / "other_build"
    assert ctx.variables["GENERATED_LOCATION"] == (binary_dir / "gen.c").as_posix()
    for created in ("gen.c", f"libgenerated{LIB_EXT}", "first.txt", "by.txt"):
        assert (binary_dir / created).is_file(), created
    assert (binary_dir / "second.txt").is_file()
    assert not (tmp_path / "build" / "sub" / "gen.c").exists()


def test_custom_command_outputs_in_fetched_content(tmp_path: Path) -> None:
    """The outputs of a fetched dependency are in its binary directory, while
    its sources are elsewhere in the build directory."""
    import subprocess
    import tarfile

    from cja.generator import configure

    tmp_path = tmp_path.resolve()
    _write_generating_directory(tmp_path / "dep")
    tar_path = tmp_path / "dep.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(tmp_path / "dep", arcname="dep")
    project = tmp_path / "project"
    project.mkdir()
    (project / "CMakeLists.txt").write_text(f"""\
cmake_minimum_required(VERSION 3.10)
project(FetchedOutputsTest C)
include(FetchContent)
FetchContent_Declare(dep URL file://{tar_path})
FetchContent_MakeAvailable(dep)
""")

    configure(project, "build")
    subprocess.run(["ninja"], cwd=project, check=True, capture_output=True)

    binary_dir = project / "build" / "_deps" / "dep-build"
    for created in ("gen.c", f"libgenerated{LIB_EXT}", "second.txt", "by.txt"):
        assert (binary_dir / created).is_file(), created


@pytest.mark.parametrize("event", ["", "POST_BUILD"])
def test_arguments_with_spaces_without_verbatim(tmp_path: Path, event: str) -> None:
    """Like in CMake, an argument with spaces stays one also without VERBATIM,
    while the shell sees all of its other characters."""
    import subprocess

    from cja.generator import configure

    if event:
        command = "add_custom_command(TARGET app POST_BUILD"
    else:
        command = "add_custom_command(OUTPUT copied.txt"
    (tmp_path / "CMakeLists.txt").write_text(f"""\
cmake_minimum_required(VERSION 3.10)
project(SpacesTest C)
add_executable(app main.c)
{command}
    COMMAND ${{CMAKE_COMMAND}} -E copy "${{CMAKE_CURRENT_SOURCE_DIR}}/my file.txt" copied.txt
    COMMAND echo "x y" > echoed.txt)
add_custom_target(copy ALL DEPENDS {"app" if event else "copied.txt"})
""")
    (tmp_path / "main.c").write_text("int main(void) { return 0; }\n")
    (tmp_path / "my file.txt").write_text("content")

    configure(tmp_path, "build")
    subprocess.run(["ninja"], cwd=tmp_path, check=True, capture_output=True)

    assert (tmp_path / "build" / "copied.txt").read_text() == "content"
    echoed = (tmp_path / "build" / "echoed.txt").read_text().strip().strip('"')
    assert echoed == "x y"
