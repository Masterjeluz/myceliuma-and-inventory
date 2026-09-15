"""Tests for local Git checkpoints.

Every repository is created under pytest's tmp_path. No real project path is
used or modified by these tests.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import checkpoint
from permissions import PermissionDeniedError


def git(repository: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        check=check,
    )


def make_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    repository.mkdir()
    git(repository, "init", "--quiet")
    git(repository, "config", "user.name", "Mycelium Test")
    git(repository, "config", "user.email", "test@mycelium.local")
    (repository / "README.md").write_text("# test repository\n", encoding="utf-8")
    git(repository, "add", "README.md")
    git(repository, "commit", "--quiet", "-m", "initial")
    return repository


def approval(repository: Path, approved: bool = True):
    return {
        "approved": approved,
        "action": checkpoint.CHECKPOINT_ACTION,
        "target": str(repository.resolve()),
        "request_id": "test-request",
    }


def test_inspect_repository_reports_status_cleanliness_and_head(tmp_path):
    repository = make_repository(tmp_path)
    inspection = checkpoint.inspect_repository(repository)
    assert inspection["is_repository"] is True
    assert inspection["cleanliness"] == "clean"
    assert inspection["clean"] is True
    assert inspection["status"] == ""
    assert inspection["status_lines"] == []
    assert inspection["current_head"]
    assert len(inspection["current_head"]) == 40
    assert inspection["provenance"]["source"] == "mycelium-desktop-agent:checkpoint"


def test_inspect_repository_detects_dirty_repository(tmp_path):
    repository = make_repository(tmp_path)
    (repository / "changes.txt").write_text("uncommitted", encoding="utf-8")
    inspection = checkpoint.inspect_repository(repository)
    assert inspection["cleanliness"] == "dirty"
    assert inspection["clean"] is False
    assert inspection["status_lines"]


def test_checkpoint_on_clean_repository_creates_commit(tmp_path):
    repository = make_repository(tmp_path)
    before = checkpoint.inspect_repository(repository)
    result = checkpoint.create_checkpoint(repository, approval(repository))
    after = checkpoint.inspect_repository(repository)
    assert result["previous_head"] == before["current_head"]
    assert result["checkpoint_id"] == after["current_head"]
    assert result["checkpoint_id"] != before["current_head"]
    assert result["message"].startswith("Mycelium checkpoint")
    assert after["cleanliness"] == "clean"


def test_checkpoint_contains_correct_commit_message_and_parent(tmp_path):
    repository = make_repository(tmp_path)
    before = checkpoint.inspect_repository(repository)
    result = checkpoint.create_checkpoint(
        repository,
        approval(repository),
        message="M2A safety checkpoint",
    )
    commit_message = git(repository, "show", "-s", "--format=%s", "HEAD").stdout.strip()
    parent = git(repository, "rev-parse", "HEAD^").stdout.strip()
    assert commit_message == "M2A safety checkpoint"
    assert parent == before["current_head"]
    assert result["checkpoint_id"] == git(repository, "rev-parse", "HEAD").stdout.strip()


def test_checkpoint_refuses_without_permission(tmp_path):
    repository = make_repository(tmp_path)
    before = checkpoint.inspect_repository(repository)
    denied = {
        "approved": False,
        "action": checkpoint.CHECKPOINT_ACTION,
        "target": str(repository.resolve()),
        "request_id": "test-request",
    }
    with pytest.raises(PermissionDeniedError):
        checkpoint.create_checkpoint(repository, denied)
    after = checkpoint.inspect_repository(repository)
    assert after["current_head"] == before["current_head"]


def test_checkpoint_refuses_when_permission_is_omitted(tmp_path):
    repository = make_repository(tmp_path)
    before = checkpoint.inspect_repository(repository)
    denied = {
        "approved": False,
        "action": checkpoint.CHECKPOINT_ACTION,
        "target": str(repository.resolve()),
        "request_id": "test-request",
    }
    with pytest.raises(PermissionDeniedError):
        checkpoint.create_checkpoint(
            repository,
            permission_func=lambda _action, _target, _details: denied,
        )
    after = checkpoint.inspect_repository(repository)
    assert after["current_head"] == before["current_head"]


def test_checkpoint_refuses_dirty_repository_before_permission(tmp_path):
    repository = make_repository(tmp_path)
    before = checkpoint.inspect_repository(repository)
    (repository / "dirty.txt").write_text("do not checkpoint", encoding="utf-8")
    with pytest.raises(checkpoint.DirtyRepositoryError):
        checkpoint.create_checkpoint(repository, approval(repository))
    after = checkpoint.inspect_repository(repository)
    assert after["current_head"] == before["current_head"]


def test_checkpoint_refuses_if_repository_changes_after_permission(tmp_path, monkeypatch):
    repository = make_repository(tmp_path)
    before = checkpoint.inspect_repository(repository)
    calls = {"count": 0}
    original_inspect = checkpoint.inspect_repository

    def inspect_then_change(path):
        result = original_inspect(path)
        calls["count"] += 1
        if calls["count"] == 2:
            (Path(path) / "race.txt").write_text("changed after permission", encoding="utf-8")
        return result

    monkeypatch.setattr(checkpoint, "inspect_repository", inspect_then_change)
    with pytest.raises(checkpoint.RepositoryChangedError):
        checkpoint.create_checkpoint(repository, approval(repository))
    assert checkpoint.inspect_repository(repository)["current_head"] == before["current_head"]


def test_checkpoint_never_invokes_forbidden_git_operations(tmp_path, monkeypatch):
    repository = make_repository(tmp_path)
    calls = []

    original_run_git = checkpoint._run_git

    def record(repository_path, arguments, *, check=True):
        calls.append(list(arguments))
        return original_run_git(repository_path, arguments, check=check)

    monkeypatch.setattr(checkpoint, "_run_git", record)
    checkpoint.create_checkpoint(repository, approval(repository))
    operations = {args[0] for args in calls}
    assert operations <= {"rev-parse", "status", "branch", "-c"}
    assert not (operations & checkpoint.FORBIDDEN_GIT_OPERATIONS)


def test_checkpoint_does_not_touch_real_projects(tmp_path):
    repository = make_repository(tmp_path)
    real_candidate = Path("C:/Users/Jelles/Desktop/Projects/myceliuma-and-inventory")
    assert real_candidate.exists()
    before = checkpoint.inspect_repository(repository)
    result = checkpoint.create_checkpoint(repository, approval(repository))
    after = checkpoint.inspect_repository(repository)
    assert result["previous_head"] == before["current_head"]
    assert after["current_head"] != before["current_head"]
    assert not (real_candidate / ".mycelium-test-marker").exists()


def test_checkpoint_permission_is_logged_with_provenance(tmp_path):
    repository = make_repository(tmp_path)
    log_path = tmp_path / "permission_log.jsonl"
    result = checkpoint.create_checkpoint(
        repository,
        permission_func=lambda action, target, details: checkpoint.request_checkpoint_permission(
            repository,
            input_func=lambda _prompt: "YES",
            log_path=log_path,
        ),
    )
    assert result["approval"]["provenance"]["source"] == "mycelium-desktop-agent:permission"
    assert result["approval"]["provenance"]["default"] == "deny"
    assert json.loads(log_path.read_text(encoding="utf-8"))["approved"] is True
