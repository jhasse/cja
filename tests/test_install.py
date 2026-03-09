"""Tests for install command."""

from pathlib import Path
import platform

from cja.generator import BuildContext, configure, process_commands, generate_ninja
from cja.parser import Command

EXE_EXT = ".exe" if platform.system() == "Windows" else ""
LIB_EXT = ".lib" if platform.system() == "Windows" else ".a"


def test_install_targets(tmp_path: Path) -> None:
    """Test that install(TARGETS ...) correctly creates install targets in Ninja."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    # Mock HOME environment variable for the test to have a predictable path
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()

    # We need to monkeypatch Path.home() or just accept that it will use the real one.
    # Actually, our implementation uses Path.home() / ".local" / "bin" as default.
    # Let's test explicit DESTINATION first as it's easier.

    dest_path = tmp_path / "install_dir"

    commands = [
        Command(name="add_executable", args=["myapp", "main.cpp"], line=1),
        Command(
            name="install",
            args=["TARGETS", "myapp", "DESTINATION", str(dest_path)],
            line=2,
        ),
    ]
    process_commands(commands, ctx)

    assert len(ctx.install_targets) == 1
    assert ctx.install_targets[0].targets == ["myapp"]
    assert ctx.install_targets[0].destination == str(dest_path)

    # Test propagation to Ninja file
    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    ninja_content = ninja_path.read_text()
    rel_dest = str(dest_path.relative_to(tmp_path))

    # Check for install_file rule
    assert "rule install_file" in ninja_content

    # Check for individual install build statement
    # src is $builddir/myapp
    expected_dest = f"{rel_dest}/myapp{EXE_EXT}"
    assert "install_file" in ninja_content
    assert str(expected_dest) in ninja_content
    assert f"$builddir/myapp{EXE_EXT}" in ninja_content
    # Check for out_dir variable (may be wrapped across lines due to long paths)
    assert "out_dir =" in ninja_content
    assert rel_dest in ninja_content

    # Check for phony install target
    assert "build install: phony" in ninja_content
    assert str(expected_dest) in ninja_content


def test_cmake_install_prefix_default(tmp_path: Path) -> None:
    """CMAKE_INSTALL_PREFIX should default to <builddir>/install."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text("project(test_install_prefix)\n")

    ctx = configure(source_dir, "build")

    assert (
        ctx.variables["CMAKE_INSTALL_PREFIX"]
        == f"{source_dir.as_posix()}/build/install"
    )


def test_cmake_install_prefix_respects_override(tmp_path: Path) -> None:
    """-DCMAKE_INSTALL_PREFIX should override the default value."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "CMakeLists.txt").write_text("project(test_install_prefix)\n")

    ctx = configure(
        source_dir,
        "build",
        variables={"CMAKE_INSTALL_PREFIX": "/opt/custom-prefix"},
    )

    assert ctx.variables["CMAKE_INSTALL_PREFIX"] == "/opt/custom-prefix"


def test_install_targets_ignores_file_set_names(tmp_path: Path) -> None:
    """FILE_SET entries in install(TARGETS ...) must not be treated as targets."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    commands = [
        Command(name="add_library", args=["fmt", "STATIC", "fmt.cc"], line=1),
        Command(name="add_library", args=["fmt-header-only", "INTERFACE"], line=2),
        Command(
            name="install",
            args=[
                "TARGETS",
                "fmt",
                "fmt-header-only",
                "EXPORT",
                "fmt-targets",
                "LIBRARY",
                "DESTINATION",
                "lib",
                "ARCHIVE",
                "DESTINATION",
                "lib",
                "PUBLIC_HEADER",
                "DESTINATION",
                "include/fmt",
                "RUNTIME",
                "DESTINATION",
                "bin",
                "FILE_SET",
                "fmt",
                "DESTINATION",
                "include/fmt",
            ],
            line=3,
        ),
    ]
    process_commands(commands, ctx)

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    ninja_content = ninja_path.read_text()
    # Only one install edge should be emitted for libfmt (FILE_SET "fmt" must not be treated as a target).
    assert ninja_content.count(f"build include/fmt/libfmt{LIB_EXT}: install_file") == 1
