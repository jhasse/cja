import json

from cja.generator import BuildContext, process_commands, generate_ninja
from cja.parser import Command


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
    assert "run_exe" not in content

    cja_json = json.loads((tmp_path / "build" / "cja.json").read_text())
    assert cja_json["run_executable"] == "build/exe2"


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
    assert "run_exe" not in content

    cja_json = json.loads((tmp_path / "build" / "cja.json").read_text())
    assert cja_json["run_executable"] == "build/exe1"
