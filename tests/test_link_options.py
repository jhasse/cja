"""Tests for target_link_options()."""

import re
from pathlib import Path

from cja.generator import BuildContext, configure, process_commands
from cja.parser import Command


def link_libs(ninja: str, output_pattern: str) -> str:
    """Return the ``libs`` variable of the build statement producing an output."""
    m = re.search(
        rf"^build [^\n]*{output_pattern}[^\n]*: \w*link\w*[^\n]*\n((?:  [^\n]*\n)*)",
        ninja,
        re.MULTILINE,
    )
    assert m, f"no link statement for {output_pattern}:\n{ninja}"
    libs = re.search(r"^  libs = (.*)$", m.group(1), re.MULTILINE)
    return libs.group(1) if libs else ""


def configure_project(
    tmp_path: Path, cmake: str, variables: dict[str, str] | None = None
) -> str:
    (tmp_path / "CMakeLists.txt").write_text(cmake)
    (tmp_path / "main.c").write_text("int main(void) { return 0; }\n")
    (tmp_path / "lib.c").write_text("int lib(void) { return 0; }\n")
    configure(tmp_path, "build", variables=variables)
    return (tmp_path / "build.ninja").read_text()


def test_visibility_is_stored() -> None:
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(
        [
            Command(name="add_library", args=["lib", "STATIC", "lib.c"], line=1),
            Command(name="add_executable", args=["app", "main.c"], line=2),
            Command(
                name="target_link_options",
                args=["lib", "PRIVATE", "-a", "PUBLIC", "-b", "INTERFACE", "-c"],
                line=3,
            ),
            Command(name="target_link_options", args=["app", "PRIVATE", "-d"], line=4),
            Command(
                name="target_link_options",
                args=["app", "BEFORE", "PRIVATE", "-e"],
                line=5,
            ),
        ],
        ctx,
    )
    lib = ctx.get_library("lib")
    exe = ctx.get_executable("app")
    assert lib and exe
    assert lib.link_options == ["-a", "-b"]
    assert lib.public_link_options == ["-b", "-c"]
    assert exe.link_options == ["-e", "-d"]


def test_executable_link_options(tmp_path: Path) -> None:
    ninja = configure_project(
        tmp_path,
        """\
project(test C)
add_executable(app main.c)
target_link_options(app PRIVATE -Wl,--as-needed "SHELL:-Xlinker --gc-sections" LINKER:-z,defs)
""",
    )
    assert (
        link_libs(ninja, "app") == "-Wl,--as-needed -Xlinker --gc-sections -Wl,-z,defs"
    )


def test_interface_link_options_propagate(tmp_path: Path) -> None:
    ninja = configure_project(
        tmp_path,
        """\
project(test C)
add_library(base STATIC lib.c)
target_link_options(base PRIVATE -private-only INTERFACE -from-base)
add_library(mid INTERFACE)
target_link_libraries(mid INTERFACE base)
target_link_options(mid INTERFACE -from-mid -from-base)
add_executable(app main.c)
target_link_libraries(app PRIVATE mid)
target_link_options(app PRIVATE -own)
""",
    )
    # PRIVATE options of base stay private, duplicates are dropped
    assert link_libs(ninja, "app") == "-own -from-mid -from-base"


def test_shared_library_link_options(tmp_path: Path) -> None:
    ninja = configure_project(
        tmp_path,
        """\
project(test C)
add_library(shared SHARED lib.c)
target_link_options(shared PRIVATE -Wl,--no-undefined PUBLIC -Wl,--as-needed)
add_executable(app main.c)
target_link_libraries(app PRIVATE shared)
""",
    )
    assert link_libs(ninja, r"libshared\.\w+") == "-Wl,--no-undefined -Wl,--as-needed"
    assert link_libs(ninja, "app").startswith("-Wl,--as-needed")


def test_generator_expressions(tmp_path: Path) -> None:
    cmake = """\
project(test C)
add_executable(app main.c)
target_link_options(app PRIVATE $<$<CONFIG:Debug>:-debug-flag> $<$<CONFIG:Release>:-release-flag>)
"""
    ninja = configure_project(tmp_path, cmake, {"CMAKE_BUILD_TYPE": "Release"})
    assert link_libs(ninja, "app") == "-release-flag"
