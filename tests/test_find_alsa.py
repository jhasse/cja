"""Tests for find_package(ALSA) using the bundled FindALSA.cmake."""

from pathlib import Path

import pytest

from cja.generator import configure


def _make_prefix(root: Path) -> Path:
    prefix = root / "alsa"
    (prefix / "include" / "alsa").mkdir(parents=True)
    (prefix / "include" / "alsa" / "asoundlib.h").write_text("/* asoundlib */\n")
    (prefix / "include" / "alsa" / "version.h").write_text(
        '#define SND_LIB_VERSION_STR\t"1.2.11"\n'
    )
    (prefix / "lib").mkdir()
    (prefix / "lib" / "libasound.a").write_bytes(b"!<arch>\n")
    return prefix


def test_find_alsa(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prefix = _make_prefix(tmp_path)
    source = tmp_path / "proj"
    source.mkdir()
    (source / "main.c").write_text("int main(void) { return 0; }\n")
    (source / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(alsa C)\n"
        "find_package(ALSA MODULE REQUIRED)\n"
        "add_executable(app main.c)\n"
        "target_link_libraries(app PRIVATE ALSA::ALSA)\n"
    )
    monkeypatch.chdir(source)

    ctx = configure(
        source,
        "build",
        variables={"CMAKE_PREFIX_PATH": prefix.as_posix()},
        quiet=True,
    )

    assert ctx.variables["ALSA_FOUND"] == "TRUE"
    assert ctx.variables["ALSA_VERSION"] == "1.2.11"
    assert Path(ctx.variables["ALSA_INCLUDE_DIR"]) == prefix / "include"
    assert "ALSA::ALSA" in ctx.imported_targets
    assert f"{prefix.as_posix()}/lib/libasound.a" in (source / "build.ninja").read_text()
