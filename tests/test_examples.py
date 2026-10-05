"""Build every project in examples/ with ``cja build``.

Examples using CPM or FetchContent download their dependencies, so the first
run needs network access; later runs reuse the CPM cache.
"""

import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers import copy_unignored_tree

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"

# Examples that need a package installed on the system. They're skipped when
# cja reports the package missing; any other failure still fails the test.
SYSTEM_PACKAGE_EXAMPLES = {"boost", "freetype", "gtest", "openssl", "qt5"}
MISSING_PACKAGE = re.compile(r"could not find (?:package|modules): (\S+)")

# Covered by test_clang_tidy_example, which expects the build to fail.
CLANG_TIDY_EXAMPLE = "clang-tidy"

EXAMPLE_MARKS = {
    "frameworks": pytest.mark.skipif(
        platform.system() != "Darwin", reason="Apple frameworks require macOS"
    ),
}

EXAMPLES = [
    pytest.param(p.name, marks=EXAMPLE_MARKS.get(p.name, ()))
    for p in sorted(EXAMPLES_DIR.iterdir())
    if (p / "CMakeLists.txt").is_file() and p.name != CLANG_TIDY_EXAMPLE
]


def _copy_example(name: str, tmp_path: Path) -> Path:
    """Copy an example plus examples/cpm, which other examples include via
    ``../cpm/cmake/CPM.cmake``."""
    source_dir = tmp_path / name
    copy_unignored_tree(EXAMPLES_DIR / name, source_dir)
    if name != "cpm":
        copy_unignored_tree(EXAMPLES_DIR / "cpm", tmp_path / "cpm")
    return source_dir


def _cja_build(source_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "cja", "build"],
        cwd=source_dir,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_builds(name: str, tmp_path: Path) -> None:
    result = _cja_build(_copy_example(name, tmp_path))
    output = result.stdout + result.stderr
    if result.returncode != 0 and name in SYSTEM_PACKAGE_EXAMPLES:
        missing = MISSING_PACKAGE.search(output)
        if missing:
            pytest.skip(f"{missing.group(1)} not installed")
    assert result.returncode == 0, output


@pytest.mark.skipif(shutil.which("clang-tidy") is None, reason="clang-tidy not found")
def test_clang_tidy_example(tmp_path: Path) -> None:
    """foo.cpp deliberately violates modernize-use-nullptr, which .clang-tidy
    turns into an error, so the build must fail with that diagnostic."""
    result = _cja_build(_copy_example(CLANG_TIDY_EXAMPLE, tmp_path))
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "modernize-use-nullptr" in output
