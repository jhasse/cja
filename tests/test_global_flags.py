"""Tests for CMAKE_C_FLAGS and CMAKE_CXX_FLAGS."""

import platform
import re
from pathlib import Path

from cja.generator import configure


def test_cmake_c_flags(tmp_path: Path) -> None:
    """Test that CMAKE_C_FLAGS are included in the ninja file."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_flags)\n"
        'set(CMAKE_C_FLAGS "-Wall -Wextra")\n'
        "add_executable(main main.c)"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    content = ninja_file.read_text()

    # Check that flags are in the rule or build statement
    # Our implementation will put them in the rule for simplicity
    assert "-Wall -Wextra" in content


def test_cmake_cxx_flags(tmp_path: Path) -> None:
    """Test that CMAKE_CXX_FLAGS are included in the ninja file."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_flags)\n"
        'set(CMAKE_CXX_FLAGS "-std=c++17")\n'
        "add_executable(main main.cpp)"
    )
    (source_dir / "main.cpp").write_text("int main() { return 0; }")

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    content = ninja_file.read_text()

    assert "-std=c++17" in content


def test_cmake_cxx_flags_from_cli(tmp_path: Path) -> None:
    """-DCMAKE_CXX_FLAGS must survive project() and appear in compile rules."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(test_cli_flags)\n"
        'string(APPEND CMAKE_CXX_FLAGS " -ffp-contract=off")\n'
        "add_executable(main main.cpp)"
    )
    (source_dir / "main.cpp").write_text("int main() { return 0; }")

    configure(
        source_dir,
        "build",
        variables={"CMAKE_CXX_FLAGS": "-stdlib=libc++"},
    )

    content = (source_dir / "build.ninja").read_text()
    # The flag also appears in the reconfigure -D line; assert on the cxx rule.
    cxx_rule = content.split("rule cxx", 1)[1].split("\nrule ", 1)[0]
    assert "-stdlib=libc++" in cxx_rule
    assert "-ffp-contract=off" in cxx_rule


def test_cmake_linker_flags(tmp_path: Path) -> None:
    """Test that CMAKE_LINKER_FLAGS are included in the ninja file."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_linker_flags)\n"
        'set(CMAKE_LINKER_FLAGS "-Wl,--as-needed")\n'
        "add_executable(main main.c)"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    content = ninja_file.read_text()

    assert "-Wl,--as-needed" in content


def test_cmake_exe_linker_flags(tmp_path: Path) -> None:
    """Test that CMAKE_EXE_LINKER_FLAGS are included in the ninja file."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_exe_linker_flags)\n"
        'set(CMAKE_EXE_LINKER_FLAGS "-fuse-ld=lld")\n'
        "add_executable(main main.c)"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    content = ninja_file.read_text()

    assert "-fuse-ld=lld" in content


def test_linker_flags_of_shared_libraries_and_modules(tmp_path: Path) -> None:
    """Like in CMake, executables are linked with CMAKE_EXE_LINKER_FLAGS,
    shared libraries with CMAKE_SHARED_LINKER_FLAGS and modules with
    CMAKE_MODULE_LINKER_FLAGS."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_linker_flags C)\n"
        'set(CMAKE_EXE_LINKER_FLAGS "-Wl,--exe")\n'
        'set(CMAKE_SHARED_LINKER_FLAGS "-Wl,--shared")\n'
        'set(CMAKE_MODULE_LINKER_FLAGS "-Wl,--module")\n'
        "add_executable(main main.c)\n"
        "add_library(shared SHARED lib.c)\n"
        "add_library(module MODULE lib.c)\n"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")
    (source_dir / "lib.c").write_text("int lib() { return 0; }")

    configure(source_dir, "build")

    # Unwrap the lines that ninja_syntax continues with a trailing "$"
    ninja = re.sub(r" \$\n +", " ", (source_dir / "build.ninja").read_text())
    lines = ninja.splitlines()
    assert "ldflags = -Wl,--exe" in lines
    assert "shared_ldflags = -Wl,--shared" in lines
    assert "module_ldflags = -Wl,--module" in lines

    def following(start: str) -> str:
        """The line after the one that starts like that."""
        return lines[next(i for i, line in enumerate(lines) if line.startswith(start)) + 1]

    assert following("rule link").endswith(" $ldflags $libs")
    assert following("rule solink").endswith(" $shared_ldflags $libs")
    shared = next(line for line in lines if line.startswith("build ") and ": solink " in line)
    assert "module" not in shared
    assert not following(shared).startswith("  shared_ldflags")
    module = next(
        line for line in lines if line.startswith("build ") and "module" in line and ": solink " in line
    )
    assert "  shared_ldflags = $module_ldflags" in lines[lines.index(module) + 1 :][:3]


def test_dollar_sign_in_linker_flags(tmp_path: Path) -> None:
    """Like in CMake, a "$" of the linker flags isn't one of Ninja's, so that
    the linker gets e.g. $ORIGIN. The flags of LINK_FLAGS are also escaped for
    the shell, as they're divided like by one."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_linker_flags_dollar C)\n"
        "set(CMAKE_EXE_LINKER_FLAGS \"-Wl,-rpath,'\\$ORIGIN/exe'\")\n"
        "add_executable(main main.c)\n"
        "set_target_properties(main PROPERTIES\n"
        "  LINK_FLAGS \"-Wl,-rpath,'\\$ORIGIN/prop' '-Wl,-rpath,/with space'\")\n"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")

    configure(source_dir, "build")

    content = (source_dir / "build.ninja").read_text()
    assert "ldflags = -Wl,-rpath,'$$ORIGIN/exe'\n" in content
    if platform.system() == "Windows":
        expected = '-Wl,-rpath,$$ORIGIN/prop "-Wl,-rpath,/with space"'
    else:
        expected = r"-Wl,-rpath,\$$ORIGIN/prop -Wl,-rpath,/with\ space"
    assert f" {expected}" in content


def test_cmake_linker_flags_append(tmp_path: Path) -> None:
    """Test that appending to CMAKE_LINKER_FLAGS works without warnings."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_append)\n"
        'set(CMAKE_LINKER_FLAGS "${CMAKE_LINKER_FLAGS} -fsanitize=address")\n'
        "add_executable(main main.c)"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    content = ninja_file.read_text()

    assert "-fsanitize=address" in content


def test_cmake_c_flags_debug(tmp_path: Path) -> None:
    """Test that CMAKE_C_FLAGS_DEBUG are included in the ninja file."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text(
        "project(test_flags_debug)\n"
        'set(CMAKE_C_FLAGS_DEBUG "-fsanitize=undefined")\n'
        "add_executable(main main.c)"
    )
    (source_dir / "main.c").write_text("int main() { return 0; }")

    configure(source_dir, "build")

    ninja_file = source_dir / "build.ninja"
    content = ninja_file.read_text()

    assert "-fsanitize=undefined" in content
