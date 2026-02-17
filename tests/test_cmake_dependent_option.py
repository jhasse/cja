"""Tests for CMakeDependentOption module and cmake_dependent_option()."""

from pathlib import Path

from cja.generator import BuildContext, process_commands
from cja.parser import Command


def test_include_cmake_dependent_option_strict() -> None:
    """include(CMakeDependentOption) should be accepted in strict mode."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [Command(name="include", args=["CMakeDependentOption"], line=1)]
    process_commands(commands, ctx, strict=True)


def test_cmake_dependent_option_true_uses_default() -> None:
    """When dependency is true, option default is used."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    commands = [
        Command(name="set", args=["BOX2D_DISABLE_SIMD", "OFF"], line=1),
        Command(
            name="cmake_dependent_option",
            args=[
                "BOX2D_AVX2",
                "Enable AVX2",
                "ON",
                "NOT BOX2D_DISABLE_SIMD",
                "OFF",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["BOX2D_AVX2"] == "ON"


def test_cmake_dependent_option_true_does_not_override_existing() -> None:
    """When dependency is true, pre-existing value is preserved."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["BOX2D_AVX2"] = "OFF"
    commands = [
        Command(name="set", args=["BOX2D_DISABLE_SIMD", "OFF"], line=1),
        Command(
            name="cmake_dependent_option",
            args=[
                "BOX2D_AVX2",
                "Enable AVX2",
                "ON",
                "NOT BOX2D_DISABLE_SIMD",
                "OFF",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["BOX2D_AVX2"] == "OFF"


def test_cmake_dependent_option_false_forces_value() -> None:
    """When dependency is false, force value is applied."""
    ctx = BuildContext(source_dir=Path("."), build_dir=Path("build"))
    ctx.variables["BOX2D_AVX2"] = "ON"
    commands = [
        Command(name="set", args=["BOX2D_DISABLE_SIMD", "ON"], line=1),
        Command(
            name="cmake_dependent_option",
            args=[
                "BOX2D_AVX2",
                "Enable AVX2",
                "ON",
                "NOT BOX2D_DISABLE_SIMD",
                "OFF",
            ],
            line=2,
        ),
    ]
    process_commands(commands, ctx)
    assert ctx.variables["BOX2D_AVX2"] == "OFF"
