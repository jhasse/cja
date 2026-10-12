"""Tests for EXCLUDE_FROM_ALL."""

import platform
import re
from pathlib import Path

from cja.generator import configure

EXE_EXT = ".exe" if platform.system() == "Windows" else ""
LIB_EXT = ".lib" if platform.system() == "Windows" else ".a"


def _all_targets(source_dir: Path) -> list[str]:
    ninja_content = (source_dir / "build.ninja").read_text()
    ninja_content = re.sub(r"\$\n\s*", "", ninja_content)
    match = re.search(r"^build all: phony (.*)$", ninja_content, re.MULTILINE)
    assert match
    return match.group(1).split()


def test_add_executable_exclude_from_all(tmp_path: Path) -> None:
    (tmp_path / "CMakeLists.txt").write_text(
        """
add_executable(app main.c)
add_executable(tool EXCLUDE_FROM_ALL main.c)
"""
    )
    (tmp_path / "main.c").write_text("int main() { return 0; }")

    configure(tmp_path, "build")

    all_targets = _all_targets(tmp_path)
    assert f"$builddir/app{EXE_EXT}" in all_targets
    assert f"$builddir/tool{EXE_EXT}" not in all_targets
    # The target itself is still generated
    assert f"build $builddir/tool{EXE_EXT}:" in (tmp_path / "build.ninja").read_text()


def test_add_library_exclude_from_all(tmp_path: Path) -> None:
    (tmp_path / "CMakeLists.txt").write_text(
        """
add_library(a lib.c)
add_library(b STATIC EXCLUDE_FROM_ALL lib.c)
add_library(c EXCLUDE_FROM_ALL lib.c)
add_library(b_alias ALIAS b)
"""
    )
    (tmp_path / "lib.c").write_text("int f(void) { return 0; }")

    configure(tmp_path, "build")

    all_targets = _all_targets(tmp_path)
    assert f"$builddir/liba{LIB_EXT}" in all_targets
    assert f"$builddir/libb{LIB_EXT}" not in all_targets
    assert f"$builddir/libc{LIB_EXT}" not in all_targets
    # EXCLUDE_FROM_ALL isn't treated as a source file
    assert "EXCLUDE_FROM_ALL" not in (tmp_path / "build.ninja").read_text()


def test_set_target_properties_exclude_from_all(tmp_path: Path) -> None:
    (tmp_path / "CMakeLists.txt").write_text(
        """
add_executable(app main.c)
add_executable(tool main.c)
set_target_properties(tool PROPERTIES EXCLUDE_FROM_ALL TRUE)
"""
    )
    (tmp_path / "main.c").write_text("int main() { return 0; }")

    configure(tmp_path, "build")

    all_targets = _all_targets(tmp_path)
    assert f"$builddir/app{EXE_EXT}" in all_targets
    assert f"$builddir/tool{EXE_EXT}" not in all_targets


def test_add_subdirectory_exclude_from_all(tmp_path: Path) -> None:
    (tmp_path / "CMakeLists.txt").write_text(
        """
add_executable(app main.c)
add_subdirectory(sub EXCLUDE_FROM_ALL)
add_executable(app2 main.c)
"""
    )
    (tmp_path / "main.c").write_text("int main() { return 0; }")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "CMakeLists.txt").write_text(
        """
add_executable(sub_exe main.c)
add_executable(sub_included main.c)
set_target_properties(sub_included PROPERTIES EXCLUDE_FROM_ALL FALSE)
add_custom_target(sub_custom ALL COMMAND echo hi)
add_subdirectory(nested)
"""
    )
    (sub / "main.c").write_text("int main() { return 0; }")
    nested = sub / "nested"
    nested.mkdir()
    (nested / "CMakeLists.txt").write_text("add_library(nested_lib lib.c)")
    (nested / "lib.c").write_text("int f(void) { return 0; }")

    configure(tmp_path, "build")

    all_targets = _all_targets(tmp_path)
    assert f"$builddir/app{EXE_EXT}" in all_targets
    assert f"$builddir/app2{EXE_EXT}" in all_targets
    assert f"$builddir/sub/sub_exe{EXE_EXT}" not in all_targets
    assert f"$builddir/sub/sub_included{EXE_EXT}" in all_targets
    assert "sub_custom" not in all_targets
    assert f"$builddir/sub/nested/libnested_lib{LIB_EXT}" not in all_targets
    # EXCLUDE_FROM_ALL isn't taken as the binary directory
    assert not (tmp_path / "build" / "EXCLUDE_FROM_ALL").exists()


def test_add_subdirectory_exclude_from_all_with_binary_dir(tmp_path: Path) -> None:
    (tmp_path / "CMakeLists.txt").write_text(
        """
add_executable(app main.c)
add_subdirectory(sub sub_build EXCLUDE_FROM_ALL)
"""
    )
    (tmp_path / "main.c").write_text("int main() { return 0; }")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "CMakeLists.txt").write_text("add_executable(sub_exe main.c)")
    (sub / "main.c").write_text("int main() { return 0; }")

    configure(tmp_path, "build")

    all_targets = _all_targets(tmp_path)
    assert f"$builddir/app{EXE_EXT}" in all_targets
    assert f"$builddir/sub_build/sub_exe{EXE_EXT}" not in all_targets
