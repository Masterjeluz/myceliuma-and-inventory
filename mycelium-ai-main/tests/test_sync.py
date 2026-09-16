"""Sync protocol tests (BIG #10, deel 3).

Bounded pull pages, idempotent apply, conflict surfacing,
sync status, INVENTory change feed over HTTP (cursor +
provenance, never SQL, never the database file).
"""

import pytest

from coordinator.app.sync import (
    SyncRefusedError,
    apply_pulled,
    fetch_inventory_changes,
    pull_changes,
    sync_status,
)


def use_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "sync.db"))


def source(items, latest=0):
    def fetch(after, limit):
        page = [item for item in items][:limit]
        return page, latest or len(items)
    return fetch


def test_pull_bounds():
    items, latest = pull_changes(source([{"a": 1}] * 5, 5),
                                 after_rowid=0, limit=2)
    assert len(items) == 2
    assert latest == 5
    with pytest.raises(SyncRefusedError):
        pull_changes(source([]), after_rowid="nope")
    with pytest.raises(SyncRefusedError):
        pull_changes("not-callable")


def test_apply_idempotent_and_conflicts(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch)
    from coordinator.app.diststate import new_envelope
    first = new_envelope("node-a", "obj_1", "object",
                         "entity.observed",
                         entity_revision="rev-1").model_dump(
                             mode="json")
    summary = apply_pulled([first, first])
    assert summary["applied"] == 1
    assert summary["duplicates"] == 1
    assert summary["conflicts"] == 0
    other = new_envelope("node-b", "obj_1", "object",
                         "entity.observed",
                         entity_revision="rev-2b",
                         base_revision="rev-1",
                         payload={"color": "blue"}).model_dump(
                             mode="json")
    mine = new_envelope("node-a", "obj_1", "object",
                        "entity.observed",
                        entity_revision="rev-2a",
                        base_revision="rev-1",
                        payload={"color": "red"}).model_dump(
                            mode="json")
    second = apply_pulled([mine, other])
    assert second["applied"] == 1
    assert second["conflicts"] == 1
    assert len(second["conflict_ids"][0]) > 0
    broken = apply_pulled([{"nope": True}, "string"])
    assert broken["failed"] == 2


def test_sync_status_shape(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch)
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "q.db"))
    from coordinator.app.diststate import new_envelope, save_envelope
    save_envelope(new_envelope("node-a", "obj_1", "object",
                               "entity.observed"))
    save_envelope(new_envelope("node-a", "obj_2", "object",
                               "entity.observed"))
    status = sync_status([], cursor=1)
    assert status["log_latest"] == 2
    assert status["pending"] == 1
    assert status["open_conflicts"] == 0
    assert status["epoch"] == 0
    assert status["live_nodes"] == 0
    assert status["coordinator"]["mode"] == "none"


class FakeReader:
    def __init__(self, events):
        self._events = events

    async def events_since(self, since="", limit=100):
        return self._events[:limit]


def test_inventory_change_feed_bridge():
    import asyncio
    reader = FakeReader([{
        "id": "evt_1", "event_type": "object_created",
        "entity_id": "obj_1", "timestamp": "2026-01-01T00:00:00",
        "provenance": {"source_type": "user-created"}}])
    items = asyncio.run(fetch_inventory_changes(
        reader, since="", limit=10))
    assert len(items) == 1
    assert items[0]["entity_id"] == "obj_1"
    assert items[0]["provenance"]["source_type"] == "user-created"


def test_inventory_bridge_refusals():
    import asyncio

    class NoFeed:
        pass

    async def run():
        with pytest.raises(SyncRefusedError, match="cursor change"):
            await fetch_inventory_changes(NoFeed())
        with pytest.raises(SyncRefusedError, match="limit"):
            await fetch_inventory_changes(FakeReader([]),
                                          limit="nope")

    asyncio.run(run())
