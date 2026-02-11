from cja.generator import BuildContext, process_commands, generate_ninja
from cja.parser import Command
import pytest


def test_public_flags_propagation_to_library(tmp_path):
    """Test that PUBLIC flags from one library propagate to another library linking to it."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        # lib1 has a public definition
        Command(name="add_library", args=["lib1", "lib1.cpp"], line=1),
        Command(
            name="target_compile_definitions",
            args=["lib1", "PUBLIC", "LIB1_PUB"],
            line=2,
        ),
        # lib2 links to lib1
        Command(name="add_library", args=["lib2", "lib2.cpp"], line=3),
        Command(name="target_link_libraries", args=["lib2", "PUBLIC", "lib1"], line=4),
    ]

    process_commands(commands, ctx)

    # Check that lib1 has the definition
    lib1 = ctx.get_library("lib1")
    assert "LIB1_PUB" in lib1.public_compile_definitions

    # Check that lib2 doesn't have it in its OWN definitions, but it should be used during compilation
    lib2 = ctx.get_library("lib2")
    assert "LIB1_PUB" not in lib2.compile_definitions

    # Generate ninja and check the compile command for lib2
    ninja_file = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_file, "build")

    content = ninja_file.read_text()
    # lib2 compile command should have -DLIB1_PUB
    assert "build $builddir/lib2_lib2.o: cxx lib2.cpp" in content
    # Find the line with lib2_lib2.o and check its variables
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if "build $builddir/lib2_lib2.o" in line:
            # Check the next line for cflags
            assert "-DLIB1_PUB" in lines[i + 1]
            break
    else:
        pytest.fail("Could not find build statement for lib2_lib2.o")


def test_non_target_library_propagation(tmp_path):
    """Test that plain library names (not targets) propagate and result in -l flags."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        # lib1 links to a plain 'freetype' library
        Command(name="add_library", args=["lib1", "lib1.cpp"], line=1),
        Command(
            name="target_link_libraries", args=["lib1", "PUBLIC", "freetype"], line=2
        ),
        # app links to lib1
        Command(name="add_executable", args=["app", "main.cpp"], line=3),
        Command(name="target_link_libraries", args=["app", "PRIVATE", "lib1"], line=4),
    ]

    process_commands(commands, ctx)

    # Generate ninja and check the link command for app
    ninja_file = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_file, "build")

    content = ninja_file.read_text()
    # app link command should have -lfreetype
    assert "build $builddir/app: link_cxx" in content
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if "build $builddir/app: link_cxx" in line:
            assert "-lfreetype" in lines[i + 1]
            break
    else:
        pytest.fail("Could not find build statement for app")


def test_static_private_link_only_propagation(tmp_path):
    """Test that PRIVATE dependencies of STATIC libraries only propagate link flags, not compile flags."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        # lib2 has a public definition
        Command(name="add_library", args=["lib2", "lib2.cpp"], line=1),
        Command(
            name="target_compile_definitions",
            args=["lib2", "PUBLIC", "LIB2_PUB"],
            line=2,
        ),
        # lib1 links to lib2 PRIVATELY
        Command(name="add_library", args=["lib1", "lib1.cpp"], line=3),
        Command(name="target_link_libraries", args=["lib1", "PRIVATE", "lib2"], line=4),
        # app links to lib1
        Command(name="add_executable", args=["app", "main.cpp"], line=5),
        Command(name="target_link_libraries", args=["app", "PRIVATE", "lib1"], line=6),
    ]

    process_commands(commands, ctx)

    # Generate ninja
    ninja_file = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_file, "build")

    content = ninja_file.read_text()

    # app compile command should NOT have -DLIB2_PUB
    for i, line in enumerate(content.splitlines()):
        if "build $builddir/app_main.o" in line:
            assert "-DLIB2_PUB" not in content.splitlines()[i + 1]
            break
    else:
        pytest.fail("Could not find build statement for app_main.o")

    # app link command SHOULD have lib2.a
    found_app_link = False
    for i, line in enumerate(content.splitlines()):
        if "build $builddir/app: link_cxx" in line:
            found_app_link = True
            # Check this line and subsequent lines (Ninja uses $ for continuation)
            full_build_stmt = line
            j = i
            while full_build_stmt.endswith("$") and j + 1 < len(content.splitlines()):
                j += 1
                full_build_stmt += content.splitlines()[j]
            assert "$builddir/liblib2.a" in full_build_stmt
            break
    assert found_app_link, "Could not find build statement for app"


def test_generator_expression_stripping(tmp_path, capsys):
    """Test that complex generator expressions in target_link_libraries are stripped."""
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    genex = "$<$<AND:$<CXX_COMPILER_ID:GNU>,$<VERSION_LESS:$<CXX_COMPILER_VERSION>,9.0>>:stdc++fs>"
    commands = [
        Command(name="add_executable", args=["app", "main.cpp"], line=1),
        Command(name="target_link_libraries", args=["app", "PRIVATE", genex], line=2),
    ]

    process_commands(commands, ctx)

    # Generate ninja
    ninja_file = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_file, "build")

    content = ninja_file.read_text()
    # Check that genex is NOT in the ninja file
    assert "stdc++fs" not in content
    assert "$<" not in content

    # Check for warning
    captured = capsys.readouterr()
    assert (
        "generator expressions in target_link_libraries are not yet supported"
        in captured.err
    )
