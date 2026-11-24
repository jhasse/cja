"""Git repositories fetched by FetchContent."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import TracebackType
from typing import Self

from rich import filesize
from rich.progress import (
    BarColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
)

# A progress line of git, e.g.
# "Receiving objects:  45% (15556/34567), 5.20 MiB | 10.39 MiB/s"
_PROGRESS_RE = re.compile(
    r"(?:remote: )?(?P<phase>[A-Z][a-z]+(?: [a-z]+)+): +\d+% "
    r"\((?P<done>\d+)/(?P<total>\d+)\)"
    r"(?:, (?P<size>[\d.]+ \w+) \| (?P<speed>[\d.]+ \w+)/s)?"
)
_CLONING_RE = re.compile(r"Cloning into '(?P<path>.+)'\.\.\.")
_UNITS = {"bytes": 1, "KiB": 2**10, "MiB": 2**20, "GiB": 2**30}


def _size(text: str) -> str:
    """Format a size that git printed, e.g. ``5.20 MiB``, like a download."""
    number, unit = text.split()
    return filesize.decimal(int(float(number) * _UNITS.get(unit, 1)))


class _Git:
    """Runs git commands and shows their progress like the download of an archive.

    Git's own output is hidden: its progress lines move a progress bar, and the
    other ones are only printed if a command fails, apart from warnings.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._progress: Progress | None = None
        self._task = TaskID(0)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._finish()

    def run(self, *args: str, check: bool = True) -> bool:
        """Run git and return whether it succeeded.

        With ``check`` a failure raises CalledProcessError after printing what
        git said. Without, the caller handles the failure, so it's silent.
        """
        command = ["git", "-c", "advice.detachedHead=false", *args]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            # Untranslated, as the output is parsed
            env={**os.environ, "LC_ALL": "C"},
        )
        assert process.stdout is not None
        output = process.stdout.fileno()
        messages: list[str] = []
        pending = b""
        # Git ends its progress lines with a carriage return to overwrite them
        while chunk := os.read(output, 65536):
            *lines, pending = re.split(rb"[\r\n]", pending + chunk)
            messages += filter(None, map(self._line, lines))
        messages += filter(None, [self._line(pending)])
        returncode = process.wait()
        if returncode == 0:
            warnings = [m for m in messages if m.startswith("warning:")]
            self._print_messages(warnings)
            return True
        if check:
            self._print_messages(messages)
            raise subprocess.CalledProcessError(returncode, command)
        return False

    def _print_messages(self, messages: list[str]) -> None:
        if messages:
            self._finish()
            sys.stdout.flush()
            print("\n".join(messages), file=sys.stderr)

    def _line(self, raw: bytes) -> str | None:
        """Handle a line of git's output and return it unless it's progress."""
        line = raw.decode(errors="replace").strip()
        if match := _PROGRESS_RE.match(line):
            self._advance(match)
            return None
        if match := _CLONING_RE.fullmatch(line):
            path = os.path.relpath(
                os.path.realpath(match["path"]), os.path.realpath(self._directory)
            )
            if path != ".":
                # A submodule gets its own progress bar
                self._finish()
                print(f"Cloning submodule {Path(path).as_posix()}")
            return None
        return line

    def _advance(self, match: re.Match[str]) -> None:
        if self._progress is None:
            self._progress = Progress(
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                TextColumn("[progress.download]{task.fields[size]}"),
                TextColumn("[progress.data.speed]{task.fields[speed]}"),
                "•",
                TimeRemainingColumn(),
            )
            self._task = self._progress.add_task("", size="", speed="")
            self._progress.start()
        task = self._progress.tasks[self._task]
        if task.description != match["phase"]:
            # The next step, like resolving deltas after receiving objects
            self._progress.reset(self._task, description=match["phase"])
        self._progress.update(
            self._task, completed=int(match["done"]), total=int(match["total"])
        )
        if match["size"]:
            self._progress.update(
                self._task,
                size=_size(match["size"]),
                speed=f"{_size(match['speed'])}/s",
            )

    def _finish(self) -> None:
        """Leave the progress bar completed, like the one of a download."""
        if self._progress is not None:
            task = self._progress.tasks[self._task]
            self._progress.update(self._task, description="", completed=task.total)
            self._progress.stop()
            self._progress = None


def clone(repository: str, directory: Path, tag: str | None, shallow: bool) -> None:
    """Clone a repository and check out the tag, branch or commit.

    With GIT_SHALLOW only the commit of a tag or branch is fetched, instead of
    the tips of all of them like CMake does. A commit can't be cloned that
    way, so then the history is fetched as well.
    """
    with _Git(directory) as git:
        target = (repository, str(directory))
        if shallow:
            branch = ["--branch", tag] if tag else []
            if git.run(
                "clone", "--progress", "--depth", "1", *branch, *target, check=False
            ):
                return
            shutil.rmtree(directory, ignore_errors=True)
        git.run("clone", "--progress", *target)
        if tag:
            git.run("-C", str(directory), "checkout", "--progress", tag)


def checkout(directory: Path, tag: str, fetching: str) -> None:
    """Check out the tag, branch or commit in an existing clone.

    Like CMake, fetch from the remote if it isn't known yet, e.g. after
    GIT_TAG changed to a new tag. ``fetching`` is printed before doing that.
    """
    with _Git(directory) as git:
        repo = ("-C", str(directory))
        if git.run(*repo, "checkout", "--progress", tag, check=False):
            return
        print(fetching)
        shallow = subprocess.run(
            ["git", *repo, "rev-parse", "--is-shallow-repository"],
            check=False,
            capture_output=True,
            text=True,
        )
        if shallow.stdout.strip() == "true":
            # A shallow clone only tracks what it was cloned for.
            git.run(*repo, "remote", "set-branches", "origin", "*", check=False)
            # Stay shallow if possible: first try a tag, then the tips of all
            # branches and tags, and only then get the history, e.g. for a commit.
            fetches = [
                ["--depth", "1", "origin", "tag", tag],
                ["--depth", "1", "--tags", "origin"],
                ["--unshallow", "--tags", "origin"],
            ]
        else:
            fetches = [["--tags", "origin"]]
        for fetch in fetches:
            if git.run(
                *repo, "fetch", "--progress", "--force", *fetch, check=False
            ) and git.run(*repo, "checkout", "--progress", tag, check=False):
                return
        # Fails again, with git's error message this time
        git.run(*repo, "checkout", tag)


def update_submodules(
    directory: Path, submodules: list[str] | None, recurse: bool
) -> None:
    """Update the submodules of a clone.

    Like CMake, all of them are updated unless ``submodules`` has the values of
    GIT_SUBMODULES, which lists the ones to update: none if it's empty.
    """
    if submodules == [] or not (directory / ".gitmodules").is_file():
        return
    update = ["-C", str(directory), "submodule", "update", "--init", "--progress"]
    if recurse:
        update.append("--recursive")
    if submodules:
        update += ["--", *submodules]
    with _Git(directory) as git:
        git.run(*update)
