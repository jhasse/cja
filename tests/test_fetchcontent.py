"""Tests for FetchContent command."""

import tarfile
import urllib.request
from pathlib import Path

import pytest

from cja.generator import BuildContext, process_commands
from cja.parser import Command


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
    assert ctx.variables["CMAKE_CURRENT_SOURCE_DIR"] == str(source_dir)
    assert ctx.variables["CMAKE_CURRENT_LIST_FILE"] == str(source_dir / "CMakeLists.txt")


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

    class _FakeResponse:
        def info(self) -> dict[str, str]:
            return {"Content-Length": str(len(archive_bytes))}

        def read(self, size: int = -1) -> bytes:
            if size < 0:
                data, self._buf = self._buf, b""
                return data
            data, self._buf = self._buf[:size], self._buf[size:]
            return data

        def __enter__(self) -> "_FakeResponse":
            self._buf = archive_bytes
            return self

        def __exit__(self, *args: object) -> None:
            return None

    url = "https://sourceforge.net/projects/example/files/mylib.tar.gz/download"
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _FakeResponse())

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

    class _FakeResponse:
        def info(self) -> dict[str, str]:
            return {}

        def read(self, size: int = -1) -> bytes:
            if size < 0:
                data, self._buf = self._buf, b""
                return data
            data, self._buf = self._buf[:size], self._buf[size:]
            return data

        def __enter__(self) -> "_FakeResponse":
            self._buf = archive_bytes
            return self

        def __exit__(self, *args: object) -> None:
            return None

    url = "https://example.com/mylib.tar.gz"
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _FakeResponse())

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
