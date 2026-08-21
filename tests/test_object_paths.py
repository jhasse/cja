"""Tests for object-file output path generation."""

from pathlib import PurePosixPath, PureWindowsPath

from cja.generator import _obj_subdir


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
