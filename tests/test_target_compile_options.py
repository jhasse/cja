"""Tests for target_compile_options command."""

import platform
import re
from pathlib import Path

from cja.generator import BuildContext, generate_ninja, process_commands
from cja.parser import Command, parse


def test_target_compile_options_executable() -> None:
    """target_compile_options adds options to executable target."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="add_executable", args=["myapp", "main.c"], line=1),
        Command(
            name="target_compile_options",
            args=["myapp", "PRIVATE", "-Wall", "-Wextra"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    exe = ctx.get_executable("myapp")
    assert exe is not None
    assert "-Wall" in exe.compile_options
    assert "-Wextra" in exe.compile_options


def test_target_compile_options_visibility(tmp_path: Path) -> None:
    """PUBLIC/INTERFACE options propagate to linking executable."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="add_library", args=["mylib", "lib.c"], line=1),
        Command(
            name="target_compile_options",
            args=[
                "mylib",
                "PUBLIC",
                "-Wall",
                "PRIVATE",
                "-Werror",
                "INTERFACE",
                "-Winvalid-pch",
            ],
            line=2,
        ),
        Command(name="add_executable", args=["myapp", "main.c"], line=3),
        Command(name="target_link_libraries", args=["myapp", "mylib"], line=4),
    ]
    process_commands(commands, ctx)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert "-Wall" in lib.compile_options
    assert "-Werror" in lib.compile_options
    assert "-Winvalid-pch" not in lib.compile_options
    assert "-Wall" in lib.public_compile_options
    assert "-Winvalid-pch" in lib.public_compile_options
    assert "-Werror" not in lib.public_compile_options

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")
    lines = ninja_path.read_text().splitlines()

    lib_line_idx = next(i for i, line in enumerate(lines) if " lib.c" in line)
    lib_line_block = "\n".join(lines[lib_line_idx : lib_line_idx + 2])
    assert "-Wall" in lib_line_block
    assert "-Werror" in lib_line_block

    exe_line_idx = next(i for i, line in enumerate(lines) if " main.c" in line)
    exe_line_block = "\n".join(lines[exe_line_idx : exe_line_idx + 2])
    assert "-Wall" in exe_line_block
    assert "-Winvalid-pch" in exe_line_block
    assert "-Werror" not in exe_line_block


def test_target_compile_options_compile_language(tmp_path: Path) -> None:
    """$<COMPILE_LANGUAGE:...> gates options to matching source languages."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    (tmp_path / "main.cpp").write_text("int main() { return 0; }\n")
    (tmp_path / "helper.c").write_text("void helper(void) {}\n")
    (tmp_path / "boot.s").write_text("\n")
    commands = [
        Command(
            name="add_library",
            args=["mylib", "main.cpp", "helper.c", "boot.s"],
            line=1,
        ),
        Command(
            name="target_compile_options",
            args=[
                "mylib",
                "PRIVATE",
                "$<$<COMPILE_LANGUAGE:ASM>:-xassembler-with-cpp>",
                "$<$<COMPILE_LANGUAGE:CXX>:-fno-rtti>",
                "$<$<COMPILE_LANGUAGE:C>:-fno-strict-aliasing>",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")
    lines = ninja_path.read_text().splitlines()

    def flags_for(source: str) -> str:
        idx = next(i for i, line in enumerate(lines) if f" {source}" in line)
        return "\n".join(lines[idx : idx + 2])

    cpp_block = flags_for("main.cpp")
    assert "-fno-rtti" in cpp_block
    assert "-xassembler-with-cpp" not in cpp_block
    assert "-fno-strict-aliasing" not in cpp_block

    c_block = flags_for("helper.c")
    assert "-fno-strict-aliasing" in c_block
    assert "-fno-rtti" not in c_block
    assert "-xassembler-with-cpp" not in c_block

    asm_block = flags_for("boot.s")
    assert "-xassembler-with-cpp" in asm_block
    assert "-fno-rtti" not in asm_block
    assert "-fno-strict-aliasing" not in asm_block


def test_target_compile_options_lists(tmp_path: Path) -> None:
    """An option that is a list, or evaluates to one, is several flags."""
    from cja.generator import configure

    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(OptionListTest C)\n"
        "add_library(mylib STATIC lib.c)\n"
        "target_compile_options(mylib PRIVATE\n"
        '    "-DQUOTED1;-DQUOTED2" "$<JOIN:-DJOINED1;-DJOINED2,;>")\n'
    )
    (tmp_path / "lib.c").write_text("int f(void) { return 0; }\n")

    configure(tmp_path, "build")

    ninja_content = (tmp_path / "build.ninja").read_text()
    cflags = next(
        line for line in ninja_content.splitlines() if line.startswith("  cflags = ")
    )
    # Without what the toolchain adds on Windows
    definitions = [flag for flag in cflags.split()[2:] if flag.startswith("-D")]
    assert definitions == ["-DQUOTED1", "-DQUOTED2", "-DJOINED1", "-DJOINED2"]


def test_target_compile_options_multiline_genex(tmp_path: Path) -> None:
    """Multi-line genex flag blocks expand to space-separated flags per source."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    ctx.variables["CMAKE_CXX_COMPILER_ID"] = "GNU"
    (tmp_path / "main.cpp").write_text("int main() { return 0; }\n")
    commands = parse(
        "add_library(mylib main.cpp)\n"
        "target_compile_options(mylib PRIVATE\n"
        "  $<$<CXX_COMPILER_ID:GNU>:\n"
        "    -Wall -Wextra -Wno-unused-parameter -Wno-unused-variable>)\n"
    )
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")
    content = ninja_path.read_text()
    assert "-Wall -Wextra -Wno-unused-parameter -Wno-unused-variable" in content
    assert "-Wall;-Wextra" not in content


def test_add_library_multiline_genex_source_list(tmp_path: Path) -> None:
    """Multi-line genex source blocks expand into separate sources."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    for name in ("a.c", "b.c", "c.c"):
        (src_dir / name).write_text("int x;\n")

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    ctx.variables["FEATURE"] = "ON"
    commands = parse(
        "add_library(mylib\n"
        "  src/a.c\n"
        "  $<$<BOOL:${FEATURE}>:\n"
        "    src/b.c\n"
        "    src/c.c\n"
        "  >)\n"
    )
    process_commands(commands, ctx)

    lib = ctx.get_library("mylib")
    assert lib is not None
    assert "src/a.c" in lib.sources
    assert "src/b.c" in lib.sources
    assert "src/c.c" in lib.sources


def test_windows_clang_upgrades_cxx11_in_target_compile_options(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """On Windows clang++, target -std=c++11 should be emitted as -std=c++14."""
    monkeypatch.setattr("cja.generator.platform.system", lambda: "Windows")

    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    ctx.cxx_compiler = "clang++"
    commands = [
        Command(name="add_executable", args=["myapp", "main.cpp"], line=1),
        Command(
            name="target_compile_options",
            args=["myapp", "PRIVATE", "-std=c++11"],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")
    content = ninja_path.read_text()
    assert "-std=c++14" in content
    assert "-std=c++11" not in content


def test_compile_options_and_definitions_are_escaped(tmp_path: Path) -> None:
    """Like in CMake, each one is a single argument of the compiler with
    whatever characters it has, e.g. the quotes of a string."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = parse(
        r"""
add_executable(myapp main.c)
target_compile_options(myapp PRIVATE -DOPTION=\"a\ b\" -Wall)
target_compile_definitions(myapp PRIVATE UNQUOTED=\"\(a\)\" "QUOTED=\"a\\\\b\"")
set_source_files_properties(main.c PROPERTIES COMPILE_OPTIONS -DSOURCE=\"c\")
"""
    )
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")
    # With unwrapped lines
    flags = re.sub(r" *\$\n *", " ", ninja_path.read_text())
    if platform.system() == "Windows":
        expected = [
            r'-DUNQUOTED=\"(a)\"',
            r'-DQUOTED=\"a\\b\"',
            r'"-DOPTION=\"a b\""',
            "-Wall",
            r'-DSOURCE=\"c\"',
        ]
    else:
        expected = [
            r"-DUNQUOTED=\"\(a\)\"",
            r"-DQUOTED=\"a\\\\b\"",
            r"-DOPTION=\"a\ b\"",
            "-Wall",
            r"-DSOURCE=\"c\"",
        ]
    for flag in expected:
        assert f" {flag}" in flags


def test_options_of_genex_with_spaces(tmp_path: Path) -> None:
    """The space-separated items of an unquoted generator expression are
    separate options, while a quoted one is a single argument with a space."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = parse(
        """
add_executable(myapp main.c)
target_compile_options(myapp PRIVATE $<$<BOOL:ON>:-Wall -Wextra> "$<1:-DQUOTED=a b>")
target_link_options(myapp PRIVATE $<$<BOOL:ON>:-Wl,--as-needed -Wl,--no-undefined>)
"""
    )
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")
    # With unwrapped lines
    flags = re.sub(r" *\$\n *", " ", ninja_path.read_text())
    if platform.system() == "Windows":
        quoted = '"-DQUOTED=a b"'
    else:
        quoted = r"-DQUOTED=a\ b"
    assert f" -Wall -Wextra {quoted}" in flags
    assert " -Wl,--as-needed -Wl,--no-undefined" in flags


def test_dollar_sign_in_options_and_definitions(tmp_path: Path) -> None:
    """Like in CMake, it's escaped for the shell and for Ninja, so that e.g.
    the linker gets $ORIGIN."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = parse(
        r"""
add_executable(myapp main.c)
target_compile_options(myapp PRIVATE "-DOPTION=\$1")
target_compile_definitions(myapp PRIVATE "DEFINITION=\$2")
target_link_options(myapp PRIVATE "-Wl,-rpath,\$ORIGIN/lib")
"""
    )
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")
    # With unwrapped lines
    flags = re.sub(r" *\$\n *", " ", ninja_path.read_text())
    dollar = "$$" if platform.system() == "Windows" else "\\$$"
    for flag in ("-DOPTION=@1", "-DDEFINITION=@2", "-Wl,-rpath,@ORIGIN/lib"):
        assert f" {flag.replace('@', dollar)}" in flags
