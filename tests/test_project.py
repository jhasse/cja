"""Tests for finding the CMake files of a project and its user commands."""

from pathlib import Path

import pytest

from cja.lsp.workspace import Workspace
from cja.project import cmake_files, project_command_specs, project_root

_MY_FUNC = """\
function(my_func)
  cmake_parse_arguments(ARG "QUIET" "{one_value}" "SOURCES" ${{ARGN}})
endfunction()
"""


def _write(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def test_cmake_files(tmp_path: Path) -> None:
    """Build and hidden directories are skipped, and the order is fixed."""
    _write(
        tmp_path,
        dict.fromkeys(
            [
                "sub/b/CMakeLists.txt",
                "sub/a/Helpers.CMake",
                "sub/CMakeLists.txt",
                "cmake/z.cmake",
                "cmake/a.cmake",
                "CMakeLists.txt",
                "README.txt",
                ".hidden/x.cmake",
                "build/x.cmake",
                "build-release/x.cmake",
                "node_modules/x.cmake",
                "sub/_deps/x.cmake",
                "sub/CMakeFiles/x.cmake",
                "out/CMakeCache.txt",
                "out/x.cmake",
            ],
            "",
        ),
    )

    files = [path.relative_to(tmp_path).as_posix() for path in cmake_files(tmp_path)]

    assert files == [
        "CMakeLists.txt",
        "cmake/a.cmake",
        "cmake/z.cmake",
        "sub/CMakeLists.txt",
        "sub/a/Helpers.CMake",
        "sub/b/CMakeLists.txt",
    ]


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home directory, above which no project is searched for."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def test_project_root_is_the_git_repository(home: Path) -> None:
    _write(
        home,
        {
            "repo/.git/HEAD": "",
            "repo/CMakeLists.txt": "",
            "repo/sub/CMakeLists.txt": "project(sub)\n",
            # Like the .git file of a submodule or a worktree
            "repo/submodule/.git": "gitdir: ../.git/modules/submodule\n",
            "repo/submodule/cmake/x.cmake": "",
        },
    )

    assert project_root(home / "repo" / "sub") == home / "repo"
    assert project_root(home / "repo") == home / "repo"
    assert project_root(home / "repo" / "submodule" / "cmake") == (
        home / "repo" / "submodule"
    )


def test_project_root_is_the_outermost_project_call(home: Path) -> None:
    """Without Git, also if a directory in between has no CMakeLists.txt."""
    _write(
        home,
        {
            "outer/CMakeLists.txt": "cmake_minimum_required(VERSION 3.20)\nProject (outer)\n",
            "outer/libs/inner/CMakeLists.txt": "project(inner)\n",
            "outer/libs/inner/src/CMakeLists.txt": "# project(commented out)\n",
            "outer/libs/inner/cmake/x.cmake": "",
        },
    )

    for directory in ("", "libs", "libs/inner", "libs/inner/src", "libs/inner/cmake"):
        assert project_root(home / "outer" / directory) == home / "outer"


def test_project_root_without_project_call(home: Path) -> None:
    """Then it's the nearest CMakeLists.txt, or else the directory itself."""
    _write(
        home,
        {
            "a/CMakeLists.txt": "add_subdirectory(b)\n",
            "a/b/CMakeLists.txt": "add_library(b b.c)\n",
            "a/b/cmake/x.cmake": "",
            "scripts/x.cmake": "",
        },
    )

    assert project_root(home / "a" / "b" / "cmake") == home / "a" / "b"
    assert project_root(home / "a") == home / "a"
    assert project_root(home / "scripts") == home / "scripts"


def test_project_root_is_never_the_home_directory(home: Path) -> None:
    """It could be a repository for dotfiles, with everything else below."""
    _write(
        home,
        {
            ".git/HEAD": "",
            "CMakeLists.txt": "project(stray)\n",
            "work/x.cmake": "",
        },
    )

    assert project_root(home / "work") == home / "work"
    assert project_root(home) is None
    assert project_root(home.parent) is None
    assert project_root(Path(home.anchor)) is None


def test_project_command_specs(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "CMakeLists.txt": "function(plain a b)\nendfunction()\nmy_func(NAME x)\n",
            "cmake/helpers.cmake": _MY_FUNC.format(one_value="NAME"),
            "cmake/upper.cmake": (
                "MACRO(MY_MACRO)\n"
                '  CMAKE_PARSE_ARGUMENTS(ARG "" "TARGET" "" ${ARGN})\n'
                "ENDMACRO()\n"
            ),
            # Can't be parsed
            "cmake/broken.cmake": 'function(broken)\ncmake_parse_arguments(ARG "'
            + "\n",
            "build/helpers.cmake": _MY_FUNC.format(one_value="IGNORED"),
        },
    )

    specs = project_command_specs(tmp_path)

    assert sorted(specs) == ["my_func", "my_macro"]
    assert specs["my_func"].pargs[0].flags == ("QUIET",)
    assert specs["my_func"].kwargs == {"NAME": 1, "SOURCES": "*"}
    assert specs["my_macro"].kwargs == {"TARGET": 1}


def test_project_command_specs_match_the_language_server(tmp_path: Path) -> None:
    """Also for commands with the same name, of which the last file wins."""
    _write(
        tmp_path,
        {
            "CMakeLists.txt": "project(demo)\n",
            "b/helpers.cmake": _MY_FUNC.format(one_value="FROM_B"),
            "a/helpers.cmake": _MY_FUNC.format(one_value="FROM_A"),
            "a/nested/helpers.cmake": _MY_FUNC.format(one_value="FROM_NESTED"),
            "c/other.cmake": _MY_FUNC.format(one_value="OTHER").replace("my_func", "other"),
        },
    )
    workspace = Workspace()
    workspace.scan(tmp_path)

    specs = project_command_specs(tmp_path)

    assert specs == workspace.command_specs()
    assert sorted(specs) == ["my_func", "other"]
    assert "FROM_B" in specs["my_func"].kwargs
