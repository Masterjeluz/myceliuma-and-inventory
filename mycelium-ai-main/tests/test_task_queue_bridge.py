"""Tests for M6.5 staged registration (data only, never dispatchable).

The coordinator database used here is always a tmp database via
MYCELIUM_DATABASE_PATH. Staging writes exactly one inert row; dispatch,
assignment and completion must remain impossible for staged rows.
"""
import os
from pathlib import Path

import pytest

from coordinator.app.adapters import ReferenceNoopAdapter
from coordinator.app.adapter_contracts import AdapterRequest
from coordinator.app.approval import approve, reject, request_approval
from coordinator.app.proposal_tasks import proposal_fingerprint, proposal_to_task
from coordinator.app.task_queue_bridge import (
    STAGED_KIND,
    STAGED_STATUS,
    StagedTask,
    stage_task,
    staging_key_for,
)

PROV = {"source_type": "user-created", "creator_id": "tester",
        "human_verified": True}


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH", str(tmp_path / "m65.db"))
    from coordinator.app.database import init_database
    init_database()
    return str(tmp_path / "m65.db")


def make_task(task_type="inspect"):
    adapter = ReferenceNoopAdapter()
    request = AdapterRequest(request_id="req-65", adapter_id="reference-noop",
                             model_id="mod_cam", node_id="node-9",
                             task_id="task_65",
                             input={"object_id": "obj_1"},
                             provenance=dict(PROV))
    proposal = adapter.propose(request)
    approval = approve(request_approval(proposal), proposal)
    return proposal_to_task(proposal, approval,
                            approved_fingerprint=proposal_fingerprint(proposal),
                            task_type=task_type)


def test_valid_task_registers(isolated_db):
    task = make_task()
    staged = stage_task(task)
    assert isinstance(staged, StagedTask)
    assert staged.status == STAGED_STATUS
    assert staged.staging_key == staging_key_for(task)
    assert staged.task == task
    from coordinator.app.database import connection
    with connection() as db:
        row = db.execute("SELECT * FROM tasks WHERE id=?",
                         (staged.queue_id,)).fetchone()
    assert row["status"] == STAGED_STATUS
    assert row["kind"] == STAGED_KIND
    assert row["assigned_node_id"] is None


def test_unapproved_task_refused(isolated_db):
    task = make_task()
    tampered = task.model_copy(update={"status": "queued"})
    with pytest.raises(ValueError):
        stage_task(tampered)
    tampered_approval = task.approval_reference.model_copy(
        update={"approved": False, "decision": "rejected"})
    tampered = task.model_copy(update={"approval_reference": tampered_approval})
    with pytest.raises(ValueError):
        stage_task(tampered)


def test_wrong_proposal_binding_refused(isolated_db):
    task = make_task()
    tampered = task.model_copy(update={"proposal_id": "prop-other"})
    with pytest.raises(ValueError):
        stage_task(tampered)


def test_wrong_request_binding_refused(isolated_db):
    task = make_task()
    approval = task.approval_reference.model_copy(
        update={"request_id": "req-other"})
    tampered = task.model_copy(update={"approval_reference": approval})
    with pytest.raises(ValueError):
        stage_task(tampered)


def test_invalid_fingerprint_refused(isolated_db):
    # M6.5 cannot recompute proposal content from a CoordinatorTask alone;
    # content integrity is M6.4's proven guarantee. M6.5 refuses malformed
    # fingerprints and enforces bindings around the carried fingerprint.
    task = make_task()
    tampered = task.model_copy(update={"proposal_fingerprint": "too-short"})
    with pytest.raises(ValueError):
        stage_task(tampered)
    tampered = task.model_copy(update={"proposal_fingerprint": None})
    with pytest.raises(ValueError):
        stage_task(tampered)


def test_duplicate_registration_idempotent(isolated_db):
    task = make_task()
    first = stage_task(task)
    second = stage_task(task)
    assert first == second
    from coordinator.app.database import connection
    with connection() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM tasks WHERE status=?",
            (STAGED_STATUS,)).fetchone()[0]
    assert count == 1


def test_staged_task_never_running_nor_assigned(isolated_db):
    task = make_task()
    staged = stage_task(task)
    from coordinator.app.database import connection
    with connection() as db:
        row = db.execute("SELECT * FROM tasks WHERE id=?",
                         (staged.queue_id,)).fetchone()
    assert row["status"] == STAGED_STATUS
    assert row["status"] not in ("queued", "assigned", "running", "completed")
    assert row["assigned_node_id"] is None


def test_staged_task_never_claimable(isolated_db):
    from coordinator.app import main as main_mod
    from coordinator.app.database import connection
    task = make_task()
    stage_task(task)
    with connection() as db:
        db.execute(
            """INSERT INTO nodes
            (node_id, hostname, tier, capabilities, cpu_cores,
             memory_mb, energy_source, last_seen, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'online')""",
            ("node-9", "host", "worker", "[]", 2, 1024, "solar",
             "2026-01-01T00:00:00+00:00"))
    assert main_mod.claim_task("node-9") is None
    with connection() as db:
        row = db.execute("SELECT status FROM tasks LIMIT 1").fetchone()
    assert row["status"] == STAGED_STATUS


def test_node_id_only_from_task_data(isolated_db):
    task = make_task()
    staged = stage_task(task)
    assert staged.task.node_id == "node-9"
    from coordinator.app.database import connection
    with connection() as db:
        row = db.execute("SELECT assigned_node_id FROM tasks WHERE id=?",
                         (staged.queue_id,)).fetchone()
    assert row["assigned_node_id"] is None


def test_provenance_and_approval_preserved(isolated_db):
    task = make_task()
    staged = stage_task(task)
    assert staged.task.provenance.human_verified is False
    assert staged.task.provenance.source_type == "ai-generated"
    assert staged.task.approval_reference == task.approval_reference
    assert staged.task.approval_reference.decision == "approved"


def test_task_identity_stable(isolated_db):
    task = make_task()
    first = stage_task(task)
    second = stage_task(task)
    assert first.staging_key == second.staging_key == staging_key_for(task)
    assert first.queue_id == second.queue_id


def test_db_holds_only_expected_task_data(isolated_db):
    task = make_task()
    staged = stage_task(task)
    from coordinator.app.database import connection
    with connection() as db:
        tables = sorted(r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%'").fetchall())
        rows = db.execute("SELECT * FROM tasks").fetchall()
    assert tables == ["nodes", "tasks"]
    assert len(rows) == 1
    assert rows[0]["id"] == staged.queue_id
    assert rows[0]["status"] == STAGED_STATUS


def test_no_second_queue(isolated_db):
    task = make_task()
    stage_task(task)
    from coordinator.app.database import connection
    with connection() as db:
        tables = sorted(r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%'").fetchall())
    assert tables == ["nodes", "tasks"]


def test_no_execution_attributes():
    import coordinator.app.task_queue_bridge as module
    for name in dir(module):
        if name.startswith("__"):
            continue
        lowered = name.lower()
        for token in ("execute", "dispatch", "assign", "claim", "complete",
                      "run", "infer", "fetch", "download", "shell"):
            assert token not in lowered, f"bridge must not offer {name}"


def test_implementation_has_no_io_tokens():
    # Note: sqlite calls read as db.execute(...) — that is parameterized SQL
    # through the existing queue database, not subprocess/shell execution.
    # The word "dispatch" appears only in docstrings describing the safety
    # boundary (never hand work to nodes); the behavioral tests above prove
    # staged rows are never claimed, assigned or completed.
    source = (Path(__file__).resolve().parent.parent
              / "coordinator" / "app" / "task_queue_bridge.py").read_text(
                  encoding="utf-8")
    for token in ("subprocess", "os.system", "shell", "socket", "httpx",
                  "requests", "torch", "transformers", "ollama", "serial",
                  "GPIO", "threading", "asyncio", "pathlib", "shutil",
                  "open(", "inference", "download", "filesystem-write",
                  "claim_task", "complete_task"):
        assert token not in source, f"bridge must not use {token}"
