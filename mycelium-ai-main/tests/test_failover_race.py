"""FASE 3 tests (BIG #16): atomic campaign.

Invariant: two simultaneous campaigners can never both
become valid holders of the same resulting epoch. Same
node racing itself on an expired lease converges on one
epoch, one holder, one fencing token.
"""

import threading
from datetime import datetime, timezone

import pytest

from coordinator.app import failover


def fresh_nodes(*node_ids):
    now = datetime.now(timezone.utc).isoformat()
    return [{"node_id": node_id, "status": "online",
             "last_seen": now, "coordinator_capable": True}
            for node_id in node_ids]


def test_concurrent_same_node_campaign_converges(tmp_path,
                                                monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "race.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "race-chat.db"))
    first = failover.campaign(
        "node-r1", lambda: fresh_nodes("node-r1"))
    assert first["epoch"] == 1
    assert failover.release("node-r1") is True
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def run():
        try:
            barrier.wait(timeout=10)
            results.append(failover.campaign(
                "node-r1", lambda: fresh_nodes("node-r1")))
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, errors
    assert len(results) == 2
    # One holder, one epoch, one fencing token.
    assert {item["epoch"] for item in results} == {2}
    assert {item["node_id"] for item in results} == {"node-r1"}
    assert len({item["fencing_token"]
                for item in results}) == 1
    lease = failover.read_lease()
    assert lease["epoch"] == 2
    assert lease["holder_node_id"] == "node-r1"
    assert lease["fencing_token"] == results[0]["fencing_token"]


def test_renewal_keeps_token_and_epoch(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "race2.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "race2-chat.db"))
    first = failover.campaign(
        "node-r1", lambda: fresh_nodes("node-r1"))
    second = failover.campaign(
        "node-r1", lambda: fresh_nodes("node-r1"))
    assert second["mode"] == "renewed"
    assert second["epoch"] == first["epoch"] == 1
    assert second["fencing_token"] == first["fencing_token"]


def test_deterministic_order_still_refuses(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "race3.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "race3-chat.db"))
    with pytest.raises(failover.ElectionRefusedError):
        failover.campaign(
            "node-r9",
            lambda: fresh_nodes("node-r1", "node-r9"))
