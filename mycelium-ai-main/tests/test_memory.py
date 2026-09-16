"""Phase 1 tests (BIG #11-15): memory, watcher detectors, reports."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.inventory_read import Provenance


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "p1.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "p1-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def human_prov():
    return {"source_type": "user-created",
            "creator_id": "jelles", "human_verified": True,
            "verified_by": "jelles"}


def test_memory_create_retrieve_and_truth_tiers(tmp_path,
                                                monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        # AI suggestion by default.
        created = test_client.post("/api/v1/memory", json={
            "memory_type": "preference",
            "title": "Oat milk in coffee",
            "content": "Jelles prefers oat milk."}).json()
        assert created["memory_id"].startswith("mem_")
        assert created["truth"] == "ai_suggestion"
        # AI content cannot enter fact tiers directly.
        assert test_client.post("/api/v1/memory", json={
            "memory_type": "fact", "title": "X",
            "truth": "user_fact",
            "provenance": {"source_type": "ai-generated",
                           "creator_id": "m"}}).status_code == 422
        # Human fact works.
        fact = test_client.post("/api/v1/memory", json={
            "memory_type": "fact", "title": "Workshop address",
            "truth": "user_fact", "content": "Nijmegen",
            "provenance": human_prov()}).json()
        assert fact["truth"] == "user_fact"
        # Unknown type refuses.
        assert test_client.post("/api/v1/memory", json={
            "memory_type": "nope", "title": "X"}).status_code == 422
        # Retrieval finds the preference lexically.
        results = test_client.post("/api/v1/memory/retrieve",
                                   json={
                                       "query": "oat milk coffee",
                                       "limit": 5}).json()["results"]
        assert results
        assert results[0]["memory_id"] == created["memory_id"]
        # Filter by type/truth.
        facts = test_client.post("/api/v1/memory/retrieve",
                                 json={
                                     "query": "",
                                     "memory_types": ["fact"],
                                     "truth": "user_fact"}).json()[
                                         "results"]
        assert {item["memory_id"] for item in facts} == {
            fact["memory_id"]}
        # Get + list.
        assert test_client.get(
            f"/api/v1/memory/{fact['memory_id']}").json()[
                "title"] == "Workshop address"
        assert test_client.get(
            "/api/v1/memory/mem_missing").status_code == 404


def test_memory_verify_promotion_and_tombstone(tmp_path,
                                               monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        created = test_client.post("/api/v1/memory", json={
            "memory_type": "fact", "title": "Needs review",
            "truth": "ai_inference",
            "provenance": human_prov()}).json()
        # Verify without human approver refuses.
        assert test_client.post(
            f"/api/v1/memory/{created['memory_id']}/verify",
            json={"verified_by": ""}).status_code == 422
        verified = test_client.post(
            f"/api/v1/memory/{created['memory_id']}/verify",
            json={"verified_by": "jelles"}).json()
        assert verified["truth"] == "verified"
        assert verified["revision"] == 2
        # Delete is a tombstone: get 404s, row preserved.
        assert test_client.delete(
            f"/api/v1/memory/{created['memory_id']}"
        ).status_code == 200
        assert test_client.get(
            f"/api/v1/memory/{created['memory_id']}"
        ).status_code == 404
        from coordinator.app.memory import get_memory
        assert get_memory(created["memory_id"]).status == \
            "deleted"


def test_memory_consolidation_dedup_and_contradiction(
        tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        first = test_client.post("/api/v1/memory/consolidate",
                                 json={
                                     "raw_texts": [
                                         "Printer is in the workshop",
                                         "Printer is in the workshop",
                                         ""],
                                     "project_ref": "proj_x"}).json()
        assert len(first["candidates"]) == 1
        assert first["duplicates"] == 1
        assert first["contradictions"] == []
        # Nothing was stored by consolidation itself.
        assert test_client.post("/api/v1/memory/retrieve",
                                json={
                                    "query": "printer workshop"}
                                ).json()["results"] == []
        # Contradiction detection is structural.
        from coordinator.app.memory import (
            detect_contradictions, new_memory)
        left = new_memory("fact", "Filament left", truth="observed",
                          data={"grams": 500},
                          entity_refs=["spool_1"])
        right = new_memory("fact", "Filament right", truth="observed",
                           data={"grams": 120},
                           entity_refs=["spool_1"])
        flags = detect_contradictions([left, right])
        assert len(flags) == 1
        assert flags[0]["entity_ref"] == "spool_1"
        assert flags[0]["field"] == "grams"
        # Empty consolidation refuses.
        assert test_client.post("/api/v1/memory/consolidate",
                                json={
                                    "raw_texts": []}
                                ).status_code == 422


def test_health_memories_need_explicit_scope(tmp_path,
                                              monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        health = test_client.post("/api/v1/memory", json={
            "memory_type": "health", "title": "Sleep 7.5h",
            "content": "slept seven and a half hours",
            "truth": "observed"}).json()
        plain = test_client.post("/api/v1/memory", json={
            "memory_type": "fact", "title": "Workshop shelf",
            "content": "unrelated workshop note about brackets",
            "truth": "observed"}).json()
        # Default retrieval never surfaces health memories.
        results = test_client.post("/api/v1/memory/retrieve",
                                   json={
                                       "query": "sleep hours",
                                       "limit": 10}).json()["results"]
        assert health["memory_id"] not in {
            item["memory_id"] for item in results}
        # Explicit health type without scope refuses.
        assert test_client.post("/api/v1/memory/retrieve", json={
            "query": "sleep", "memory_types": ["health"]}
        ).status_code == 422
        # Opt-in returns them.
        scoped = test_client.post("/api/v1/memory/retrieve",
                                  json={
                                      "query": "sleep hours",
                                      "include_health": True,
                                      "limit": 10}).json()["results"]
        assert health["memory_id"] in {
            item["memory_id"] for item in scoped}
        # Same rule on the list endpoint.
        assert test_client.get(
            "/api/v1/memory",
            params={"memory_type": "health"}).status_code == 422
        listed = test_client.get("/api/v1/memory").json()
        assert health["memory_id"] not in {
            item["memory_id"] for item in listed}
        scoped_list = test_client.get(
            "/api/v1/memory",
            params={"memory_type": "health",
                    "include_health": True}).json()
        assert {item["memory_id"] for item in scoped_list} == {
            health["memory_id"]}
        # Live memory sections exclude health without scope.
        session = test_client.post("/api/v1/live/sessions",
                                   json={
                                       "interface": "web",
                                       "actor": "jelles",
                                       "capabilities": [
                                           "memory.read"]}).json()[
                                               "session_id"]
        package = test_client.post("/api/v1/live/context",
                                   json={
                                       "session_id": session,
                                       "query": "sleep hours"}).json()
        assert "memory" in package["sections"]
        assert "7.5" not in package["sections"].get("memory", "")
        scoped_session = test_client.post(
            "/api/v1/live/sessions",
            json={"interface": "web", "actor": "jelles",
                  "capabilities": ["memory.read", "health.read"],
                  "context_scope": {
                      "include_health": True}}).json()["session_id"]
        scoped_package = test_client.post(
            "/api/v1/live/context",
            json={"session_id": scoped_session,
                  "query": "sleep hours"}).json()
        assert "7.5" in scoped_package["sections"].get("memory",
                                                       "")


def test_memory_no_shell_sql_in_module():
    import pathlib
    source = (pathlib.Path(__file__).resolve().parent.parent /
              "coordinator" / "app" / "memory.py").read_text(
                  encoding="utf-8")
    for token in ("subprocess", "os.system", "eval(",
                  "import sqlite3", "https://", "0.0.0.0"):
        assert token not in source


def test_watcher_new_detectors_pure():
    from coordinator.app import watcher as w
    current = datetime.now(timezone.utc)
    old = (current - timedelta(hours=50)).isoformat()
    blocked = w.scan_blocked_tasks(
        [{"id": "t1", "status": "blocked", "updated_at": old}],
        current)
    assert len(blocked) == 1 and blocked[0].kind == "blocked_task"
    failed = w.scan_failed_tasks(
        [{"id": "t2", "status": "failed", "attempts": 2},
         {"id": "t3", "status": "queued", "attempts": 5},
         {"id": "t4", "status": "queued", "attempts": 1}],
        current)
    assert {item.entity_refs[0] for item in failed} == {
        "t2", "t3"}
    orphans = w.scan_orphan_files(
        [{"id": "file_a"}, {"id": "file_b"}],
        [{"from_id": "file_b", "to_id": "proj_1"}], current)
    assert [item.entity_refs[0] for item in orphans] == ["file_a"]
    dups = w.scan_duplicate_files(
        [{"id": "file_a", "sha256": "ab" * 32},
         {"id": "file_b", "sha256": "AB" * 32},
         {"id": "file_c", "sha256": "cd" * 32}], current)
    assert len(dups) == 1 and dups[0].kind == "duplicate_file"
    designs = w.scan_unfinished_designs(
        [{"fabrication_id": "fab_1", "status": "mesh_validated"},
         {"fabrication_id": "fab_2", "status": "verified"}],
        current)
    assert [item.entity_refs[0] for item in designs] == ["fab_1"]
    gaps = w.scan_skill_gaps(
        [{"skill": "CAD", "project_ref": "proj_x"},
         {"skill": "Python", "project_ref": "proj_x"}],
        ["python"], current)
    assert len(gaps) == 1 and "CAD" in gaps[0].summary
    stale = w.scan_device_staleness(
        [{"id": "prt_1",
          "last_seen": (current - timedelta(days=9)).isoformat()},
         {"id": "prt_2", "last_seen": current.isoformat()}],
        current)
    assert [item.entity_refs[0] for item in stale] == ["prt_1"]
    # Bounded and closed kinds.
    assert w.scan_blocked_tasks("nope", current) == []
    with pytest.raises(w.WatcherRefusedError):
        w.scan_entities([{}], current, kind="nope",
                        stale_hours=1.0)


def test_reports_fifteen_sections_and_morning_route(tmp_path,
                                                    monkeypatch):
    from coordinator.app.reports import (
        ReportRefusedError, morning_report)
    full = morning_report({
        "today": ["Monday"], "health": ["ok"], "recovery": ["rest"],
        "projects": ["p"], "tasks": ["t"], "missions": ["m"],
        "skills": ["s"], "inventory": ["i"], "workshop": ["w"],
        "research": ["r"], "fabrication": ["f"],
        "devices": ["d"], "findings": ["x"],
        "suggestions": ["y"], "fun": ["z"]})
    assert len(full.sections) == 15
    with pytest.raises(ReportRefusedError):
        morning_report({"notifications": ["old key"]})
    for test_client in make_client(tmp_path, monkeypatch):
        report = test_client.get(
            "/api/v1/reports/morning").json()
        titles = [section["title"] for section in
                  report["sections"]]
        assert "Today" in titles
        assert "Devices" in titles
        assert "Watcher findings" in titles
