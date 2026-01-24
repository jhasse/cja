"""Test handling of header files in targets."""

from pathlib import Path
from cninja.generator import BuildContext, process_commands, generate_ninja
from cninja.parser import Command


def test_headers_not_compiled(tmp_path: Path) -> None:
    """Test that header files are not compiled."""
    source_dir = tmp_path
    (source_dir / "main.cpp").touch()
    (source_dir / "header.h").touch()
    (source_dir / "other.hpp").touch()

    ctx = BuildContext(source_dir=source_dir, build_dir=source_dir / "build")
    commands = [
        Command(
            name="add_executable",
            args=["myapp", "main.cpp", "header.h", "other.hpp"],
            is_quoted=[False, False, False, False],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    # Generate Ninja
    ninja_path = source_dir / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    ninja_content = ninja_path.read_text()

    # main.cpp should be compiled
    assert "build $builddir/myapp_main.o: cxx main.cpp" in ninja_content

    # header.h and other.hpp should NOT be compiled
    assert "myapp_header.o" not in ninja_content
    assert "myapp_other.o" not in ninja_content

    # header.h and other.hpp should NOT be order-only dependencies
    assert "||" not in ninja_content


def test_headers_in_library(tmp_path: Path) -> None:
    """Test that header files in libraries are also handled correctly."""
    source_dir = tmp_path
    (source_dir / "lib.cpp").touch()
    (source_dir / "lib.h").touch()

    ctx = BuildContext(source_dir=source_dir, build_dir=source_dir / "build")
    commands = [
        Command(
            name="add_library",
            args=["mylib", "lib.cpp", "lib.h"],
            is_quoted=[False, False, False],
            line=1,
        ),
    ]
    process_commands(commands, ctx)

    ninja_path = source_dir / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")

    ninja_content = ninja_path.read_text()

    assert "build $builddir/mylib_lib.o: cxx lib.cpp" in ninja_content
    assert "||" not in ninja_content
    assert "mylib_lib.o" in ninja_content
    assert "mylib_lib.h.o" not in ninja_content
