"""Tests for FetchContent command."""

import subprocess
import tarfile
import urllib.request
from pathlib import Path
from typing import Self

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command
from tests.helpers import git, include_flags


class _FakeResponse:
    """urlopen stand-in that serves a fixed archive body."""

    def __init__(self, data: bytes, *, content_length: bool = True) -> None:
        self._data = data
        self._content_length = content_length
        self._buf = b""

    def info(self) -> dict[str, str]:
        if self._content_length:
            return {"Content-Length": str(len(self._data))}
        return {}

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            data, self._buf = self._buf, b""
            return data
        data, self._buf = self._buf[:size], self._buf[size:]
        return data

    def __enter__(self) -> Self:
        self._buf = self._data
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_fetchcontent_url(tmp_path: Path) -> None:
    """Test FetchContent_Declare and FetchContent_MakeAvailable with URL."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    # Create a small library to be "fetched"
    lib_dir = tmp_path / "mylib"
    lib_dir.mkdir()
    (lib_dir / "CMakeLists.txt").write_text("add_library(mylib STATIC mylib.c)")
    (lib_dir / "mylib.c").write_text("int mylib_func() { return 0; }")

    # Package it into a tarball
    tar_path = tmp_path / "mylib.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(lib_dir, arcname="mylib")

    url = f"file://{tar_path.resolve()}"

    ctx = BuildContext(source_dir=source_dir, build_dir=tmp_path / "build")
    # Like configure()
    ctx.variables["CMAKE_CURRENT_LIST_FILE"] = (source_dir / "CMakeLists.txt").as_posix()
    commands = [
        Command(name="include", args=["FetchContent"], line=1),
        Command(name="fetchcontent_declare", args=["mylib", "URL", url], line=2),
        Command(name="fetchcontent_makeavailable", args=["mylib"], line=3),
    ]

    process_commands(commands, ctx)

    # Check that library from fetched content was added
    assert any(lib.name == "mylib" for lib in ctx.libraries)
    assert ctx.variables["mylib_POPULATED"] == "TRUE"
    assert "mylib_SOURCE_DIR" in ctx.variables
    assert ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] == source_dir.as_posix()
    assert ctx.variables["CMAKE_CURRENT_LIST_FILE"] == (source_dir / "CMakeLists.txt").as_posix()


def test_fetchcontent_source_dir_reuses_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FetchContent honors SOURCE_DIR so CPM_SOURCE_CACHE can be reused."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    build_dir = tmp_path / "build"
    cache_dir = tmp_path / "cpm-cache" / "mylib"
    cache_dir.mkdir(parents=True)
    (cache_dir / "CMakeLists.txt").write_text("add_library(mylib STATIC mylib.c)")
    (cache_dir / "mylib.c").write_text("int mylib_func() { return 0; }")

    def fail_urlopen(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("URL should not be fetched when SOURCE_DIR is populated")

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)

    ctx = BuildContext(source_dir=source_dir, build_dir=build_dir)
    commands = [
        Command(name="include", args=["FetchContent"], line=1),
        Command(
            name="fetchcontent_declare",
            args=[
                "mylib",
                "SOURCE_DIR",
                str(cache_dir),
                "URL",
                "http://example.invalid/mylib.tar.gz",
            ],
            line=2,
        ),
        Command(name="fetchcontent_makeavailable", args=["mylib"], line=3),
    ]

    process_commands(commands, ctx)

    assert any(lib.name == "mylib" for lib in ctx.libraries)
    assert Path(ctx.variables["mylib_SOURCE_DIR"]) == cache_dir
    assert not (build_dir / "_deps" / "mylib-src").exists()


def test_fetchcontent_hash(tmp_path: Path) -> None:
    """Test FetchContent with URL_HASH."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    lib_dir = tmp_path / "mylib"
    lib_dir.mkdir()
    (lib_dir / "CMakeLists.txt").write_text("add_library(mylib STATIC mylib.c)")
    (lib_dir / "mylib.c").write_text("int mylib_func() { return 0; }")

    tar_path = tmp_path / "mylib.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(lib_dir, arcname="mylib")

    import hashlib

    h = hashlib.sha256()
    h.update(tar_path.read_bytes())
    sha256_hash = h.hexdigest()

    url = f"file://{tar_path.resolve()}"
    url_hash = f"SHA256={sha256_hash}"

    ctx = BuildContext(source_dir=source_dir, build_dir=tmp_path / "build")
    commands = [
        Command(name="include", args=["FetchContent"], line=1),
        Command(
            name="fetchcontent_declare",
            args=["mylib", "URL", url, "URL_HASH", url_hash],
            line=2,
        ),
        Command(name="fetchcontent_makeavailable", args=["mylib"], line=3),
    ]

    process_commands(commands, ctx)
    assert any(lib.name == "mylib" for lib in ctx.libraries)


def test_fetchcontent_wrong_hash(tmp_path: Path) -> None:
    """Test FetchContent with wrong URL_HASH."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    lib_dir = tmp_path / "mylib"
    lib_dir.mkdir()
    (lib_dir / "CMakeLists.txt").write_text("add_library(mylib STATIC mylib.c)")
    (lib_dir / "mylib.c").write_text("int mylib_func() { return 0; }")

    tar_path = tmp_path / "mylib.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(lib_dir, arcname="mylib")

    url = f"file://{tar_path.resolve()}"
    url_hash = "SHA256=wronghash"

    ctx = BuildContext(source_dir=source_dir, build_dir=tmp_path / "build")
    commands = [
        Command(name="include", args=["FetchContent"], line=1),
        Command(
            name="fetchcontent_declare",
            args=["mylib", "URL", url, "URL_HASH", url_hash],
            line=2,
        ),
        Command(name="fetchcontent_makeavailable", args=["mylib"], line=3),
    ]

    with pytest.raises(RuntimeError, match="Hash mismatch"):
        process_commands(commands, ctx)


def test_fetchcontent_sourceforge_style_download_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """URLs ending in /download (SourceForge) still download and extract."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    lib_dir = tmp_path / "mylib"
    lib_dir.mkdir()
    (lib_dir / "CMakeLists.txt").write_text("add_library(mylib STATIC mylib.c)")
    (lib_dir / "mylib.c").write_text("int mylib_func() { return 0; }")

    tar_path = tmp_path / "mylib.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(lib_dir, arcname="mylib")
    archive_bytes = tar_path.read_bytes()

    url = "https://sourceforge.net/projects/example/files/mylib.tar.gz/download"
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *_a, **_k: _FakeResponse(archive_bytes)
    )

    ctx = BuildContext(source_dir=source_dir, build_dir=tmp_path / "build")
    commands = [
        Command(name="include", args=["FetchContent"], line=1),
        Command(name="fetchcontent_declare", args=["mylib", "URL", url], line=2),
        Command(name="fetchcontent_makeavailable", args=["mylib"], line=3),
    ]

    process_commands(commands, ctx)

    src = Path(ctx.variables["mylib_SOURCE_DIR"])
    assert (src / "CMakeLists.txt").exists()
    assert any(lib.name == "mylib" for lib in ctx.libraries)
    # Archive should be saved under its real name, not "download"
    assert (tmp_path / "build" / "_deps" / "mylib.tar.gz").exists()


def test_fetchcontent_retries_empty_src_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty *-src dir from a prior failed extract is re-populated."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    build_dir = tmp_path / "build"
    empty = build_dir / "_deps" / "mylib-src"
    empty.mkdir(parents=True)

    lib_dir = tmp_path / "mylib"
    lib_dir.mkdir()
    (lib_dir / "CMakeLists.txt").write_text("add_library(mylib STATIC mylib.c)")
    (lib_dir / "mylib.c").write_text("int mylib_func() { return 0; }")
    tar_path = tmp_path / "mylib.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(lib_dir, arcname="mylib")
    archive_bytes = tar_path.read_bytes()

    url = "https://example.com/mylib.tar.gz"
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_a, **_k: _FakeResponse(archive_bytes, content_length=False),
    )

    ctx = BuildContext(source_dir=source_dir, build_dir=build_dir)
    commands = [
        Command(name="include", args=["FetchContent"], line=1),
        Command(name="fetchcontent_declare", args=["mylib", "URL", url], line=2),
        Command(name="fetchcontent_makeavailable", args=["mylib"], line=3),
    ]
    process_commands(commands, ctx)
    assert (Path(ctx.variables["mylib_SOURCE_DIR"]) / "CMakeLists.txt").exists()


def test_fetchcontent_git_commit_hash(tmp_path: Path) -> None:
    """Test FetchContent_Declare with GIT_TAG set to a commit hash (not a branch/tag name)."""
    # Create a local bare-ish git repo to act as the remote
    remote_dir = tmp_path / "remote"
    remote_dir.mkdir()
    subprocess.run(["git", "init", str(remote_dir)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(remote_dir), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(remote_dir), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    (remote_dir / "CMakeLists.txt").write_text("add_library(mylib STATIC mylib.c)")
    (remote_dir / "mylib.c").write_text("int mylib_func() { return 0; }")
    subprocess.run(
        ["git", "-C", str(remote_dir), "add", "."], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(remote_dir), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )

    # Get the commit hash
    result = subprocess.run(
        ["git", "-C", str(remote_dir), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    commit_hash = result.stdout.strip()

    source_dir = tmp_path / "src"
    source_dir.mkdir()
    ctx = BuildContext(source_dir=source_dir, build_dir=tmp_path / "build")
    commands = [
        Command(name="include", args=["FetchContent"], line=1),
        Command(
            name="fetchcontent_declare",
            args=["mylib", "GIT_REPOSITORY", str(remote_dir), "GIT_TAG", commit_hash],
            line=2,
        ),
        Command(name="fetchcontent_makeavailable", args=["mylib"], line=3),
    ]

    process_commands(commands, ctx)

    assert ctx.variables["mylib_POPULATED"] == "TRUE"
    src_dir = ctx.variables["mylib_SOURCE_DIR"]
    assert (Path(src_dir) / "CMakeLists.txt").exists()
    assert any(lib.name == "mylib" for lib in ctx.libraries)


def _git_repo(path: Path, files: dict[str, str], submodules: list[Path]) -> None:
    """Create a git repository with a commit of the files and submodules."""
    path.mkdir()
    git(path, "init")
    for name, content in files.items():
        (path / name).write_text(content)
    for submodule in submodules:
        git(path, "submodule", "add", submodule.as_posix(), submodule.name)
    git(path, "add", ".")
    git(path, "commit", "-m", "init")


@pytest.fixture
def remote_with_submodules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A git repository with the submodules ``other`` and ``sub``, which itself
    has the submodule ``nested``."""
    # Git doesn't clone submodules from local paths by default.
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")
    repos = tmp_path / "repos"
    repos.mkdir()
    _git_repo(repos / "nested", {"nested.txt": "nested"}, [])
    _git_repo(repos / "sub", {"sub.txt": "1"}, [repos / "nested"])
    _git_repo(repos / "other", {"other.txt": "other"}, [])
    _git_repo(
        repos / "remote",
        {"CMakeLists.txt": "add_library(mylib STATIC mylib.c)", "mylib.c": ""},
        [repos / "sub", repos / "other"],
    )
    git(repos / "remote", "tag", "v1")
    return repos / "remote"


def _fetch_git(tmp_path: Path, remote: Path | str, options: list[str]) -> Path:
    """Make the repository available and return its source directory."""
    source_dir = tmp_path / "src"
    source_dir.mkdir(exist_ok=True)
    ctx = BuildContext(source_dir=source_dir, build_dir=tmp_path / "build")
    commands = [
        Command(name="include", args=["FetchContent"], line=1),
        Command(
            name="fetchcontent_declare",
            args=["mylib", "GIT_REPOSITORY", str(remote), *options],
            line=2,
        ),
        Command(name="fetchcontent_makeavailable", args=["mylib"], line=3),
    ]
    process_commands(commands, ctx, strict=True)
    return Path(ctx.variables["mylib_SOURCE_DIR"])


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ([], ["sub/sub.txt", "sub/nested/nested.txt", "other/other.txt"]),
        (["GIT_SUBMODULES", ""], []),
        # Without a value, which CPM.cmake passes on for "", it has no effect
        (["GIT_SUBMODULES"], ["sub/sub.txt", "sub/nested/nested.txt", "other/other.txt"]),
        (["GIT_SUBMODULES", "sub"], ["sub/sub.txt", "sub/nested/nested.txt"]),
        (["GIT_SUBMODULES_RECURSE", "OFF"], ["sub/sub.txt", "other/other.txt"]),
    ],
)
def test_fetchcontent_git_submodules(
    tmp_path: Path, remote_with_submodules: Path, options: list[str], expected: list[str]
) -> None:
    """Like CMake, all submodules are cloned recursively by default."""
    src_dir = _fetch_git(tmp_path, remote_with_submodules, ["GIT_TAG", "v1", *options])

    files = ["sub/sub.txt", "sub/nested/nested.txt", "other/other.txt"]
    assert [name for name in files if (src_dir / name).exists()] == expected


def test_fetchcontent_git_submodules_follow_git_tag(
    tmp_path: Path, remote_with_submodules: Path
) -> None:
    """Checking out another GIT_TAG in an existing clone updates the submodules."""
    remote = remote_with_submodules
    (remote.parent / "sub" / "sub.txt").write_text("2")
    git(remote.parent / "sub", "commit", "-am", "update")
    git(remote / "sub", "pull")
    git(remote, "commit", "-am", "update sub")
    git(remote, "tag", "v2")

    src_dir = _fetch_git(tmp_path, remote, ["GIT_TAG", "v1"])
    assert (src_dir / "sub" / "sub.txt").read_text() == "1"

    src_dir = _fetch_git(tmp_path, remote, ["GIT_TAG", "v2"])
    assert (src_dir / "sub" / "sub.txt").read_text() == "2"


@pytest.fixture
def remote_with_history(tmp_path: Path) -> Path:
    """A git repository with three commits: the tags ``v1`` and ``v2``, which
    also is the branch ``stable``, and the tip of the default branch."""
    remote = tmp_path / "remote"
    _git_repo(remote, {"CMakeLists.txt": "", "version.txt": "1"}, [])
    git(remote, "tag", "v1")
    (remote / "version.txt").write_text("2")
    git(remote, "commit", "-am", "second")
    git(remote, "tag", "v2")
    git(remote, "branch", "stable")
    (remote / "version.txt").write_text("3")
    git(remote, "commit", "-am", "third")
    return remote


def _is_shallow(src_dir: Path) -> bool:
    return git(src_dir, "rev-parse", "--is-shallow-repository") == "true"


@pytest.mark.parametrize(
    ("options", "version", "commits"),
    [
        (["GIT_TAG", "v2"], "2", 2),
        (["GIT_TAG", "v2", "GIT_SHALLOW", "OFF"], "2", 2),
        (["GIT_TAG", "v2", "GIT_SHALLOW", "TRUE"], "2", 1),
        (["GIT_TAG", "stable", "GIT_SHALLOW", "ON"], "2", 1),
        (["GIT_SHALLOW", "1"], "3", 1),
    ],
)
def test_fetchcontent_git_shallow(
    tmp_path: Path, remote_with_history: Path, options: list[str], version: str, commits: int
) -> None:
    """With GIT_SHALLOW only the commit of the tag or branch is cloned."""
    # Git ignores --depth for a local path
    src_dir = _fetch_git(tmp_path, remote_with_history.as_uri(), options)

    assert (src_dir / "version.txt").read_text() == version
    assert int(git(src_dir, "rev-list", "--count", "HEAD")) == commits


def test_fetchcontent_git_shallow_commit(
    tmp_path: Path, remote_with_history: Path
) -> None:
    """A commit can't be cloned shallowly, so the history is cloned as well."""
    commit = git(remote_with_history, "rev-parse", "v2")

    src_dir = _fetch_git(
        tmp_path, remote_with_history.as_uri(), ["GIT_TAG", commit, "GIT_SHALLOW", "TRUE"]
    )

    assert (src_dir / "version.txt").read_text() == "2"
    assert not _is_shallow(src_dir)


@pytest.mark.parametrize(
    ("tag", "version", "shallow"),
    [("v2", "2", True), ("stable", "2", True), ("v1^{commit}", "1", False)],
)
def test_fetchcontent_git_shallow_changed_git_tag(
    tmp_path: Path, remote_with_history: Path, tag: str, version: str, shallow: bool
) -> None:
    """What a shallow clone doesn't have is fetched, with the history if needed."""
    remote = remote_with_history
    if "^" in tag:
        # A commit that is neither a tag nor a branch
        tag = git(remote, "rev-parse", tag)
        git(remote, "tag", "-d", "v1")
    _fetch_git(tmp_path, remote.as_uri(), ["GIT_SHALLOW", "TRUE"])

    src_dir = _fetch_git(tmp_path, remote.as_uri(), ["GIT_TAG", tag, "GIT_SHALLOW", "TRUE"])

    assert (src_dir / "version.txt").read_text() == version
    assert _is_shallow(src_dir) == shallow


def test_fetchcontent_git_output(
    tmp_path: Path, remote_with_history: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """Git's own output is replaced by a progress bar like the one of downloads."""
    remote = remote_with_history.as_uri()
    commit = git(remote_with_history, "rev-parse", "v1")
    capfd.readouterr()

    _fetch_git(tmp_path, remote, ["GIT_TAG", "v2", "GIT_SHALLOW", "TRUE"])
    out, err = capfd.readouterr()
    assert out.startswith(f"Cloning mylib from {remote}\n")
    assert len(out.splitlines()) == 2  # The progress bar
    assert "objects" not in out
    assert err == ""

    # Nothing to do
    _fetch_git(tmp_path, remote, ["GIT_TAG", "v2", "GIT_SHALLOW", "TRUE"])
    assert capfd.readouterr() == ("", "")

    _fetch_git(tmp_path, remote, ["GIT_TAG", commit, "GIT_SHALLOW", "TRUE"])
    out, err = capfd.readouterr()
    assert out.startswith(f"Fetching mylib from {remote}\n")
    assert err == ""


def test_fetchcontent_git_submodules_output(
    tmp_path: Path, remote_with_submodules: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    capfd.readouterr()

    _fetch_git(tmp_path, remote_with_submodules, ["GIT_TAG", "v1"])

    out, err = capfd.readouterr()
    assert out.splitlines() == [
        f"Cloning mylib from {remote_with_submodules}",
        "Cloning submodule other",
        "Cloning submodule sub",
        "Cloning submodule sub/nested",
    ]
    assert err == ""


def test_fetchcontent_git_clone_failure_output(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """What git said is only shown when it fails."""
    remote = (tmp_path / "missing").as_uri()
    capfd.readouterr()

    with pytest.raises(SystemExit):
        _fetch_git(tmp_path, remote, ["GIT_TAG", "v1", "GIT_SHALLOW", "TRUE"])

    out, err = capfd.readouterr()
    assert out == f"Cloning mylib from {remote}\n"
    assert "fatal: " in err
    assert "Cloning into" not in err
    assert err.splitlines()[-1].endswith(f"error: git clone failed for {remote}")


def test_fetchcontent_git_tag_created_after_cloning(
    tmp_path: Path, remote_with_history: Path
) -> None:
    """A GIT_TAG that an existing clone doesn't know is fetched."""
    remote = remote_with_history
    _fetch_git(tmp_path, remote, ["GIT_TAG", "v2"])
    (remote / "version.txt").write_text("4")
    git(remote, "commit", "-am", "fourth")
    git(remote, "tag", "v4")

    src_dir = _fetch_git(tmp_path, remote, ["GIT_TAG", "v4"])

    assert (src_dir / "version.txt").read_text() == "4"


def test_fetchcontent_system(tmp_path: Path) -> None:
    """With SYSTEM, consumers get the include dirs of the content as -isystem."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    dep_dir = tmp_path / "dep"
    dep_dir.mkdir()
    (dep_dir / "CMakeLists.txt").write_text(
        "add_library(dep INTERFACE)\n"
        "target_include_directories(dep INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/include)\n"
        "get_directory_property(system SYSTEM)\n"
        'set(DEP_SYSTEM "${system}" CACHE INTERNAL "")\n'
    )
    (source_dir / "main.c").write_text("int main(void) { return 0; }\n")
    (source_dir / "CMakeLists.txt").write_text(
        "include(FetchContent)\n"
        "FetchContent_Declare(dep SOURCE_DIR ${CMAKE_SOURCE_DIR}/../dep SYSTEM)\n"
        "FetchContent_MakeAvailable(dep)\n"
        "add_executable(app main.c)\n"
        "target_link_libraries(app PRIVATE dep)\n"
    )

    from cja.generator import configure

    ctx = configure(source_dir, "build", strict=True)

    assert ctx.cache_values["DEP_SYSTEM"] == "TRUE"
    content = (source_dir / "build.ninja").read_text()
    assert include_flags(content, "app_main.o") == [
        f"-isystem {(dep_dir / 'include').as_posix()}"
    ]
