"""Phase 6 tests (BIG #11-15): Live integration, jobs, UI."""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "p6.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "p6-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def open_session(test_client, caps, scope=None):
    body = {"interface": "web", "actor": "jelles",
            "capabilities": caps}
    if scope:
        body["context_scope"] = scope
    return test_client.post("/api/v1/live/sessions",
                            json=body).json()["session_id"]


def test_live_new_sections_gated(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        test_client.post("/api/v1/memory", json={
            "memory_type": "fact", "title": "Oat milk",
            "content": "prefers oat milk",
            "truth": "user_fact",
            "provenance": {"source_type": "user-created",
                           "creator_id": "jelles",
                           "human_verified": True,
                           "verified_by": "jelles"}})
        test_client.post("/api/v1/skills", json={
            "name": "Python", "stage": "practicing"})
        # Unknown new caps refuse at session open.
        assert test_client.post("/api/v1/live/sessions", json={
            "interface": "web", "actor": "jelles",
            "capabilities": ["mind.read"]}).status_code == 422
        full = open_session(
            test_client,
            ["memory.read", "skills.read", "health.read",
             "research.read", "workshop.read",
             "fabrication.read", "twin.read", "watcher.read"],
            {"include_health": True})
        package = test_client.post("/api/v1/live/context",
                                   json={
                                       "session_id": full,
                                       "query": "oat milk",
                                       "budget": 8000}).json()
        assert "memory" in package["sections"]
        assert "skills" in package["sections"]
        assert "health" in package["sections"]
        # Health without explicit scope stays out.
        scoped = open_session(test_client, ["health.read"])
        bare = test_client.post("/api/v1/live/context", json={
            "session_id": scoped}).json()
        assert "health" not in bare["sections"]
        # Minimal session sees none of the new sections.
        minimal = open_session(test_client, ["task.read"])
        package = test_client.post("/api/v1/live/context",
                                   json={
                                       "session_id": minimal}).json()
        for section in ("memory", "health", "research",
                        "skills", "workshop", "fabrication",
                        "twin", "findings"):
            assert section not in package["sections"]


def test_jobs_bounded_observable_idempotent(tmp_path,
                                            monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        jobs = test_client.get("/api/v1/jobs").json()
        assert {item["job_name"] for item in jobs} == {
            "watcher_scan", "memory_consolidation",
            "morning_report", "health_import",
            "research_process", "skill_discover",
            "inventory_reconcile", "device_health"}
        assert test_client.post("/api/v1/jobs/run", json={
            "job_name": "nope"}).status_code == 422
        first = test_client.post("/api/v1/jobs/run", json={
            "job_name": "watcher_scan",
            "run_key": "smoke-key-1"}).json()
        assert first["status"] == "completed"
        assert "findings" in first["summary"]
        # Same key returns the existing run (idempotent).
        again = test_client.post("/api/v1/jobs/run", json={
            "job_name": "watcher_scan",
            "run_key": "smoke-key-1"}).json()
        assert again["run_id"] == first["run_id"]
        report = test_client.post("/api/v1/jobs/run", json={
            "job_name": "morning_report"}).json()
        assert report["summary"]["sections"] >= 1
        health = test_client.post("/api/v1/jobs/run", json={
            "job_name": "health_import",
            "params": {"provider": "mock", "limit": 3}}).json()
        assert health["summary"]["imported"] == 3
        runs = test_client.get("/api/v1/jobs/runs").json()
        assert len(runs) >= 3
        # Synchronous runs finish at once: nothing to cancel.
        assert test_client.post(
            f"/api/v1/jobs/runs/{first['run_id']}/cancel").json()[
                "cancelled"] is False


def test_living_workshop_pages_render(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        for page in ("/morning", "/memory", "/health",
                     "/skills", "/research", "/devices",
                     "/watcher"):
            response = test_client.get(page)
            assert response.status_code == 200, page
            assert "Mycelium" in response.text or \
                "mycelium" in response.text.lower(), page
        assert "Memory" in test_client.get("/").text or \
            "/memory" in test_client.get("/").text
