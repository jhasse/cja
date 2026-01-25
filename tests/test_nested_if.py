"""Test nested parentheses in if() conditions."""

from pathlib import Path
from cninja.parser import parse
from cninja.generator import configure


def test_nested_parentheses_parsing() -> None:
    content = "if((A AND B) OR C)\nendif()"
    commands = parse(content)
    assert len(commands) == 2
    assert commands[0].name == "if"
    # Arguments should include the inner parentheses as separate tokens
    expected_args = ["(", "A", "AND", "B", ")", "OR", "C"]
    assert commands[0].args == expected_args


def test_nested_parentheses_evaluation(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    # Case 1: (True AND True) OR False -> True
    (source_dir / "CMakeLists.txt").write_text(
        "set(A 1)\n"
        "set(B 1)\n"
        "set(C 0)\n"
        "if((A AND B) OR C)\n"
        "  set(RESULT TRUE)\n"
        "else()\n"
        "  set(RESULT FALSE)\n"
        "endif()\n"
    )
    ctx = configure(source_dir, "build")
    assert ctx.variables["RESULT"] == "TRUE"

    # Case 2: (True AND False) OR False -> False
    (source_dir / "CMakeLists.txt").write_text(
        "set(A 1)\n"
        "set(B 0)\n"
        "set(C 0)\n"
        "if((A AND B) OR C)\n"
        "  set(RESULT TRUE)\n"
        "else()\n"
        "  set(RESULT FALSE)\n"
        "endif()\n"
    )
    ctx = configure(source_dir, "build")
    assert ctx.variables["RESULT"] == "FALSE"

    # Case 3: (True AND False) OR True -> True
    (source_dir / "CMakeLists.txt").write_text(
        "set(A 1)\n"
        "set(B 0)\n"
        "set(C 1)\n"
        "if((A AND B) OR C)\n"
        "  set(RESULT TRUE)\n"
        "else()\n"
        "  set(RESULT FALSE)\n"
        "endif()\n"
    )
    ctx = configure(source_dir, "build")
    assert ctx.variables["RESULT"] == "TRUE"
