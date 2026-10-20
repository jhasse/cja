"""Tests for get_filename_component command."""

from pathlib import Path

from cja.generator import configure


def test_get_filename_component(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    (source_dir / "CMakeLists.txt").write_text(
        "project(test)\n"
        'get_filename_component(DIR "a/b/c.txt" DIRECTORY)\n'
        'get_filename_component(NAME "a/b/c.txt" NAME)\n'
        'get_filename_component(EXT "a/b/c.txt" EXT)\n'
        'get_filename_component(NAME_WE "a/b/c.txt" NAME_WE)\n'
        'get_filename_component(ABS "c.txt" ABSOLUTE)\n'
        'get_filename_component(ABS_BASE "c.txt" ABSOLUTE BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/sub")\n'
    )

    ctx = configure(source_dir, "build")

    assert ctx.variables["DIR"].replace("\\", "/") == "a/b"
    assert ctx.variables["NAME"] == "c.txt"
    assert ctx.variables["EXT"] == ".txt"
    assert ctx.variables["NAME_WE"] == "c"
    assert ctx.variables["ABS"] == str((source_dir / "c.txt").resolve())
    assert ctx.variables["ABS_BASE"] == str((source_dir / "sub" / "c.txt").resolve())


def test_get_filename_component_empty_dir(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        'get_filename_component(DIR "c.txt" DIRECTORY)'
    )
    ctx = configure(source_dir, "build")
    assert ctx.variables["DIR"] == ""


def test_get_filename_component_extensions(tmp_path: Path) -> None:
    """EXT and NAME_WE split at the first dot, LAST_EXT and NAME_WLE at the last."""
    (tmp_path / "CMakeLists.txt").write_text(
        'foreach(f "a/b.tar.gz" ".bashrc" "dir/.config.yml" "a.b/c")\n'
        "  foreach(m EXT NAME_WE LAST_EXT NAME_WLE)\n"
        '    get_filename_component(r "${f}" ${m})\n'
        '    list(APPEND results "[${r}]")\n'
        "  endforeach()\n"
        "endforeach()\n"
    )
    ctx = configure(tmp_path, "build")
    assert ctx.variables["results"].split(";") == [
        *["[.tar.gz]", "[b]", "[.gz]", "[b.tar]"],
        *["[.bashrc]", "[]", "[.bashrc]", "[]"],
        *["[.config.yml]", "[]", "[.yml]", "[.config]"],
        *["[]", "[c]", "[]", "[c]"],
    ]


def test_get_filename_component_program_and_cache(tmp_path: Path) -> None:
    (tmp_path / "CMakeLists.txt").write_text(
        'get_filename_component(abs "/x/y/../z/./w" ABSOLUTE)\n'
        'get_filename_component(prog "sh -c foo" PROGRAM PROGRAM_ARGS prog_args)\n'
        'set(cached before CACHE STRING "")\n'
        'get_filename_component(cached "a/b.c" NAME CACHE)\n'
        'get_filename_component(new "a/b.c" NAME CACHE)\n'
    )
    ctx = configure(tmp_path, "build")
    assert Path(ctx.variables["abs"]) == Path("/x/z/w").absolute()
    assert Path(ctx.variables["prog"]).name.startswith("sh")
    assert ctx.variables["prog_args"] == " -c foo"
    assert ctx.variables["cached"] == "before"
    assert ctx.cache_values["new"] == "b.c"
