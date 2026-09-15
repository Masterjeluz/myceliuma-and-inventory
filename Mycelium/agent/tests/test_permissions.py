"""Tests for the explicit permission gate."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from permissions import PermissionGate, request_permission


def decisions(log_path: Path):
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


def test_permission_default_deny_without_input(tmp_path):
    log_path = tmp_path / "permissions.jsonl"
    gate = PermissionGate(log_path=log_path)
    approval = gate.request_permission("modify", "C:/tmp/project", {"reason": "test"})
    assert approval["approved"] is False
    assert approval["decision"] == "denied"
    assert approval["decision_source"] == "default-deny"
    assert decisions(log_path) == [approval]


def test_permission_default_deny(tmp_path):
    log_path = tmp_path / "permissions.jsonl"
    gate = PermissionGate(log_path=log_path, input_func=lambda _prompt: "")
    approval = gate.request_permission("modify", "C:/tmp/project", {"reason": "test"})
    assert approval["approved"] is False
    assert approval["decision"] == "denied"
    assert approval["decision_source"] == "human-input"
    assert decisions(log_path) == [approval]


def test_permission_requires_exact_yes(tmp_path):
    log_path = tmp_path / "permissions.jsonl"
    gate = PermissionGate(log_path=log_path, input_func=lambda _prompt: "YES")
    approval = gate.request_permission(
        "modify",
        "C:/tmp/project",
        {"reason": "controlled test modification"},
    )
    assert approval["approved"] is True
    assert approval["decision"] == "approved"
    assert approval["response"] == "YES"
    assert decisions(log_path)[0]["approved"] is True


def test_permission_reject_without_explicit_yes(tmp_path):
    log_path = tmp_path / "permissions.jsonl"
    gate = PermissionGate(log_path=log_path, input_func=lambda _prompt: "no")
    approval = gate.request_permission("delete", "C:/tmp/project", "test rejection")
    assert approval["approved"] is False
    assert approval["response"] == "DENY"
    assert decisions(log_path)[0]["decision"] == "denied"


def test_permission_log_has_timestamp_and_provenance(tmp_path):
    log_path = tmp_path / "permissions.jsonl"
    now = iter(["2026-01-01T00:00:00+00:00", "2026-01-01T00:00:01+00:00"])
    gate = PermissionGate(
        log_path=log_path,
        input_func=lambda _prompt: "YES",
        now=lambda: next(now),
    )
    approval = gate.request_permission(
        "checkpoint",
        "C:/tmp/project",
        {"reason": "before modification"},
    )
    logged = decisions(log_path)[0]
    assert logged["requested_at"] == "2026-01-01T00:00:00+00:00"
    assert logged["decided_at"] == "2026-01-01T00:00:01+00:00"
    assert logged["provenance"]["source"] == "mycelium-desktop-agent:permission"
    assert logged["provenance"]["mode"] == "explicit-human-confirmation"
    assert logged["provenance"]["default"] == "deny"
    assert approval == logged


def test_interactive_wrapper_requires_exact_yes(tmp_path):
    log_path = tmp_path / "permissions.jsonl"
    approval = request_permission(
        "modify",
        "C:/tmp/project",
        {"reason": "interactive test"},
        input_func=lambda _prompt: "YES",
        log_path=log_path,
    )
    assert approval["approved"] is True
    assert decisions(log_path)[0]["approved"] is True
