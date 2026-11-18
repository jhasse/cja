"""Tests for $<TARGET_OBJECTS:tgt> among the sources of a target."""

import platform
import re
import subprocess
from pathlib import Path

import pytest

from cja import configure
from cja.generator import BuildContext, generate_ninja, process_commands
from cja.parser import Command

EXE_EXT = ".exe" if platform.system() == "Windows" else ""


def _ninja(tmp_path: Path, commands: list[Command], strict: bool = False) -> str:
    """The build.ninja of a project with these commands, with unwrapped lines."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    process_commands(commands, ctx)
    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build", strict)
    return re.sub(r"\$\n +", "", ninja_path.read_text())


def _inputs(ninja: str, rule: str, target: str) -> list[str]:
    """The inputs of the edge that archives or links a target."""
    edge = re.search(
        rf"^build \$builddir/\S*{re.escape(target)}\S*: {rule}\w* (.*)$",
        ninja,
        re.MULTILINE,
    )
    assert edge, f"no {rule} edge for {target}"
    return edge.group(1).split(" |")[0].split()


def test_static_library_of_object_libraries(tmp_path: Path) -> None:
    """A library can consist of nothing but the objects of object libraries,
    like libwebp's, rather than be an archive without members."""
    ninja = _ninja(
        tmp_path,
        [
            Command(name="add_library", args=["dec", "OBJECT", "dec.c"], line=1),
            Command(name="add_library", args=["dsp", "OBJECT", "dsp.c"], line=2),
            Command(
                name="add_library",
                args=["webp", "$<TARGET_OBJECTS:dec>", "$<TARGET_OBJECTS:dsp>"],
                line=3,
            ),
        ],
    )

    assert _inputs(ninja, "ar", "webp") == ["$builddir/dec_dec.o", "$builddir/dsp_dsp.o"]


def test_sources_keep_target_objects() -> None:
    """The expression stays among the sources, also as one of a list, and
    isn't taken for a path."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    process_commands(
        [
            Command(name="add_library", args=["objs", "OBJECT", "objs.c"], line=1),
            Command(
                name="add_library",
                args=["lib", "STATIC", "lib.c;$<TARGET_OBJECTS:objs>"],
                line=2,
            ),
            Command(
                name="add_executable",
                args=["app", "main.c", "$<$<BOOL:ON>:$<TARGET_OBJECTS:objs>>"],
                line=3,
            ),
            Command(
                name="add_executable",
                args=["without", "main.c", "$<$<BOOL:OFF>:$<TARGET_OBJECTS:objs>>"],
                line=4,
            ),
        ],
        ctx,
    )

    lib = ctx.get_library("lib")
    app = ctx.get_executable("app")
    without = ctx.get_executable("without")
    assert lib is not None and app is not None and without is not None
    assert lib.sources == ["lib.c", "$<TARGET_OBJECTS:objs>"]
    assert app.sources == ["main.c", "$<TARGET_OBJECTS:objs>"]
    assert without.sources == ["main.c"]


def test_library_defined_before_its_object_library(tmp_path: Path) -> None:
    """The library whose objects are meant can be defined later, as CMake
    only evaluates the expression when generating."""
    ninja = _ninja(
        tmp_path,
        [
            Command(
                name="add_library",
                args=["lib", "STATIC", "own.c", "$<TARGET_OBJECTS:objs>"],
                line=1,
            ),
            Command(name="add_library", args=["objs", "OBJECT", "objs.c"], line=2),
        ],
    )

    assert _inputs(ninja, "ar", "lib") == ["$builddir/lib_own.o", "$builddir/objs_objs.o"]


def test_shared_library_and_alias(tmp_path: Path) -> None:
    """A shared library links the objects, also those of an alias."""
    ninja = _ninja(
        tmp_path,
        [
            Command(
                name="add_library",
                args=["lib", "SHARED", "own.c", "$<TARGET_OBJECTS:ns::objs>"],
                line=1,
            ),
            Command(name="add_library", args=["objs", "OBJECT", "objs.c"], line=2),
            Command(name="add_library", args=["ns::objs", "ALIAS", "objs"], line=3),
        ],
    )

    assert _inputs(ninja, "solink", "lib")[:2] == [
        "$builddir/lib_own.o",
        "$builddir/objs_objs.o",
    ]


def test_executable_links_objects_once(tmp_path: Path) -> None:
    """An executable links the objects, and only once if it links their
    object library too."""
    ninja = _ninja(
        tmp_path,
        [
            Command(name="add_library", args=["objs", "OBJECT", "objs.c"], line=1),
            Command(
                name="add_executable",
                args=["app", "main.c", "$<TARGET_OBJECTS:objs>"],
                line=2,
            ),
            Command(
                name="add_executable",
                args=["both", "main.c", "$<TARGET_OBJECTS:objs>"],
                line=3,
            ),
            Command(name="target_link_libraries", args=["both", "objs"], line=4),
        ],
    )

    assert _inputs(ninja, "link", "app") == ["$builddir/app_main.o", "$builddir/objs_objs.o"]
    assert _inputs(ninja, "link", "both") == ["$builddir/both_main.o", "$builddir/objs_objs.o"]


def test_target_sources(tmp_path: Path) -> None:
    """target_sources() adds the objects too, and to the users of a library
    that has them as INTERFACE sources."""
    ninja = _ninja(
        tmp_path,
        [
            Command(name="add_library", args=["objs", "OBJECT", "objs.c"], line=1),
            Command(name="add_library", args=["lib", "STATIC", "lib.c"], line=2),
            Command(
                name="target_sources",
                args=["lib", "PRIVATE", "$<TARGET_OBJECTS:objs>"],
                line=3,
            ),
            Command(name="add_library", args=["usage", "INTERFACE"], line=4),
            Command(
                name="target_sources",
                args=["usage", "INTERFACE", "$<TARGET_OBJECTS:objs>"],
                line=5,
            ),
            Command(name="add_executable", args=["app", "main.c"], line=6),
            Command(name="target_link_libraries", args=["app", "usage"], line=7),
        ],
    )

    assert _inputs(ninja, "ar", "lib") == ["$builddir/lib_lib.o", "$builddir/objs_objs.o"]
    assert _inputs(ninja, "link", "app") == ["$builddir/app_main.o", "$builddir/objs_objs.o"]


def test_objects_of_other_libraries(tmp_path: Path) -> None:
    """They can be the objects of any library, but only those of its own
    sources, not the ones it has of other libraries in turn."""
    ninja = _ninja(
        tmp_path,
        [
            Command(name="add_library", args=["objs", "OBJECT", "objs.c"], line=1),
            Command(
                name="add_library",
                args=["static", "STATIC", "static.c", "$<TARGET_OBJECTS:objs>"],
                line=2,
            ),
            Command(
                name="add_executable",
                args=["app", "main.c", "$<TARGET_OBJECTS:static>"],
                line=3,
            ),
        ],
    )

    assert _inputs(ninja, "link", "app") == [
        "$builddir/app_main.o",
        "$builddir/static_static.o",
    ]


def test_unknown_target(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Objects of a target that doesn't exist are an error, as CMake doesn't
    configure such a project either."""
    commands = [
        Command(
            name="add_library",
            args=["lib", "STATIC", "lib.c", "$<TARGET_OBJECTS:nope>"],
            line=3,
        )
    ]

    with pytest.raises(SystemExit):
        _ninja(tmp_path, commands)
    assert (
        "error: lib has $<TARGET_OBJECTS:nope> among its sources, but there's "
        "no target nope" in capsys.readouterr().err
    )


@pytest.mark.parametrize(
    "command",
    [
        Command(name="add_library", args=["other", "INTERFACE"], line=1),
        Command(name="add_custom_target", args=["other"], line=1),
    ],
)
def test_target_without_objects(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: Command
) -> None:
    """Nor does CMake configure one with the objects of an interface library
    or a custom target, which have none."""
    commands = [
        command,
        Command(
            name="add_executable",
            args=["app", "main.c", "$<TARGET_OBJECTS:other>"],
            line=2,
        ),
    ]

    with pytest.raises(SystemExit):
        _ninja(tmp_path, commands)
    assert (
        "error: app has $<TARGET_OBJECTS:other> among its sources, but other "
        "isn't a library with objects" in capsys.readouterr().err
    )


def test_imported_library(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """An imported library has no objects, which CMake accepts."""
    ninja = _ninja(
        tmp_path,
        [
            Command(name="add_library", args=["imp", "STATIC", "IMPORTED"], line=1),
            Command(
                name="add_executable",
                args=["app", "main.c", "$<TARGET_OBJECTS:imp>"],
                line=2,
            ),
        ],
    )

    assert _inputs(ninja, "link", "app") == ["$builddir/app_main.o"]
    assert "TARGET_OBJECTS" not in capsys.readouterr().err


def test_executable_unsupported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CMake takes the objects of an executable too, which isn't supported:
    a warning, and an error with --strict."""
    commands = [
        Command(name="add_executable", args=["tool", "tool.c"], line=1),
        Command(
            name="add_library",
            args=["lib", "STATIC", "lib.c", "$<TARGET_OBJECTS:tool>"],
            line=2,
        ),
    ]

    ninja = _ninja(tmp_path, commands)
    assert _inputs(ninja, "ar", "lib") == ["$builddir/lib_lib.o"]
    assert (
        "warning: lib has $<TARGET_OBJECTS:tool> among its sources, but the "
        "objects of an executable aren't supported" in capsys.readouterr().err
    )

    with pytest.raises(SystemExit):
        _ninja(tmp_path, commands, strict=True)
    assert "error: lib has $<TARGET_OBJECTS:tool>" in capsys.readouterr().err


def test_build(tmp_path: Path) -> None:
    """Building and running an executable that needs the objects from a
    library that has no sources of its own."""
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.15)\n"
        "project(target_objects C)\n"
        "add_library(all $<TARGET_OBJECTS:one> $<TARGET_OBJECTS:two>)\n"
        "add_library(one OBJECT one.c)\n"
        "add_library(two OBJECT two.c)\n"
        "add_executable(app main.c)\n"
        "target_link_libraries(app all)\n"
    )
    (tmp_path / "one.c").write_text("int one(void) { return 1; }\n")
    (tmp_path / "two.c").write_text("int two(void) { return 2; }\n")
    (tmp_path / "main.c").write_text(
        "int one(void);\nint two(void);\nint main(void) { return one() + two() - 3; }\n"
    )

    configure(tmp_path, "build")
    subprocess.run(["ninja"], cwd=tmp_path, check=True)
    subprocess.run([str(tmp_path / "build" / f"app{EXE_EXT}")], check=True)
