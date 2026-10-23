"""Tests for the bash completion script in completions/cja.bash."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from cja.generator import configure
from tests.helpers import copy_unignored_tree

COMPLETION_SCRIPT = Path(__file__).parent.parent / "completions" / "cja.bash"
BASH_COMPLETION = Path("/usr/share/bash-completion/bash_completion")
EXAMPLES_DIR = Path(__file__).parent.parent / "examples"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or not BASH_COMPLETION.exists(),
    reason="bash-completion is not installed",
)


def complete(line: str, cwd: Path) -> list[str]:
    """Return the completions bash offers with the cursor at the end of line."""
    # Split like bash does with the default COMP_WORDBREAKS, where "=" is a
    # word of its own
    words = re.findall(r"=|[^\s=]+", line)
    if line.endswith(" "):
        words.append("")
    script = f"""
source {BASH_COMPLETION}
source {COMPLETION_SCRIPT}
COMP_LINE="$1"
COMP_POINT=${{#COMP_LINE}}
shift
COMP_WORDS=("$@")
COMP_CWORD=$((${{#COMP_WORDS[@]}} - 1))
_comp_cmd_cja cja "${{COMP_WORDS[COMP_CWORD]}}" "${{COMP_WORDS[COMP_CWORD - 1]}}"
printf '%s\\n' "${{COMPREPLY[@]}}"
"""
    result = subprocess.run(
        ["bash", "-c", script, "bash", line, *words],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(c for c in result.stdout.splitlines() if c)


def test_subcommands(tmp_path: Path) -> None:
    assert complete("cja ", tmp_path) == ["build", "format", "lsp", "run", "test"]
    assert complete("cja --release b", tmp_path) == ["build"]


def test_options(tmp_path: Path) -> None:
    assert "--trace" in complete("cja --", tmp_path)
    assert complete("cja test --p", tmp_path) == ["--parallel"]
    assert complete("cja format --i", tmp_path) == ["--in-place"]
    assert complete("cja build -D --re", tmp_path) == []


def test_build_dirs(tmp_path: Path) -> None:
    (tmp_path / "build.ninja").touch()
    (tmp_path / "build-release.ninja").touch()
    assert complete("cja -B ", tmp_path) == ["build", "build-release"]
    assert complete("cja build --build-dir=build-", tmp_path) == ["build-release"]


def test_command_mode(tmp_path: Path) -> None:
    assert complete("cja -E copy", tmp_path) == ["copy", "copy_if_different"]


def test_script_mode(tmp_path: Path) -> None:
    (tmp_path / "script.cmake").touch()
    (tmp_path / "data.txt").touch()
    assert complete("cja -P ", tmp_path) == ["script.cmake"]
    assert complete("cja -P script.cmake ", tmp_path) == ["data.txt", "script.cmake"]


def test_format_files(tmp_path: Path) -> None:
    (tmp_path / "CMakeLists.txt").touch()
    (tmp_path / "foo.cmake").touch()
    (tmp_path / "main.cpp").touch()
    assert complete("cja format ", tmp_path) == ["CMakeLists.txt", "foo.cmake"]


@pytest.mark.skipif(shutil.which("ninja") is None, reason="ninja is not installed")
def test_build_targets(tmp_path: Path) -> None:
    copy_unignored_tree(EXAMPLES_DIR / "libmath", tmp_path)
    configure(tmp_path, "build")
    configure(tmp_path, "out")
    expected = ["all", "build/calculator", "build/libmath.a"]
    assert complete("cja build ", tmp_path) == expected
    assert complete("cja build b", tmp_path) == expected[1:]
    assert complete("cja -B out build ", tmp_path) == [
        "all",
        "out/calculator",
        "out/libmath.a",
    ]
    assert complete("cja build --release ", tmp_path) == []
