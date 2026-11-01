"""Tests for check_language() from the bundled CheckLanguage.cmake."""

from pathlib import Path

import pytest

from cja.generator import BuildContext, configure


def _configure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str, capsys
) -> BuildContext:
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\n"
        "project(langs C CXX)\n"
        "include(CheckLanguage)\n" + body
    )
    monkeypatch.chdir(tmp_path)
    ctx = configure(tmp_path, "build", strict=True, quiet=True)
    assert "unknown module" not in capsys.readouterr().err
    return ctx


def test_check_language_unsupported_is_notfound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    ctx = _configure(
        tmp_path,
        monkeypatch,
        "check_language(CUDA)\nif(CMAKE_CUDA_COMPILER)\n  set(HAS_CUDA yes)\nendif()\n",
        capsys,
    )

    assert ctx.variables["CMAKE_CUDA_COMPILER"] == "NOTFOUND"
    assert ctx.cache_values["CMAKE_CUDA_COMPILER"] == "NOTFOUND"
    assert "HAS_CUDA" not in ctx.variables


def test_check_language_supported_uses_cja_compilers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    ctx = _configure(
        tmp_path,
        monkeypatch,
        "check_language(OBJC)\ncheck_language(OBJCXX)\ncheck_language(ASM)\n",
        capsys,
    )

    assert ctx.variables["CMAKE_OBJC_COMPILER"] == ctx.c_compiler
    assert ctx.variables["CMAKE_OBJCXX_COMPILER"] == ctx.cxx_compiler
    assert ctx.variables["CMAKE_ASM_COMPILER"] == ctx.c_compiler


def test_check_language_keeps_existing_compiler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    ctx = _configure(
        tmp_path,
        monkeypatch,
        "set(CMAKE_Fortran_COMPILER /opt/gfortran)\ncheck_language(Fortran)\n",
        capsys,
    )

    assert ctx.variables["CMAKE_Fortran_COMPILER"] == "/opt/gfortran"
