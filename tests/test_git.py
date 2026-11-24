"""Tests for how the Git commands of FetchContent show their progress."""

from pathlib import Path

import pytest

from cja.git import _Git


def test_git_progress_lines_move_a_progress_bar(tmp_path: Path) -> None:
    with _Git(tmp_path) as git:
        assert git._line(b"remote: Counting objects:  10% (24/239)        ") is None
        assert git._progress is not None
        task = git._progress.tasks[0]
        assert (task.description, task.completed, task.total) == (
            "Counting objects",
            24,
            239,
        )
        assert task.fields == {"size": "", "speed": ""}

        git._line(b"Receiving objects:  45% (15556/34567), 5.20 MiB | 512.00 KiB/s")
        assert (task.description, task.completed, task.total) == (
            "Receiving objects",
            15556,
            34567,
        )
        assert task.fields == {"size": "5.5 MB", "speed": "524.3 kB/s"}

        # The size stays when the next step doesn't have one
        git._line(b"Resolving deltas: 100% (5/5), done.")
        assert (task.description, task.completed, task.total) == (
            "Resolving deltas",
            5,
            5,
        )
        assert task.fields["size"] == "5.5 MB"
    assert git._progress is None


@pytest.mark.parametrize(
    "line",
    [
        "remote: Enumerating objects: 239, done.",
        "remote: Total 239 (delta 5), reused 158 (delta 4), pack-reused 0 (from 0)",
        "fatal: repository 'https://example.com/x.git/' not found",
        "warning: --depth is ignored in local clones; use file:// instead.",
    ],
)
def test_git_messages_are_not_progress(tmp_path: Path, line: str) -> None:
    with _Git(tmp_path) as git:
        assert git._line(f"{line}        ".encode()) == line
        assert git._progress is None


def test_git_names_the_submodules_it_clones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with _Git(tmp_path) as git:
        assert git._line(f"Cloning into '{tmp_path.as_posix()}'...".encode()) is None
        assert capsys.readouterr().out == ""

        nested = tmp_path / "sub" / "nested"
        assert git._line(f"Cloning into '{nested.as_posix()}'...".encode()) is None
        assert capsys.readouterr().out == "Cloning submodule sub/nested\n"
