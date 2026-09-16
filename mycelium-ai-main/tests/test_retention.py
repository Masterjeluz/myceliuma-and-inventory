"""FASE 4 tests (BIG #16): retention + indexes.

Retention is deterministic and operator-triggered: newest
rows survive, oldest excess goes, security tables
(dist_events, dist_conflicts, write_proposals) are never
touched. Indexes serve the hot paths (verified by
EXPLAIN QUERY PLAN below).
"""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.database import connection


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "ret.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "ret-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_retention_prunes_logs_not_security(tmp_path,
                                            monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        for index in range(10):
            main_mod.emit_event("ret.test", f"event {index}")
        from coordinator.app.jobs import run_job
        run_job("watcher_scan")
        run_job("watcher_scan")
        result = client.post(
            "/api/v1/maintenance/prune").json()
        assert result["interface_events"] == 0
        assert result["job_runs"] == 0
        assert result["excluded"] == [
            "dist_events", "dist_conflicts", "write_proposals"]
        # Over the caps: oldest go, newest stay.
        from coordinator.app.retention import (
            prune_job_runs, run_retention)
        from coordinator.app.jobs import list_runs
        for _ in range(25):
            run_job("watcher_scan")
        before = len(list_runs(job_name="watcher_scan",
                               limit=200))
        assert before > 20
        assert prune_job_runs(keep_per_job=20) == before - 20
        assert len(list_runs(job_name="watcher_scan",
                             limit=200)) == 20
        # dist_events untouched by retention.
        client.post("/api/v1/sync/apply", json={"items": [{
            "event_id": "dsevt_ret1",
            "origin_node_id": "node-a",
            "entity_id": "obj_1", "entity_type": "object",
            "entity_revision": "rev-1", "base_revision": "",
            "event_type": "entity.observed", "timestamp": "",
            "payload": {}, "provenance": {}, "epoch": 0}]})
        counts = run_retention()
        assert counts["excluded"] == [
            "dist_events", "dist_conflicts", "write_proposals"]
        from coordinator.app.diststate import read_log
        items, _ = read_log(after_rowid=0, limit=100)
        assert any(item["event_id"] == "dsevt_ret1"
                   for item in items)


def test_conversation_events_capped_per_mission(tmp_path,
                                                monkeypatch):
    for _client in make_client(tmp_path, monkeypatch):
        from coordinator.app.database import (
            chat_connection, init_chat_database)
        from coordinator.app.retention import (
            prune_conversation_events)
        init_chat_database()
        with chat_connection() as db:
            for index in range(8):
                db.execute(
                    "INSERT INTO conversation_events "
                    "(event_id, conversation_id, event_type, "
                    "mission_id, created_at) VALUES (?, ?, ?, "
                    "?, ?)",
                    (f"evt_{index}", "conv_1", "note",
                     "mis_1", f"2026-01-0{(index % 9) + 1}T00:00:00"))
        assert prune_conversation_events(
            keep_per_mission=5) == 3
        with chat_connection() as db:
            remaining = db.execute(
                "SELECT COUNT(*) AS n FROM conversation_events"
            ).fetchone()["n"]
        assert remaining == 5


def test_hot_path_indexes_used(tmp_path, monkeypatch):
    for _client in make_client(tmp_path, monkeypatch):
        from coordinator.app.database import init_chat_database
        init_chat_database()
        with connection() as db:
            claim_plan = db.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM tasks WHERE "
                "status='queued' ORDER BY priority DESC, id "
                "ASC LIMIT 500").fetchall()
            assert any("idx_tasks_status" in row[3]
                       for row in claim_plan), claim_plan
            nodes_plan = db.execute(
                "EXPLAIN QUERY PLAN SELECT status, last_seen "
                "FROM nodes ORDER BY last_seen DESC").fetchall()
            # Tiny tables may scan by planner choice; the
            # index must exist for growth.
            indexed = db.execute(
                "SELECT name FROM sqlite_master WHERE type="
                "'index' AND name='idx_nodes_last_seen'"
            ).fetchone()
            assert indexed is not None
            _ = nodes_plan
        from coordinator.app.database import (
            chat_connection as _chat)
        with _chat() as db:
            hash_plan = db.execute(
                "EXPLAIN QUERY PLAN SELECT source_id FROM "
                "research_sources WHERE content_hash=?"
                "", ("x",)).fetchall()
            assert any("idx_research_sources_hash" in row[3]
                       for row in hash_plan), hash_plan
            mem_plan = db.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM memories "
                "WHERE truth=? ORDER BY updated_at DESC LIMIT "
                "50", ("verified",)).fetchall()
            assert any("idx_memories" in row[3]
                       for row in mem_plan), mem_plan
