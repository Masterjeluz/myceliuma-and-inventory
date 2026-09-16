"""Coordinator failover tests (BIG #10, deel 2).

Lease, epoch, fencing, deterministic election, quorum and
degraded mode, stale-coordinator write refusal, returning
primary sync. No Raft, no new dependencies.
"""

import pytest

import coordinator.app.main as main_mod
from coordinator.app.failover import (
    ElectionRefusedError,
    FencingError,
    campaign,
    current_epoch,
    release,
    require_epoch,
    sync_status,
)


def use_dbs(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "fo.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "fo-chat.db"))


def register(node_id, capable=True, live=True):
    from fastapi.testclient import TestClient
    with TestClient(main_mod.app) as client:
        response = client.post("/api/v1/nodes/register", json={
            "node_id": node_id, "hostname": "h",
            "capabilities": [], "coordinator_capable": capable})
        assert response.status_code == 201, response.text
        if not live:
            from coordinator.app.database import connection
            with connection() as db:
                db.execute(
                    "UPDATE nodes SET last_seen=? WHERE node_id=?",
                    ("2020-01-01T00:00:00+00:00", node_id))


def voters():
    from coordinator.app.database import connection
    with connection() as db:
        rows = db.execute(
            "SELECT node_id, status, last_seen, "
            "coordinator_capable FROM nodes").fetchall()
    return [{
        "node_id": row["node_id"], "status": row["status"],
        "last_seen": row["last_seen"],
        "coordinator_capable": bool(row["coordinator_capable"]),
    } for row in rows]


def test_single_node_elects_degraded(tmp_path, monkeypatch):
    use_dbs(tmp_path, monkeypatch)
    register("node-solo")
    result = campaign("node-solo", voters)
    assert result["epoch"] == 1
    assert result["mode"] == "degraded"
    assert len(result["fencing_token"]) == 32
    assert current_epoch() == 1
    assert require_epoch(1) == 1
    # Renewal keeps the epoch, refreshes the lease.
    renewed = campaign("node-solo", voters)
    assert renewed["epoch"] == 1
    assert renewed["mode"] == "renewed"


def test_deterministic_order_and_quorum(tmp_path, monkeypatch):
    use_dbs(tmp_path, monkeypatch)
    register("node-b")
    register("node-a")
    with pytest.raises(ElectionRefusedError, match="node-a"):
        campaign("node-b", voters)
    result = campaign("node-a", voters)
    assert result["epoch"] == 1
    assert result["mode"] == "quorum"
    # Holder renews without quorum drama; a released lease with
    # too few fresh voters refuses (manual recovery).
    register("node-c", live=False)
    register("node-d", live=False)
    renewed = campaign("node-a", voters)
    assert renewed["mode"] == "renewed"
    release("node-a")
    stale("node-a")
    with pytest.raises(ElectionRefusedError, match="no quorum"):
        campaign("node-b", voters)
    from coordinator.app.failover import _capable_set
    assert len(_capable_set(voters())) == 4


def test_ineligible_nodes_refused(tmp_path, monkeypatch):
    use_dbs(tmp_path, monkeypatch)
    register("node-plain", capable=False)
    with pytest.raises(ElectionRefusedError, match="eligible"):
        campaign("node-plain", voters)
    with pytest.raises(ElectionRefusedError, match="eligible"):
        campaign("node-ghost", voters)
    register("node-stale", live=False)
    with pytest.raises(ElectionRefusedError, match="eligible"):
        campaign("node-stale", voters)


def stale(node_id):
    from coordinator.app.database import connection
    with connection() as db:
        db.execute("UPDATE nodes SET last_seen=? WHERE node_id=?",
                   ("2020-01-01T00:00:00+00:00", node_id))


def expire_lease():
    from coordinator.app.database import chat_connection
    with chat_connection() as db:
        db.execute("UPDATE coordinator_lease SET expires_at=? "
                   "WHERE id=1",
                   ("2020-01-01T00:00:00+00:00",))


def disable(node_id):
    from coordinator.app.database import connection
    with connection() as db:
        db.execute("UPDATE nodes SET status='disabled' "
                   "WHERE node_id=?", (node_id,))


def test_lease_holder_wins_and_release(tmp_path, monkeypatch):
    use_dbs(tmp_path, monkeypatch)
    register("node-1")
    register("node-2")
    first = campaign("node-1", voters)
    assert first["epoch"] == 1
    # Holder goes stale: the live lease still fences node-2 out.
    stale("node-1")
    with pytest.raises(ElectionRefusedError, match="held by"):
        campaign("node-2", voters)
    assert release("node-2") is False
    assert release("node-1") is True
    assert current_epoch() == 0
    # Manual recovery: disable the dead node, then node-2 wins
    # a new epoch in degraded mode. No split-brain: epoch grows.
    disable("node-1")
    second = campaign("node-2", voters)
    assert second["epoch"] == 2
    assert second["mode"] == "degraded"


def test_old_epoch_cannot_write(tmp_path, monkeypatch):
    use_dbs(tmp_path, monkeypatch)
    register("node-1")
    campaign("node-1", voters)
    assert current_epoch() == 1
    # Primary returns after failure elsewhere: it synchronizes
    # by reading (pull-only) and must campaign for a NEW epoch;
    # the old epoch never writes again.
    release("node-1")
    register("node-2")
    disable("node-1")
    campaign("node-2", voters)
    assert current_epoch() == 2
    with pytest.raises(FencingError, match="not the live epoch"):
        require_epoch(1)
    with pytest.raises(FencingError):
        require_epoch("nope")
    assert require_epoch(2) == 2


def test_sync_status_snapshot(tmp_path, monkeypatch):
    use_dbs(tmp_path, monkeypatch)
    register("node-1")
    empty = sync_status(voters())
    assert empty == {"epoch": 0, "holder": None,
                     "expires_at": None, "eligible_voters": [
                         "node-1"], "mode": "none"}
    campaign("node-1", voters)
    live = sync_status(voters())
    assert live["epoch"] == 1
    assert live["holder"] == "node-1"
    assert live["mode"] == "degraded"
