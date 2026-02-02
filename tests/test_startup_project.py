from cninja.generator import BuildContext, process_commands, generate_ninja
from cninja.parser import Command


def test_vs_startup_project_directory(tmp_path):
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(name="add_executable", args=["exe1", "main1.cpp"], line=1),
        Command(name="add_executable", args=["exe2", "main2.cpp"], line=2),
        Command(
            name="set_property",
            args=["DIRECTORY", "PROPERTY", "VS_STARTUP_PROJECT", "exe2"],
            line=3,
        ),
    ]

    process_commands(commands, ctx)

    ninja_file = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_file, "build")

    content = ninja_file.read_text()
    # Check that 'run' depends on exe2, not exe1
    assert "build run: run_exe $builddir/exe2" in content
    assert "build run: run_exe $builddir/exe1" not in content


def test_vs_startup_project_first_by_default(tmp_path):
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")

    commands = [
        Command(name="add_executable", args=["exe1", "main1.cpp"], line=1),
        Command(name="add_executable", args=["exe2", "main2.cpp"], line=2),
    ]

    process_commands(commands, ctx)

    ninja_file = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_file, "build")

    content = ninja_file.read_text()
    # Check that 'run' depends on exe1 (the first one)
    assert "build run: run_exe $builddir/exe1" in content
