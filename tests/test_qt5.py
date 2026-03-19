"""Integration test for the Qt5 example."""

import subprocess
import platform
from pathlib import Path

import pytest

from cja import configure
from tests.helpers import copy_unignored_tree

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
EXE_EXT = ".exe" if platform.system() == "Windows" else ""


def has_qt5() -> bool:
    """Check if Qt5Core is available via pkg-config."""
    try:
        result = subprocess.run(
            ["pkg-config", "--exists", "Qt5Core"], capture_output=True
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


@pytest.mark.skipif(not has_qt5(), reason="Qt5 not found via pkg-config")
def test_qt5_example(tmp_path: Path) -> None:
    """Test building the Qt5 example project."""
    source_dir = tmp_path / "qt5"
    copy_unignored_tree(EXAMPLES_DIR / "qt5", source_dir)

    configure(source_dir, "build")

    build_ninja = source_dir / "build.ninja"
    assert build_ninja.exists()

    result = subprocess.run(
        ["ninja"],
        cwd=source_dir,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ninja failed: {result.stderr}"

    build_dir = source_dir / "build"
    qt5_hello = build_dir / f"qt5_hello{EXE_EXT}"
    assert qt5_hello.exists()

    result = subprocess.run(
        [str(qt5_hello)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Hello from Qt" in result.stdout
