"""Git repositories fetched by FetchContent."""

import shutil
import subprocess
from pathlib import Path


def _succeeds(*command: str) -> bool:
    """Run a git command whose failure is handled, so without its output."""
    result = subprocess.run(
        ["git", *command],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def clone(repository: str, directory: Path, tag: str | None, shallow: bool) -> None:
    """Clone a repository and check out the tag, branch or commit.

    With GIT_SHALLOW only the commit of a tag or branch is fetched, instead of
    the tips of all of them like CMake does. A commit can't be cloned that
    way, so then the history is fetched as well.
    """
    if shallow:
        branch = ["--branch", tag] if tag else []
        if _succeeds("clone", "--depth", "1", *branch, repository, str(directory)):
            return
        shutil.rmtree(directory, ignore_errors=True)
    subprocess.run(["git", "clone", repository, str(directory)], check=True)
    if tag:
        subprocess.run(["git", "-C", str(directory), "checkout", tag], check=True)


def checkout(directory: Path, tag: str) -> None:
    """Check out the tag, branch or commit in an existing clone.

    Like CMake, fetch from the remote if it isn't known yet, e.g. after
    GIT_TAG changed to a new tag.
    """
    git = ("-C", str(directory))
    if _succeeds(*git, "checkout", tag):
        return
    shallow = subprocess.run(
        ["git", *git, "rev-parse", "--is-shallow-repository"],
        check=False,
        capture_output=True,
        text=True,
    )
    if shallow.stdout.strip() == "true":
        # A shallow clone only tracks what it was cloned for.
        _succeeds(*git, "remote", "set-branches", "origin", "*")
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
        if _succeeds(*git, "fetch", "--force", *fetch) and _succeeds(
            *git, "checkout", tag
        ):
            return
    # Fails again, with git's error message this time
    subprocess.run(["git", *git, "checkout", tag], check=True)


def update_submodules(
    directory: Path, submodules: list[str] | None, recurse: bool
) -> None:
    """Update the submodules of a clone.

    Like CMake, all of them are updated unless ``submodules`` has the values of
    GIT_SUBMODULES, which lists the ones to update: none if it's empty.
    """
    if submodules == [] or not (directory / ".gitmodules").is_file():
        return
    update_cmd = ["git", "-C", str(directory), "submodule", "update", "--init"]
    if recurse:
        update_cmd.append("--recursive")
    if submodules:
        update_cmd += ["--", *submodules]
    subprocess.run(update_cmd, check=True)
