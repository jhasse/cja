"""Integration tests for cja."""

import subprocess
import platform
import os
from pathlib import Path
import pytest

from cja import configure
from tests.helpers import copy_unignored_tree


EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
EXE_EXT = ".exe" if platform.system() == "Windows" else ""
LIB_EXT = ".lib" if platform.system() == "Windows" else ".a"


def _is_gnu_cxx() -> bool:
    try:
        result = subprocess.run(
            ["c++", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    if result.returncode != 0:
        return False
    version_output = f"{result.stdout}\n{result.stderr}".lower()
    return "g++" in version_output or "gcc" in version_output


def test_hello_example(tmp_path: Path) -> None:
    """Test building the hello example project."""
    # Copy example to tmp_path since build.ninja is written in source dir
    source_dir = tmp_path / "hello"
    copy_unignored_tree(EXAMPLES_DIR / "hello", source_dir)

    # Configure
    configure(source_dir, "build")

    # Check build.ninja was created in source directory
    build_ninja = source_dir / "build.ninja"
    assert build_ninja.exists()

    # Build with ninja (run from source dir)
    result = subprocess.run(
        ["ninja"],
        cwd=source_dir,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ninja failed: {result.stderr}"

    # Check executable was created in build dir
    build_dir = source_dir / "build"
    hello_exe = build_dir / f"hello{EXE_EXT}"
    assert hello_exe.exists()

    # Run the executable and check output
    result = subprocess.run(
        [str(hello_exe)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "Hello, World!"


def test_libmath_example(tmp_path: Path) -> None:
    """Test building the libmath example with static library."""
    # Copy example to tmp_path since build.ninja is written in source dir
    source_dir = tmp_path / "libmath"
    copy_unignored_tree(EXAMPLES_DIR / "libmath", source_dir)

    # Configure
    configure(source_dir, "build")

    # Check build.ninja was created in source directory
    build_ninja = source_dir / "build.ninja"
    assert build_ninja.exists()

    # Build with ninja (run from source dir)
    result = subprocess.run(
        ["ninja"],
        cwd=source_dir,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ninja failed: {result.stderr}"

    # Check library and executable were created in build dir
    build_dir = source_dir / "build"
    assert (build_dir / f"libmath{LIB_EXT}").exists()
    assert (build_dir / f"calculator{EXE_EXT}").exists()

    # Run the executable and check output
    result = subprocess.run(
        [str(build_dir / f"calculator{EXE_EXT}")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "3 + 4 = 7" in result.stdout
    assert "3 * 4 = 12" in result.stdout


def test_objlib_example(tmp_path: Path) -> None:
    """Test building the objlib example with OBJECT library."""
    # Copy example to tmp_path since build.ninja is written in source dir
    source_dir = tmp_path / "objlib"
    copy_unignored_tree(EXAMPLES_DIR / "objlib", source_dir)

    # Configure
    configure(source_dir, "build")

    # Check build.ninja was created in source directory
    build_ninja = source_dir / "build.ninja"
    assert build_ninja.exists()

    # Verify no .a file is created for OBJECT library
    content = build_ninja.read_text()
    assert f"libutils{LIB_EXT}" not in content

    # Build with ninja (run from source dir)
    result = subprocess.run(
        ["ninja"],
        cwd=source_dir,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ninja failed: {result.stderr}"

    # Check executable was created in build dir (but no .a file)
    build_dir = source_dir / "build"
    assert (build_dir / f"app{EXE_EXT}").exists()
    assert not (build_dir / f"libutils{LIB_EXT}").exists()

    # Run the executable and check output
    result = subprocess.run(
        [str(build_dir / f"app{EXE_EXT}")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Value: 42" in result.stdout


def test_manifest_example(tmp_path: Path) -> None:
    """Test building the manifest example with .manifest as source (auto .rc + llvm-rc)."""
    source_dir = tmp_path / "manifest"
    copy_unignored_tree(EXAMPLES_DIR / "manifest", source_dir)

    # Configure
    configure(source_dir, "build")

    build_ninja = source_dir / "build.ninja"
    assert build_ninja.exists()

    # Build with ninja
    result = subprocess.run(
        ["ninja"],
        cwd=source_dir,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ninja failed: {result.stderr}"

    build_dir = source_dir / "build"
    app_exe = build_dir / f"app{EXE_EXT}"
    assert app_exe.exists()

    # Run and verify output
    result = subprocess.run(
        [str(app_exe)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Hello from manifest example" in result.stdout


def test_manifest_example_ninja_content(tmp_path: Path) -> None:
    """Verify manifest example generates rc rule, .res, and auto-generated .rc (Windows)."""
    source_dir = tmp_path / "manifest"
    copy_unignored_tree(EXAMPLES_DIR / "manifest", source_dir)
    configure(source_dir, "build")

    content = (source_dir / "build.ninja").read_text()
    if platform.system() == "Windows":
        assert "rule rc" in content
        assert "app_app.res" in content
        # Auto-generated .rc references manifest
        generated_rc = source_dir / "build" / "app_app.rc"
        assert generated_rc.exists()
        assert "RT_MANIFEST" in generated_rc.read_text()


def test_subdirectory_example(tmp_path: Path) -> None:
    """Test subdirectory example list-dir behavior matches CMake."""
    source_dir = tmp_path / "subdirectory"
    copy_unignored_tree(EXAMPLES_DIR / "subdirectory", source_dir)

    configure(source_dir, "build")

    build_ninja = source_dir / "build.ninja"
    assert build_ninja.exists()


def test_regenerate_preserves_defines(tmp_path: Path) -> None:
    """Test that -DFOO=bar is preserved in the reconfigure rule after regeneration."""
    source_dir = tmp_path / "hello"
    copy_unignored_tree(EXAMPLES_DIR / "hello", source_dir)

    configure(source_dir, "build", variables={"FOO": "bar"})

    build_ninja = source_dir / "build.ninja"
    assert build_ninja.exists()
    content = build_ninja.read_text()
    assert "-DFOO=bar" in content

    # Touch CMakeLists.txt and rebuild — ninja should regenerate build.ninja
    cmake_file = source_dir / "CMakeLists.txt"
    import time

    time.sleep(0.05)
    cmake_file.write_text(cmake_file.read_text())

    result = subprocess.run(
        ["ninja"],
        cwd=source_dir,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ninja failed: {result.stderr}"

    # After regeneration, -DFOO=bar should still be in the reconfigure command
    content = build_ninja.read_text()
    assert "-DFOO=bar" in content


@pytest.mark.skipif(
    not _is_gnu_cxx(),
    reason="requires GNU g++ as c++",
)
def test_linker_unknown_argument_captured_output_gxx_only(tmp_path: Path) -> None:
    """Unknown linker arg should fail and include compiler diagnostic output."""
    source_dir = tmp_path / "libmath"
    copy_unignored_tree(EXAMPLES_DIR / "libmath", source_dir)

    cmake_file = source_dir / "CMakeLists.txt"
    cmake_file.write_text(
        cmake_file.read_text() + '\nset(CMAKE_LINKER_FLAGS "--asdf")\n',
    )

    configure(source_dir, "build")

    result = subprocess.run(
        ["ninja"],
        cwd=source_dir,
        capture_output=True,
        text=True,
        env={**os.environ, "CLICOLOR_FORCE": "1", "LC_ALL": "C"},
    )
    assert result.returncode != 0
    output_lower = f"{result.stdout}\n{result.stderr}".lower()
    assert "unrecognized command-line option" in output_lower
    assert "\x1b[01m\x1b[k--asdf\x1b[m\x1b[k" in output_lower


def test_stale_object_removed_from_static_library(tmp_path: Path) -> None:
    """Removing a source file should remove its object from the static library."""
    source_dir = tmp_path / "stale_obj"
    source_dir.mkdir()

    # Create a static library with two source files
    (source_dir / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(stale_obj)\n"
        "add_library(mylib STATIC foo.cpp bar.cpp)\n"
        "add_executable(app main.cpp)\n"
        "target_link_libraries(app PRIVATE mylib)\n"
    )
    (source_dir / "foo.cpp").write_text(
        'extern "C" int foo_func() { return 1; }\n'
    )
    (source_dir / "bar.cpp").write_text(
        'extern "C" int bar_func() { return 2; }\n'
    )
    (source_dir / "main.cpp").write_text(
        'extern "C" int foo_func();\n'
        "int main() { return foo_func() - 1; }\n"
    )

    # First build with both sources
    configure(source_dir, "build")
    result = subprocess.run(
        ["ninja"], cwd=source_dir, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"ninja failed: {result.stderr}"

    lib_path = source_dir / "build" / f"libmylib{LIB_EXT}"
    assert lib_path.exists()

    # Verify both objects are in the archive
    ar_cmd = "llvm-ar" if platform.system() == "Windows" else "ar"
    ar_result = subprocess.run(
        [ar_cmd, "t", str(lib_path)], capture_output=True, text=True, check=True,
    )
    members = ar_result.stdout.strip().split("\n")
    assert any("bar" in m for m in members), f"bar not in archive: {members}"
    assert any("foo" in m for m in members), f"foo not in archive: {members}"

    # Remove bar.cpp from CMakeLists.txt (keep only foo.cpp)
    (source_dir / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(stale_obj)\n"
        "add_library(mylib STATIC foo.cpp)\n"
        "add_executable(app main.cpp)\n"
        "target_link_libraries(app PRIVATE mylib)\n"
    )

    # Reconfigure and rebuild
    configure(source_dir, "build")
    result = subprocess.run(
        ["ninja"], cwd=source_dir, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"ninja rebuild failed: {result.stderr}"

    # bar's object must no longer be in the archive
    ar_result = subprocess.run(
        [ar_cmd, "t", str(lib_path)], capture_output=True, text=True, check=True,
    )
    members = ar_result.stdout.strip().split("\n")
    assert not any("bar" in m for m in members), (
        f"stale bar object still in archive after source removal: {members}"
    )
