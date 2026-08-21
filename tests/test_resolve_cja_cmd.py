"""Tests for resolving how cja invokes itself in generated ninja rules."""

from cja import generator


def test_uses_cja_on_path_outside_venv(monkeypatch):
    monkeypatch.setattr(generator.shutil, "which", lambda _: "/usr/bin/cja")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(generator.platform, "system", lambda: "Linux")
    assert generator._resolve_cja_cmd() == ["cja"]


def test_uses_absolute_cja_inside_active_venv(monkeypatch):
    monkeypatch.setattr(generator.shutil, "which", lambda _: "/venv/bin/cja")
    monkeypatch.setenv("VIRTUAL_ENV", "/venv")
    monkeypatch.setattr(generator.platform, "system", lambda: "Linux")
    assert generator._resolve_cja_cmd() == ["/venv/bin/cja"]


def test_prefers_adjacent_script_when_not_on_path(monkeypatch, tmp_path):
    """When cja isn't on PATH (venv not sourced), use the single-token console
    script next to the interpreter instead of multi-token `python -m cja`."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "cja"
    script.write_text("#!/bin/sh\n")
    python = bindir / "python"
    python.write_text("")

    monkeypatch.setattr(generator.shutil, "which", lambda _: None)
    monkeypatch.setattr(generator.sys, "executable", str(python))
    monkeypatch.setattr(generator.platform, "system", lambda: "Linux")

    assert generator._resolve_cja_cmd() == [str(script)]


def test_falls_back_to_module_invocation_without_script(monkeypatch, tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    python = bindir / "python"
    python.write_text("")

    monkeypatch.setattr(generator.shutil, "which", lambda _: None)
    monkeypatch.setattr(generator.sys, "executable", str(python))
    monkeypatch.setattr(generator.platform, "system", lambda: "Linux")

    assert generator._resolve_cja_cmd() == [str(python), "-m", "cja"]
