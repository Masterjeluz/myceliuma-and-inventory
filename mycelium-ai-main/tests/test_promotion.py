"""Tests for M7.1 staged to queued promotion gate (decision + one UPDATE).

Coordinator database is always a tmp database via MYCELIUM_DATABASE_PATH.
Promotion flips exactly one staged row to queued; every other situation
fails closed with the row untouched.
"""
import os
from pathlib import Path

import pytest

from coordinator.app.adapters import ReferenceNoopAdapter
from coordinator.app.adapter_contracts import AdapterRequest
from coordinator.app.approval import approve, decide, reject, request_approval
from coordinator.app.promotion import (
    PromotionAudit,
    PromotionRequest,
    promote,
    staged_fingerprint,
)
from coordinator.app.proposal_tasks import proposal_fingerprint, proposal_to_task
from coordinator.app.task_queue_bridge import STAGED_KIND, STAGED_STATUS, stage_task

PROV = {"source_type": "user-created", "creator_id": "tester",
        "human_verified": True}
MODEL = {"model_id": "mod_cam", "model_type": "vision",
         "capabilities": ["ocr"]}
REQUIRED = ["ocr"]
SNAPSHOT = ["ocr"]


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH", str(tmp_path / "m71.db"))
    from coordinator.app.database import init_database
    init_database()
    return str(tmp_path / "m71.db")


def make_chain():
    adapter = ReferenceNoopAdapter()
    request = AdapterRequest(request_id="req-71", adapter_id="reference-noop",
                             model_id="mod_cam", node_id="node-7",
                             task_id="task_71",
                             input={"object_id": "obj_1"},
                             provenance=dict(PROV))
    proposal = adapter.propose(request)
    approval = approve(request_approval(proposal), proposal)
    task = proposal_to_task(proposal, approval,
                            approved_fingerprint=proposal_fingerprint(proposal),
                            task_type="inspect")
    return proposal, approval, task


def register_node(node_id="node-7", capabilities=("ocr",)):
    from coordinator.app.database import connection, dump
    with connection() as db:
        db.execute(
            """INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'online')""",
            (node_id, "host", "worker", dump(list(capabilities)), 2, 1024,
             "solar", "2026-01-01T00:00:00+00:00"))


def stage(task):
    return stage_task(task)


def make_promotion_request(staged, task, node_id="node-7"):
    task_data = task.model_dump(mode="json")
    return PromotionRequest(
        promotion_request_id="promo-1",
        staging_key=f"{task.proposal_id}:{task.request_id}:{task.proposal_fingerprint}",
        queue_id=staged.queue_id,
        proposal_fingerprint=task.proposal_fingerprint,
        staged_fingerprint=staged_fingerprint(task_data),
        selected_node_id=node_id,
        required_capabilities=list(REQUIRED),
        model=dict(MODEL),
        adapter_id="reference-noop",
        capability_snapshot=list(SNAPSHOT),
    )


def fresh_approval(proposal):
    return approve(request_approval(proposal), proposal, decided_by="operator")


def setup(isolated_db):
    proposal, _, task = make_chain()
    register_node()
    staged = stage(task)
    approval = fresh_approval(proposal)
    request = make_promotion_request(staged, task)
    return proposal, approval, task, staged, request


def row(queue_id):
    from coordinator.app.database import connection
    with connection() as db:
        return db.execute("SELECT * FROM tasks WHERE id=?",
                          (queue_id,)).fetchone()


# --- happy path ----------------------------------------------------------------------------

def test_valid_promotion(isolated_db):
    proposal, approval, task, staged, request = setup(isolated_db)
    audit = promote(request, approval)
    assert isinstance(audit, PromotionAudit)
    assert audit.result == "queued"
    assert audit.promotion_request_id == "promo-1"
    assert audit.staging_key == request.staging_key
    assert audit.queue_id == staged.queue_id
    assert audit.original_fingerprint == task.proposal_fingerprint
    assert audit.current_fingerprint == request.staged_fingerprint
    assert audit.selected_node_id == "node-7"
    assert audit.capability_snapshot == ["ocr"]
    assert audit.approval == approval
    assert audit.provenance.human_verified is False
    stored = row(staged.queue_id)
    assert stored["status"] == "queued"
    assert stored["kind"] == STAGED_KIND


# --- refusals -----------------------------------------------------------------------------------

def test_missing_approval_denies(isolated_db):
    _, _, _, staged, request = setup(isolated_db)
    with pytest.raises(ValueError):
        promote(request, None)


def test_non_yes_approval_denies(isolated_db):
    proposal, _, _, staged, request = setup(isolated_db)
    denied = reject(request_approval(proposal), proposal)
    with pytest.raises(ValueError):
        promote(request, denied)
    denied = decide(request_approval(proposal), proposal, "NO")
    with pytest.raises(ValueError):
        promote(request, denied)
    assert row(staged.queue_id)["status"] == STAGED_STATUS


def test_wrong_promotion_request_id_denies(isolated_db):
    setup(isolated_db)
    with pytest.raises(Exception):
        PromotionRequest(
            promotion_request_id="ab", staging_key="x", queue_id=1,
            proposal_fingerprint="0" * 64, staged_fingerprint="0" * 64,
            selected_node_id="node-7", required_capabilities=[],
            model=dict(MODEL), adapter_id="reference-noop",
            capability_snapshot=[])


def test_wrong_staging_key_denies(isolated_db):
    proposal, approval, task, staged, request = setup(isolated_db)
    bad = request.model_copy(update={"staging_key": "prop-x:req-71:" + "0" * 64})
    with pytest.raises(ValueError):
        promote(bad, approval)
    assert row(staged.queue_id)["status"] == STAGED_STATUS


def test_fingerprint_mismatch_denies(isolated_db):
    proposal, approval, task, staged, request = setup(isolated_db)
    bad = request.model_copy(update={"proposal_fingerprint": "0" * 64})
    with pytest.raises(ValueError):
        promote(bad, approval)
    assert row(staged.queue_id)["status"] == STAGED_STATUS


def test_modified_staged_payload_denies(isolated_db):
    import json
    proposal, approval, task, staged, request = setup(isolated_db)
    from coordinator.app.database import connection, dump, load
    with connection() as db:
        payload = load(db.execute("SELECT payload FROM tasks WHERE id=?",
                                  (staged.queue_id,)).fetchone()["payload"])
        payload["task"]["expected_output"] = "Something entirely different"
        db.execute("UPDATE tasks SET payload=? WHERE id=?",
                   (dump(payload), staged.queue_id))
    with pytest.raises(ValueError):
        promote(request, approval)
    assert row(staged.queue_id)["status"] == STAGED_STATUS


def test_unknown_node_denies(isolated_db):
    proposal, approval, task, staged, request = setup(isolated_db)
    bad = request.model_copy(update={"selected_node_id": "node-ghost"})
    with pytest.raises(ValueError):
        promote(bad, approval)
    assert row(staged.queue_id)["status"] == STAGED_STATUS


def test_capability_mismatch_denies(isolated_db):
    proposal, approval, task, staged, request = setup(isolated_db)
    register_node(node_id="node-weak", capabilities=("printer",))
    bad = request.model_copy(update={"selected_node_id": "node-weak"})
    with pytest.raises(ValueError):
        promote(bad, approval)
    assert row(staged.queue_id)["status"] == STAGED_STATUS


def test_changed_snapshot_denies(isolated_db):
    proposal, approval, task, staged, request = setup(isolated_db)
    bad = request.model_copy(update={"capability_snapshot": ["ocr", "lidar"]})
    with pytest.raises(ValueError):
        promote(bad, approval)
    assert row(staged.queue_id)["status"] == STAGED_STATUS


def test_second_promotion_denies(isolated_db):
    proposal, approval, task, staged, request = setup(isolated_db)
    first = promote(request, approval)
    assert first.result == "queued"
    with pytest.raises(ValueError):
        promote(request, approval)
    assert row(staged.queue_id)["status"] == "queued"


def _raw_row(status, kind="staged-proposal"):
    from coordinator.app.database import connection, dump
    with connection() as db:
        cursor = db.execute(
            """INSERT INTO tasks (kind,payload,required_capabilities,preferred_tier,priority,status,created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (kind, dump({"staging_key": "other:other:" + "0" * 64}),
             dump([]), None, 0, status, "2026-01-01T00:00:00+00:00"))
        return cursor.lastrowid


@pytest.mark.parametrize("status", ["queued", "assigned", "completed", "failed"])
def test_non_staged_rows_never_promote(isolated_db, status):
    proposal, approval, task, _, _ = setup(isolated_db)
    queue_id = _raw_row(status)
    request = PromotionRequest(
        promotion_request_id="promo-2", staging_key="other:other:" + "0" * 64,
        queue_id=queue_id, proposal_fingerprint=task.proposal_fingerprint,
        staged_fingerprint="0" * 64, selected_node_id="node-7",
        required_capabilities=[], model=dict(MODEL),
        adapter_id="reference-noop", capability_snapshot=list(SNAPSHOT))
    with pytest.raises(ValueError):
        promote(request, approval)
    assert row(queue_id)["status"] == status


# --- determinism, audit, provenance ------------------------------------------------------------------

def test_deterministic_fingerprint(isolated_db):
    _, _, task, _, _ = setup(isolated_db)
    data = task.model_dump(mode="json")
    assert staged_fingerprint(data) == staged_fingerprint(data)
    assert len(staged_fingerprint(data)) == 64


def test_audit_provenance_intact(isolated_db):
    proposal, approval, task, staged, request = setup(isolated_db)
    audit = promote(request, approval)
    assert audit.provenance.human_verified is False
    assert audit.provenance.source_type == "ai-generated"
    assert audit.approval.decision == "approved"


def test_human_verified_stays_false(isolated_db):
    proposal, approval, task, staged, request = setup(isolated_db)
    audit = promote(request, approval)
    assert audit.provenance.human_verified is False
    assert row(staged.queue_id)["status"] == "queued"


def test_db_correct_after_denies(isolated_db):
    proposal, approval, task, staged, request = setup(isolated_db)
    bad = request.model_copy(update={"staging_key": "wrong"})
    with pytest.raises(ValueError):
        promote(bad, approval)
    from coordinator.app.database import connection, load
    with connection() as db:
        stored = db.execute("SELECT * FROM tasks WHERE id=?",
                            (staged.queue_id,)).fetchone()
        assert stored["status"] == STAGED_STATUS
        assert stored["kind"] == STAGED_KIND
        assert load(stored["required_capabilities"]) == []
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_atomic_transition(isolated_db):
    proposal, approval, task, staged, request = setup(isolated_db)
    audit = promote(request, approval)
    from coordinator.app.database import connection, load
    with connection() as db:
        stored = db.execute("SELECT * FROM tasks WHERE id=?",
                            (staged.queue_id,)).fetchone()
        assert stored["status"] == "queued"
        assert stored["kind"] == STAGED_KIND
        assert stored["assigned_node_id"] is None
        assert load(stored["required_capabilities"]) == ["ocr"]
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    assert audit.queue_id == staged.queue_id


# --- absence of execution ---------------------------------------------------------------------------------

def test_no_execution_attributes():
    import coordinator.app.promotion as module
    for name in dir(module):
        if name.startswith("__"):
            continue
        lowered = name.lower()
        for token in ("execute", "dispatch", "assign", "claim", "complete",
                      "run", "infer", "fetch", "download", "shell"):
            assert token not in lowered, f"promotion gate must not offer {name}"


def test_implementation_has_no_io_tokens():
    source = (Path(__file__).resolve().parent.parent
              / "coordinator" / "app" / "promotion.py").read_text(
                  encoding="utf-8")
    for token in ("subprocess", "os.system", "socket", "httpx", "requests",
                  "torch", "transformers", "ollama", "serial", "GPIO",
                  "threading", "asyncio", "pathlib", "shutil", "open(",
                  "inference", "download", "filesystem-write",
                  "claim_task", "complete_task", "hardware", "printer",
                  "slicer"):
        assert token not in source, f"promotion gate must not use {token}"
