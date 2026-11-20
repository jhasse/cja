"""Tests for CPM.cmake, using the copy in examples/cpm."""

from pathlib import Path

import pytest

from cja.generator import configure
from tests.helpers import git

CPM_CMAKE = Path(__file__).parent.parent / "examples" / "cpm" / "cmake" / "CPM.cmake"


@pytest.mark.parametrize("package", ["gh:owner/mylib@1.2.3", "gh:owner/mylib#v1.2.3"])
def test_cpm_github_shorthand(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    package: str,
) -> None:
    """CPMAddPackage("gh:...") clones the repository into CPM_SOURCE_CACHE and
    reuses it from there, for which CPM needs find_package(Git)."""
    github = tmp_path / "github"
    repo = github / "owner" / "mylib.git"
    repo.mkdir(parents=True)
    git(repo, "init")
    (repo / "CMakeLists.txt").write_text("add_library(mylib STATIC mylib.c)\n")
    (repo / "mylib.c").write_text("int mylib(void) { return 0; }\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "init")
    git(repo, "tag", "v1.2.3")
    # Clone the local repository instead of https://github.com/owner/mylib.git
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.{github.as_posix()}/.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "https://github.com/")
    cache = tmp_path / "cache"
    monkeypatch.setenv("CPM_SOURCE_CACHE", cache.as_posix())

    source = tmp_path / "proj"
    source.mkdir()
    (source / "main.c").write_text("int main(void) { return 0; }\n")
    (source / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.31)\n"
        "project(demo C)\n"
        f"include({CPM_CMAKE.as_posix()})\n"
        f'CPMAddPackage("{package}")\n'
        "add_executable(app main.c)\n"
        "target_link_libraries(app PRIVATE mylib)\n"
    )
    monkeypatch.chdir(source)

    # The second time the package is already in the cache
    for build_dir in ("build", "build2"):
        ctx = configure(source, build_dir)

        assert ctx.variables["mylib_ADDED"] == "YES"
        src_dir = Path(ctx.variables["mylib_SOURCE_DIR"])
        assert src_dir.parent == cache / "mylib"
        assert (src_dir / "mylib.c").exists()
        assert any(lib.name == "mylib" for lib in ctx.libraries)
        assert "is dirty" not in capfd.readouterr().err
    assert len(list((cache / "mylib").glob("*/mylib.c"))) == 1
