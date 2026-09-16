"""Tests for M7.4 leases, stale-node expiry and attempt limits.

Time is injected as fixed ISO strings; no sleeps. Coordinator database is
always a tmp database via MYCELIUM_DATABASE_PATH.
"""
import os

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.main import (
    LEASE_SECONDS,
    MAX_ATTEMPTS,
    NODE_STALE_SECONDS,
    _claim_task,
    _complete_task,
    expire_leases,
    node_is_stale,
)

T0 = "2026-01-01T00:00:00+00:00"
T0_LATE = "2026-01-01T00:10:00+00:00"

NODE = {"node_id": "worker-1", "hostname": "shop", "tier": "worker",
        "capabilities": ["python"], "cpu_cores": 2, "memory_mb": 1024,
        "energy_source": "solar", "node_token": "queue-token-123456"}
TASK = {"kind": "system_inventory", "required_capabilities": ["python"]}


def claim(node_id, when):
    """_claim_task with this file's node token bound."""
    return _claim_task(node_id, when,
                       node_token="queue-token-123456")


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH", str(tmp_path / "m74.db"))
    with TestClient(main_mod.app) as client:
        yield client


def register(api_client, **overrides):
    payload = dict(NODE)
    payload.update(overrides)
    res = api_client.post("/api/v1/nodes/register", json=payload)
    assert res.status_code == 201
    return payload["node_id"]


def queue(api_client, **overrides):
    payload = dict(TASK)
    payload.update(overrides)
    res = api_client.post("/api/v1/tasks", json=payload)
    assert res.status_code == 201
    return res.json()["id"]


def row(task_id):
    from coordinator.app.database import connection
    with connection() as db:
        return db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()


def test_policy_constants():
    assert LEASE_SECONDS == 300
    assert MAX_ATTEMPTS == 3
    assert NODE_STALE_SECONDS == 60


def test_new_task_has_no_assignment(api):
    task_id = queue(api)
    stored = row(task_id)
    assert stored["attempt_count"] == 0
    assert stored["assigned_node_id"] is None
    assert stored["assigned_at"] is None
    assert stored["lease_until"] is None


def test_live_node_claims_with_lease(api):
    register(api)
    task_id = queue(api)
    claimed = claim("worker-1", T0)
    assert claimed is not None
    assert claimed.id == task_id
    stored = row(task_id)
    assert stored["status"] == "assigned"
    assert stored["assigned_node_id"] == "worker-1"
    assert stored["assigned_at"] == T0
    assert stored["lease_until"] == "2026-01-01T00:05:00+00:00"
    assert stored["attempt_count"] == 1


def test_claim_via_http_still_works(api):
    register(api)
    task_id = queue(api)
    res = api.post("/api/v1/tasks/claim/worker-1",
                   params={"node_token": "queue-token-123456"})
    assert res.status_code == 200
    assert row(task_id)["status"] == "assigned"


def test_stale_node_cannot_claim(api):
    from datetime import datetime, timedelta, timezone
    register(api)
    task_id = queue(api)
    stale_moment = (datetime.now(timezone.utc)
                    + timedelta(seconds=NODE_STALE_SECONDS + 1)).isoformat()
    assert claim("worker-1", stale_moment) is None
    assert row(task_id)["status"] == "queued"


def test_missing_node_claim_404(api):
    queue(api)
    with pytest.raises(HTTPException):
        claim("ghost", T0)


def test_capability_mismatch_still_denies(api):
    register(api, node_id="weak-1", capabilities=["rust"])
    queue(api)
    assert claim("weak-1", T0) is None


def test_double_claim_single_winner(api):
    register(api, node_id="worker-1")
    register(api, node_id="worker-2")
    queue(api)
    assert claim("worker-1", T0) is not None
    assert claim("worker-2", T0) is None


def test_complete_within_lease(api):
    from coordinator.app.schemas import TaskResult
    register(api)
    task_id = queue(api)
    claim("worker-1", T0)
    _complete_task(task_id, TaskResult(success=True, result={}),
                   completing_node_id="worker-1", now_str=T0)
    assert row(task_id)["status"] == "completed"


def test_complete_wrong_node_refused(api):
    from coordinator.app.schemas import TaskResult
    register(api)
    task_id = queue(api)
    claim("worker-1", T0)
    with pytest.raises(HTTPException):
        _complete_task(task_id, TaskResult(success=True, result={}),
                       completing_node_id="other-1", now_str=T0)
    assert row(task_id)["status"] == "assigned"


def test_complete_expired_lease_refused(api):
    from coordinator.app.schemas import TaskResult
    register(api)
    task_id = queue(api)
    claim("worker-1", T0)
    with pytest.raises(HTTPException):
        _complete_task(task_id, TaskResult(success=True, result={}),
                       completing_node_id="worker-1", now_str=T0_LATE)
    assert row(task_id)["status"] == "assigned"


def test_expired_lease_requeues_below_max(api):
    register(api)
    task_id = queue(api)
    claim("worker-1", T0)
    summary = expire_leases(T0_LATE)
    assert summary == {"requeued": 1, "failed": 0, "blocked": 0}
    stored = row(task_id)
    assert stored["status"] == "queued"
    assert stored["assigned_node_id"] is None
    assert stored["assigned_at"] is None
    assert stored["lease_until"] is None


def test_expired_lease_fails_at_max(api):
    from coordinator.app.database import connection, dump
    register(api)
    task_id = queue(api)
    with connection() as db:
        db.execute("UPDATE tasks SET status='assigned', assigned_node_id=?, assigned_at=?, lease_until=?, attempt_count=? WHERE id=?",
                   ("worker-1", T0, T0, MAX_ATTEMPTS, task_id))
    summary = expire_leases(T0_LATE)
    assert summary == {"requeued": 0, "failed": 1, "blocked": 0}
    stored = row(task_id)
    assert stored["status"] == "failed"
    assert stored["assigned_node_id"] is None
    assert stored["assigned_at"] is None
    assert stored["lease_until"] is None
    assert claim("worker-1", T0_LATE) is None


def test_retry_increments_attempts(api):
    register(api)
    task_id = queue(api)
    claim("worker-1", T0)
    expire_leases(T0_LATE)
    claimed = claim("worker-1", T0_LATE)
    assert claimed is not None
    assert row(task_id)["attempt_count"] == 2


def test_max_attempts_never_exceeded(api):
    register(api)
    task_id = queue(api)
    claim("worker-1", T0)
    expire_leases("2026-01-01T00:10:00+00:00")
    claim("worker-1", "2026-01-01T00:10:00+00:00")
    expire_leases("2026-01-01T00:20:00+00:00")
    claim("worker-1", "2026-01-01T00:20:00+00:00")
    assert row(task_id)["attempt_count"] == MAX_ATTEMPTS
    expire_leases("2026-01-01T00:30:00+00:00")
    stored = row(task_id)
    assert stored["status"] == "failed"
    assert stored["attempt_count"] == MAX_ATTEMPTS
    assert claim("worker-1", "2026-01-01T00:30:00+00:00") is None


def test_completed_task_not_reclaimable(api):
    from coordinator.app.schemas import TaskResult
    register(api)
    task_id = queue(api)
    claim("worker-1", T0)
    _complete_task(task_id, TaskResult(success=True, result={}), now_str=T0)
    assert claim("worker-1", T0) is None


def test_stale_node_assigned_task_not_completed(api):
    from coordinator.app.schemas import TaskResult
    register(api)
    task_id = queue(api)
    claim("worker-1", T0)
    with pytest.raises(HTTPException):
        _complete_task(task_id, TaskResult(success=True, result={}),
                       completing_node_id="worker-1", now_str=T0_LATE)
    assert row(task_id)["status"] == "assigned"


def test_recovery_idempotent(api):
    register(api)
    task_id = queue(api)
    claim("worker-1", T0)
    assert expire_leases(T0_LATE) == {"requeued": 1, "failed": 0,
                                        "blocked": 0}
    assert expire_leases(T0_LATE) == {"requeued": 0, "failed": 0,
                                      "blocked": 0}
    assert row(task_id)["status"] == "queued"


def test_node_is_stale_unit():
    assert node_is_stale(T0, T0) is False
    assert node_is_stale(T0, "2026-01-01T00:01:00+00:00") is False
    assert node_is_stale(T0, "2026-01-01T00:01:01+00:00") is True
    assert node_is_stale("not-a-time", T0) is True


def test_migration_adds_columns(tmp_path, monkeypatch):
    import sqlite3
    db_path = str(tmp_path / "legacy.db")
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH", db_path)
    con = sqlite3.connect(db_path)
    con.execute("""CREATE TABLE tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
        payload TEXT NOT NULL, required_capabilities TEXT NOT NULL,
        preferred_tier TEXT, priority INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'queued', assigned_node_id TEXT,
        result TEXT, created_at TEXT NOT NULL, completed_at TEXT)""")
    con.execute("INSERT INTO tasks (kind,payload,required_capabilities,created_at) VALUES (?,?,?,?)",
                ("system_inventory", "{}", "[]", T0))
    con.commit()
    con.close()
    from coordinator.app.database import init_database, connection
    init_database()
    with connection() as db:
        columns = {r["name"] for r in db.execute("PRAGMA table_info(tasks)").fetchall()}
        assert {"assigned_at", "lease_until", "attempt_count"} <= columns
        stored = db.execute("SELECT * FROM tasks").fetchone()
        assert stored["attempt_count"] == 0
    init_database()
