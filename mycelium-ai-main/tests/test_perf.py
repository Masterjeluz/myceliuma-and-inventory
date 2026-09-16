"""FASE 15/16 tests (BIG #16): pagination bounds + perf sanity.

Pagination is bounded everywhere (no unbounded retrieval);
hot paths complete in sane wall-clock time on local tmp
databases. Bounds are generous by design: this pins
against pathological blowups, not for benchmarking.
"""

import time

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

PERF_BUDGET_SECONDS = 15.0


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "perf.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "perf-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_pagination_bounds_enforced(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        page = client.get("/api/v1/sync/changes",
                          params={"after": 0,
                                  "limit": 500}).json()
        assert len(page["items"]) <= 100
        memories = client.get(
            "/api/v1/memory",
            params={"limit": 500}).json()
        assert len(memories) <= 200
        try:
            from coordinator.app.memory import list_memories
            assert len(list_memories(limit=10**6)) <= 200
        except Exception as error:  # noqa: BLE001
            raise AssertionError(error)
        health = client.get(
            "/api/v1/health/measurements",
            params={"limit": 5000}).json()
        assert len(health) <= 500


def test_perf_sanity_hot_paths(tmp_path, monkeypatch):
    timings = {}
    for client in make_client(tmp_path, monkeypatch):
        client.post("/api/v1/nodes/register", json={
            "node_id": "node-perf", "hostname": "h",
            "capabilities": ["exec:system_inventory"],
            "node_token": "perf-token-123456"})
        for _ in range(50):
            client.post("/api/v1/tasks", json={
                "kind": "system_inventory",
                "required_capabilities": [
                    "exec:system_inventory"]})
        for index in range(100):
            client.post("/api/v1/memory", json={
                "memory_type": "fact",
                "title": f"perf fact {index}",
                "content": "perf content",
                "truth": "observed"})
        for index in range(200):
            main_mod.emit_event("perf.tick", f"tick {index}")

        def timed(name, func):
            start = time.perf_counter()
            func()
            took = time.perf_counter() - start
            timings[name] = round(took, 3)
            assert took < PERF_BUDGET_SECONDS, (name, took)

        timed("claim", lambda: client.post(
            "/api/v1/tasks/claim/node-perf",
            params={"node_token": "perf-token-123456"}))
        timed("event_poll", lambda: client.get(
            "/api/v1/events/poll", params={"after": 0}))
        timed("memory_retrieve", lambda: client.post(
            "/api/v1/memory/retrieve",
            json={"query": "perf", "limit": 10}))
        timed("watcher", lambda: client.get(
            "/api/v1/watcher/scan"))
        timed("morning", lambda: client.get(
            "/api/v1/reports/morning"))
        timed("sync_status", lambda: client.get(
            "/api/v1/sync/status", params={"cursor": 0}))
    assert set(timings) == {"claim", "event_poll",
                            "memory_retrieve", "watcher",
                            "morning", "sync_status"}
