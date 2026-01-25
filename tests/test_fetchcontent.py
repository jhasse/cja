"""Tests for FetchContent command."""

import pytest
import shutil
import tarfile
from pathlib import Path
from cninja.generator import BuildContext, process_commands
from cninja.parser import Command


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
