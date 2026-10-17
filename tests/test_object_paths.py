"""Tests for object-file output path generation."""

from pathlib import PurePosixPath, PureWindowsPath

from cja.generator import _obj_subdir, _object_paths


def test_obj_subdir_relative_source() -> None:
    assert _obj_subdir(PurePosixPath("src/foo.c")) == "src"
    assert _obj_subdir(PureWindowsPath("src/foo.c")) == "src"


def test_obj_subdir_top_level_source() -> None:
    assert _obj_subdir(PurePosixPath("foo.c")) == ""
    assert _obj_subdir(PureWindowsPath("foo.c")) == ""


def test_obj_subdir_strips_windows_drive() -> None:
    # External dependency fetched onto another drive (e.g. via CPM) must not
    # produce an invalid 'build/D:/...' object path that makes ninja fail.
    assert (
        _obj_subdir(PureWindowsPath("D:/cpm/sdl/55e1/src/SDL.c")) == "cpm/sdl/55e1/src"
    )


def test_obj_subdir_strips_posix_root() -> None:
    assert _obj_subdir(PurePosixPath("/usr/include/foo/bar.c")) == "usr/include/foo"


def test_obj_subdir_neutralizes_parent_refs() -> None:
    # '..' components would otherwise let objects escape $builddir.
    assert _obj_subdir(PurePosixPath("../external/baz.c")) == "__up__/external"


def test_object_paths_keep_unique_stems() -> None:
    assert _object_paths("lib", ["src/foo.c", "bar.c"]) == [
        "$builddir/src/lib_foo.o",
        "$builddir/lib_bar.o",
    ]


def test_object_paths_disambiguate_same_stem() -> None:
    # Archives store members by basename only; duplicates make MSVC's linker
    # warn LNK4255 and drop their debug info.
    assert _object_paths("lib", ["a/util.c", "b/c/util.cpp", "util.c"]) == [
        "$builddir/a/lib_a_util.o",
        "$builddir/b/c/lib_b_c_util.o",
        "$builddir/lib_util.o",
    ]
