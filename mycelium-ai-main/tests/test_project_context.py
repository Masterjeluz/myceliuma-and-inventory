"""Project context tests (Fase L/Q).

Explicit contexts validate directories; the default resolves from
environment or cwd without hardcoding one project.
"""

import os

import pytest

from coordinator.app.project_context import default_context, new_context


def test_explicit_context_needs_real_dirs(tmp_path):
    context = new_context("prj-camper", "Camper", str(tmp_path))
    assert context.repository == str(tmp_path).replace("\\", "\\")
    assert context.working_directory
    with pytest.raises(ValueError):
        new_context("prj-x", "X", str(tmp_path / "missing"))
    with pytest.raises(ValueError):
        new_context("prj-x", "  ", str(tmp_path))


def test_default_context_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_PROJECT_ROOT", str(tmp_path))
    context = default_context()
    assert context.repository == os.path.abspath(str(tmp_path))
    assert context.name


def test_default_context_falls_back_to_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("MYCELIUM_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    context = default_context()
    assert context.repository == os.path.abspath(str(tmp_path))


def test_default_context_refuses_missing_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_PROJECT_ROOT",
                       str(tmp_path / "missing"))
    with pytest.raises(ValueError):
        default_context()


def test_context_carries_no_secrets():
    context = new_context("prj-a", "A", os.getcwd())
    assert "secret" not in context.model_dump()
    assert context.provenance.human_verified is True
