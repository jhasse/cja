"""Tests for CMAKE_PROJECT_INCLUDE behavior."""

from pathlib import Path


def test_cmake_project_include_file(tmp_path: Path) -> None:
    """CMAKE_PROJECT_INCLUDE should include the file after project()."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    (source_dir / "project_hook.cmake").write_text(
        'set(PROJECT_HOOK_NAME "${PROJECT_NAME}")\n'
    )
    (source_dir / "CMakeLists.txt").write_text(
        'project(Demo)\nset(AFTER_PROJECT "${PROJECT_HOOK_NAME}")\n'
    )

    from cja.generator import configure

    ctx = configure(
        source_dir,
        "build",
        variables={"CMAKE_PROJECT_INCLUDE": "project_hook.cmake"},
    )

    assert ctx.variables["PROJECT_HOOK_NAME"] == "Demo"
    assert ctx.variables["AFTER_PROJECT"] == "Demo"


def test_cmake_project_include_list(tmp_path: Path) -> None:
    """CMAKE_PROJECT_INCLUDE should accept a semicolon-separated list."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    (source_dir / "first_hook.cmake").write_text('set(HOOK_ORDER "1")\n')
    (source_dir / "second_hook.cmake").write_text('set(HOOK_ORDER "${HOOK_ORDER}2")\n')
    (source_dir / "CMakeLists.txt").write_text("project(Demo)\n")

    from cja.generator import configure

    ctx = configure(
        source_dir,
        "build",
        variables={"CMAKE_PROJECT_INCLUDE": "first_hook.cmake;second_hook.cmake"},
    )

    assert ctx.variables["HOOK_ORDER"] == "12"
