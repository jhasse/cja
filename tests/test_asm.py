"""Tests for assembly source compilation."""

from pathlib import Path

from cja.generator import BuildContext, generate_ninja, process_commands
from cja.parser import Command


def test_assembly_sources_use_asm_rule_without_depfile(tmp_path: Path) -> None:
    """`.s` files should use the asm rule, which does not require a depfile."""
    (tmp_path / "boot.s").write_text(".globl foo\nfoo:\n  ret\n")
    (tmp_path / "main.c").write_text("int main(void) { return 0; }\n")
    ctx = BuildContext(source_dir=tmp_path, build_dir=tmp_path / "build")
    process_commands(
        [
            Command(
                name="add_library",
                args=["mylib", "STATIC", "boot.s", "main.c"],
                line=1,
            ),
        ],
        ctx,
    )

    ninja_path = tmp_path / "build.ninja"
    generate_ninja(ctx, ninja_path, "build")
    content = ninja_path.read_text()

    assert "rule asm" in content
    assert "depfile = $out.d" in content  # still used by cc/cxx
    assert "\n  deps = gcc\n" in content

    # The assembly object must use the asm rule, not cc with -MMD.
    assert ": asm " in content or ": asm\n" in content or ": asm $" in content
    asm_edges = [
        line
        for line in content.splitlines()
        if "boot.s" in line and line.startswith("build ")
    ]
    assert asm_edges
    assert any(": asm" in line for line in asm_edges)
    assert not any(": cc" in line and "boot.s" in line for line in asm_edges)
