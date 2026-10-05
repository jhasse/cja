"""Tests for FetchContent command."""

import tarfile
import urllib.request
from pathlib import Path
from typing import Self

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


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
    import subprocess

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
