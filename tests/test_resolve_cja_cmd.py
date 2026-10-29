"""Tests for resolving how cja invokes itself in generated ninja rules."""

from pathlib import Path

import pytest

from cja import generator


def make_bindir(path: Path, with_script: bool) -> tuple[Path, Path]:
    """A fake bin directory with an interpreter, and a cja console script if wanted."""
    path.mkdir()
    python = path / "python"
    python.write_text("")
    script = path / "cja"
    if with_script:
        script.write_text("#!/bin/sh\n")
    return python, script


@pytest.fixture(autouse=True)
def linux(monkeypatch):
    monkeypatch.setattr(generator.platform, "system", lambda: "Linux")
    # Started by pytest, not by a cja console script, unless a test says so
    monkeypatch.setattr(generator.sys, "argv", ["pytest"])


def test_uses_cja_on_path_if_it_is_the_running_one(monkeypatch, tmp_path):
    python, script = make_bindir(tmp_path / "bin", with_script=True)
    monkeypatch.setattr(generator.shutil, "which", lambda _: str(script))
    monkeypatch.setattr(generator.sys, "executable", str(python))
    assert generator._resolve_cja_cmd() == ["cja"]


def test_uses_cja_on_path_inside_active_venv(monkeypatch, tmp_path):
    python, script = make_bindir(tmp_path / "bin", with_script=True)
    monkeypatch.setattr(generator.shutil, "which", lambda _: str(script))
    monkeypatch.setattr(generator.sys, "executable", str(python))
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path))
    assert generator._resolve_cja_cmd() == ["cja"]


def test_uses_absolute_running_cja_if_another_is_on_path(monkeypatch, tmp_path):
    """E.g. a venv's cja run without sourcing the venv, while another version is
    installed globally: regenerating the build must not switch to that one."""
    python, script = make_bindir(tmp_path / "bin", with_script=True)
    other = tmp_path / "other-cja"
    other.write_text("#!/bin/sh\n")
    monkeypatch.setattr(generator.shutil, "which", lambda _: str(other))
    monkeypatch.setattr(generator.sys, "executable", str(python))
    assert generator._resolve_cja_cmd() == [str(script)]


def test_running_cja_is_the_one_it_was_started_with(monkeypatch, tmp_path):
    """The interpreter's directory can have another cja than the running one,
    e.g. a distribution's, while the running one is a user install on PATH."""
    python, _ = make_bindir(tmp_path / "usr-bin", with_script=True)
    _, started = make_bindir(tmp_path / "local-bin", with_script=True)
    monkeypatch.setattr(generator.shutil, "which", lambda _: str(started))
    monkeypatch.setattr(generator.sys, "executable", str(python))
    monkeypatch.setattr(generator.sys, "argv", [str(started)])
    assert generator._resolve_cja_cmd() == ["cja"]


def test_prefers_adjacent_script_when_not_on_path(monkeypatch, tmp_path):
    """When cja isn't on PATH (venv not sourced), use the single-token console
    script next to the interpreter instead of multi-token `python -m cja`."""
    python, script = make_bindir(tmp_path / "bin", with_script=True)
    monkeypatch.setattr(generator.shutil, "which", lambda _: None)
    monkeypatch.setattr(generator.sys, "executable", str(python))
    assert generator._resolve_cja_cmd() == [str(script)]


def test_falls_back_to_module_invocation_without_script(monkeypatch, tmp_path):
    python, _ = make_bindir(tmp_path / "bin", with_script=False)
    monkeypatch.setattr(generator.shutil, "which", lambda _: None)
    monkeypatch.setattr(generator.sys, "executable", str(python))
    assert generator._resolve_cja_cmd() == [str(python), "-m", "cja"]
