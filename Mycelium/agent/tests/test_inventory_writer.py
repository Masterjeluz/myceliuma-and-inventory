"""Tests for the approval-gated M2B writer (inventory_writer.py).

All INVENTory interaction uses in-process fakes; the checkpoint layer uses
injected fakes. No HTTP, no database, no real project is touched. Every
refusal test asserts zero client calls.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import inventory_bridge as bridge
import inventory_writer as writer
from inventory_writer import (
    IMPORT_ACTION,
    WriteRefusedError,
    request_approval_and_write,
    validate_project_payload,
    write_approved_mapping,
)
from mapping_store import MappingStore

STAMP = "2026-09-11T00:00:00+00:00"


class FakeInventoryClient:
    def __init__(self, proj_id="proj_test123"):
        self.calls = []
        self.proj_id = proj_id

    def create_project(self, payload):
        self.calls.append(dict(payload))
        return {"id": self.proj_id, "name": payload["name"]}


_dir_counter = {"n": 0}


def make_dir(tmp_path, name=None):
    _dir_counter["n"] += 1
    target = tmp_path / (name or f"proj{_dir_counter['n']}")
    target.mkdir(exist_ok=True)
    return str(target)


def valid_payload(name="alpha"):
    return {
        "name": name,
        "description": "synthetic test project",
        "status": "planned",
        "provenance": {
            "source_type": "imported",
            "creator_id": "mycelium-desktop-agent:inventory-bridge",
            "human_verified": False,
        },
    }


def import_approval(target, approved=True):
    return {"approved": approved, "action": IMPORT_ACTION,
            "target": target, "request_id": "test-req"}


def checkpoint_approval(target, approved=True):
    return {"approved": approved, "action": "create_git_checkpoint",
            "target": target, "request_id": "test-ckpt"}


def call_writer(tmp_path, status="proposed", is_git=False, **overrides):
    desktop = make_dir(tmp_path)
    params = {
        "desktop_id": "abc123",
        "desktop_path": desktop,
        "is_git": is_git,
        "payload": valid_payload(),
        "mapping_status": status,
        "approval": import_approval(desktop),
        "inventory_client": FakeInventoryClient(),
        "store": MappingStore(),
        "allowed_roots": [str(tmp_path)],
        "now": lambda: STAMP,
    }
    params.update(overrides)
    return params


# --- refusals: zero writes -----------------------------------------------------

def test_denied_approval_writes_nothing(tmp_path):
    params = call_writer(tmp_path)
    params["approval"] = import_approval(params["desktop_path"], approved=False)
    with pytest.raises(WriteRefusedError):
        write_approved_mapping(**params)
    assert params["inventory_client"].calls == []


def test_missing_approval_writes_nothing(tmp_path):
    params = call_writer(tmp_path, approval=None)
    with pytest.raises(WriteRefusedError):
        write_approved_mapping(**params)
    assert params["inventory_client"].calls == []


def test_wrong_action_approval_writes_nothing(tmp_path):
    params = call_writer(tmp_path)
    params["approval"] = {"approved": True, "action": "something_else",
                          "target": params["desktop_path"]}
    with pytest.raises(WriteRefusedError):
        write_approved_mapping(**params)
    assert params["inventory_client"].calls == []


def test_approval_for_other_target_writes_nothing(tmp_path):
    params = call_writer(tmp_path)
    params["approval"] = import_approval(str(tmp_path / "other"))
    with pytest.raises(WriteRefusedError):
        write_approved_mapping(**params)
    assert params["inventory_client"].calls == []


def test_non_canonical_target_writes_nothing(tmp_path):
    outside = make_dir(tmp_path, "outside")
    params = call_writer(tmp_path)
    params["desktop_path"] = outside
    params["approval"] = import_approval(outside)
    params["allowed_roots"] = [str(tmp_path / "workspace")]
    (tmp_path / "workspace").mkdir()
    with pytest.raises(WriteRefusedError):
        write_approved_mapping(**params)
    assert params["inventory_client"].calls == []


def test_empty_allowed_roots_deny_by_default(tmp_path):
    params = call_writer(tmp_path, allowed_roots=[])
    with pytest.raises(WriteRefusedError):
        write_approved_mapping(**params)
    assert params["inventory_client"].calls == []


def test_missing_directory_writes_nothing(tmp_path):
    params = call_writer(tmp_path)
    ghost = str(tmp_path / "ghost")
    params["desktop_path"] = ghost
    params["approval"] = import_approval(ghost)
    with pytest.raises(WriteRefusedError):
        write_approved_mapping(**params)
    assert params["inventory_client"].calls == []


def test_non_writable_status_writes_nothing(tmp_path):
    for status in ("conflict", "copy", "unmapped", "rejected", "mapped"):
        params = call_writer(tmp_path, status=status)
        with pytest.raises(WriteRefusedError):
            write_approved_mapping(**params)
        assert params["inventory_client"].calls == []


def test_checkpoint_failure_writes_nothing(tmp_path):
    order = []

    def fail_checkpoint(repository, approval, message=None):
        order.append("checkpoint")
        raise RuntimeError("git exploded")

    class RecordingClient(FakeInventoryClient):
        def create_project(self, payload):
            order.append("create")
            return super().create_project(payload)

    desktop = make_dir(tmp_path)
    client = RecordingClient()
    with pytest.raises(WriteRefusedError):
        write_approved_mapping(
            desktop_id="abc123", desktop_path=desktop, is_git=True,
            payload=valid_payload(), mapping_status="proposed",
            approval=import_approval(desktop),
            checkpoint_approval=checkpoint_approval(str(Path(desktop).resolve())),
            inventory_client=client, store=MappingStore(),
            allowed_roots=[str(tmp_path)], checkpoint_func=fail_checkpoint,
            now=lambda: STAMP,
        )
    assert order == ["checkpoint"]
    assert client.calls == []


def test_git_without_checkpoint_approval_writes_nothing(tmp_path):
    params = call_writer(tmp_path, is_git=True, checkpoint_approval=None,
                         checkpoint_func=lambda *a, **k: {"checkpoint_id": "x"})
    with pytest.raises(WriteRefusedError):
        write_approved_mapping(**params)
    assert params["inventory_client"].calls == []


def test_invalid_payloads_write_nothing(tmp_path):
    bad_payloads = [
        dict(valid_payload(), status="shipped"),
        dict(valid_payload(), id="proj_sneaky"),
        dict(valid_payload(), provenance={"source_type": "user-created",
                                          "human_verified": True}),
        dict(valid_payload(), provenance={"source_type": "imported",
                                          "human_verified": True}),
        "not-a-dict",
    ]
    for bad in bad_payloads:
        params = call_writer(tmp_path, payload=bad)
        with pytest.raises(WriteRefusedError):
            write_approved_mapping(**params)
        assert params["inventory_client"].calls == []


def test_server_response_without_proj_id_stores_nothing(tmp_path):
    params = call_writer(tmp_path)
    params["inventory_client"] = FakeInventoryClient(proj_id="nope")
    with pytest.raises(WriteRefusedError):
        write_approved_mapping(**params)
    assert params["store"].get("abc123") is None


# --- success paths ---------------------------------------------------------------

def test_successful_approval_creates_exactly_one(tmp_path):
    params = call_writer(tmp_path)
    result = write_approved_mapping(**params)
    assert result["writes"] == 1
    assert result["mapping_status"] == "mapped"
    assert result["inventory_project_id"] == "proj_test123"
    assert result["checkpoint_id"] is None
    assert len(params["inventory_client"].calls) == 1
    sent = params["inventory_client"].calls[0]
    assert sent["provenance"]["source_type"] == "imported"
    assert sent["provenance"]["human_verified"] is False
    assert "id" not in sent
    stored = params["store"].get("abc123")
    assert stored["mapping_status"] == "mapped"
    assert stored["inventory_project_id"] == "proj_test123"


def test_git_success_checkpoints_before_create(tmp_path):
    order = []

    def fake_checkpoint(repository, approval, message=None):
        order.append("checkpoint")
        return {"checkpoint_id": "deadbeef", "repository": str(repository)}

    class RecordingClient(FakeInventoryClient):
        def create_project(self, payload):
            order.append("create")
            return super().create_project(payload)

    desktop = make_dir(tmp_path)
    client = RecordingClient()
    result = write_approved_mapping(
        desktop_id="abc123", desktop_path=desktop, is_git=True,
        payload=valid_payload(), mapping_status="nested",
        approval=import_approval(desktop),
        checkpoint_approval=checkpoint_approval(str(Path(desktop).resolve())),
        inventory_client=client, store=MappingStore(),
        allowed_roots=[str(tmp_path)], checkpoint_func=fake_checkpoint,
        now=lambda: STAMP,
    )
    assert order == ["checkpoint", "create"]
    assert result["checkpoint_id"] == "deadbeef"
    assert result["writes"] == 1


def test_repeat_create_is_idempotent(tmp_path):
    params = call_writer(tmp_path)
    first = write_approved_mapping(**params)
    assert first["writes"] == 1
    second = write_approved_mapping(**params)
    assert second["mapping_status"] == "already_mapped"
    assert second["writes"] == 0
    assert second["inventory_project_id"] == "proj_test123"
    assert len(params["inventory_client"].calls) == 1


# --- interactive gate ---------------------------------------------------------------

def test_request_flow_approves_and_writes_once(tmp_path):
    desktop = make_dir(tmp_path)
    client = FakeInventoryClient()

    def yes(action, target, details=None, **kwargs):
        return {"approved": True, "action": action,
                "target": target, "request_id": "yes"}

    result = request_approval_and_write(
        desktop_id="abc123", desktop_path=desktop, is_git=False,
        payload=valid_payload(), mapping_status="proposed",
        inventory_client=client, store=MappingStore(),
        allowed_roots=[str(tmp_path)], permission_func=yes,
        input_func=lambda prompt: "YES", now=lambda: STAMP,
    )
    assert result["writes"] == 1
    assert len(client.calls) == 1


def test_request_flow_default_denies_without_input(tmp_path):
    from permissions import request_permission
    desktop = make_dir(tmp_path)
    client = FakeInventoryClient()
    with pytest.raises(WriteRefusedError):
        request_approval_and_write(
            desktop_id="abc123", desktop_path=desktop, is_git=False,
            payload=valid_payload(), mapping_status="proposed",
            inventory_client=client, store=MappingStore(),
            allowed_roots=[str(tmp_path)],
            permission_func=request_permission,
            input_func=None, log_path=str(tmp_path / "perm.jsonl"),
            now=lambda: STAMP,
        )
    assert client.calls == []


# --- dry-run stays write-free ----------------------------------------------------------

def test_dry_run_remains_write_free(tmp_path):
    index = {
        "computer": "PC-TEST",
        "provenance": {},
        "projects": [{
            "id": "abc123", "path": "C:/dev/alpha", "name": "alpha",
            "is_backup_copy": False, "is_nested": False, "parent_id": None,
            "relations": {"parent_id": None, "nested_children_ids": [],
                          "same_remote_ids": [], "shared_name_ids": [],
                          "possible_copy_ids": []},
        }],
    }
    plan = bridge.build_plan(index, now=lambda: STAMP)
    assert plan["writes_performed"] == 0
    assert plan["summary"]["writes_performed"] == 0
