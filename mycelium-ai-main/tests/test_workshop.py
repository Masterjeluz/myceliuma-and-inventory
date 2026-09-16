"""Workshop, Live, watcher and reports tests (BIG #10).

Graph overlays (nodes/printers), interactive pages, mesh
preview, transform proposals, Live sessions/capabilities/
context, git separation, watcher findings, deterministic
reports, domain extension points.
"""

import os

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "w.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "w-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_graph_nodes_printers_overlay(tmp_path, monkeypatch):
    import asyncio
    from coordinator.app.inventory_read import GraphResponse
    from coordinator.app.worldgraph import build_world_graph

    class Reader:
        async def graph(self, entity_id, depth=1):
            return GraphResponse(entity_id=entity_id, depth=depth,
                                 nodes=[], edges=[])

    async def run():
        return await build_world_graph(
            Reader(), "obj_x", 1,
            registry_nodes=[{"node_id": "node-1", "hostname": "h",
                    "tier": "worker", "derived_status": "online",
                    "capabilities": ["a", "b"],
                    "models": [{"model_id": "model:x"}],
                    "last_seen": "2026-01-01T00:00:00+00:00"}],
            printers=[{"printer_id": "prt-1", "name": "P",
                        "status": "registered",
                        "capabilities": ["printer.start"],
                        "inventory_hardware_id": ""}])

    graph = asyncio.run(run())
    node_ids = [node["id"] for node in graph["nodes"]]
    assert "node-1" in node_ids
    assert "prt-1" in node_ids
    node = next(entry for entry in graph["nodes"]
                if entry["id"] == "node-1")
    assert node["source"] == "mycelium"
    assert node["metadata"]["revision"] != ""


def test_graph_page_renders(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        page = test_client.get("/workshop/graph")
        assert page.status_code == 200
        assert "Living Workshop" in page.text
        assert "WORLD (INVENTory)" in page.text
        assert "<svg" in page.text


def test_workshop_pages(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        page = test_client.get("/workshop")
        assert page.status_code == 200
        assert "Keten" in page.text
        page3d = test_client.get("/workshop/3d")
        assert page3d.status_code == 200
        assert "Transformatie-voorstel" in page3d.text
        assert "canvas" in page3d.text


def test_mesh_preview_and_transform(tmp_path, monkeypatch):
    from coordinator.app.mesh3d import ProceduralTestGenerator
    for test_client in make_client(tmp_path, monkeypatch):
        generated = ProceduralTestGenerator().generate("kubus",
                                                       {})
        preview = test_client.get("/api/v1/fab/mesh/preview",
                                  params={
                                      "artifact_ref":
                                      generated.artifact_ref,
                                      "max_tris": 100}).json()
        assert preview["total_tris"] == 12
        assert len(preview["tris"]) == 12
        assert len(preview["tris"][0]) == 3
        refused = test_client.get("/api/v1/fab/mesh/preview",
                                  params={"artifact_ref":
                                          "../x.stl"})
        assert refused.status_code == 422
        # Preview-only transform: nothing persisted.
        moved = test_client.post("/api/v1/fab/transform", json={
            "artifact_ref": generated.artifact_ref,
            "op": "rotate",
            "params": {"axis": "z", "degrees": 90}}).json()
        assert moved["executed"] is False
        assert len(moved["preview_tris"]) == 12
        assert moved["preview_tris"] != preview["tris"]
        bad = test_client.post("/api/v1/fab/transform", json={
            "artifact_ref": generated.artifact_ref,
            "op": "melt", "params": {}})
        assert bad.status_code == 422
        bad2 = test_client.post("/api/v1/fab/transform", json={
            "artifact_ref": generated.artifact_ref,
            "op": "scale", "params": {"factor": 0}})
        assert bad2.status_code == 422
        # Persisted transform: local derived file + payload for
        # the proposal flow, nothing registered automatically.
        kept = test_client.post("/api/v1/fab/transform", json={
            "artifact_ref": generated.artifact_ref,
            "op": "translate",
            "params": {"dx": 5, "dy": 0, "dz": 0},
            "persist": True}).json()
        assert kept["executed"] is True
        assert kept["derived_ref"].startswith("fab-derived-")
        assert kept["file_payload"]["file_kind"] == "mesh"
        assert kept["validation"]["verdict"] == "valid"


def test_live_sessions_and_caps(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        opened = test_client.post("/api/v1/live/sessions", json={
            "interface": "web", "actor": "jelles",
            "capabilities": ["inventory.read", "git.diff"]}).json()
        session_id = opened["session_id"]
        assert session_id.startswith("live-")
        fetched = test_client.get(
            f"/api/v1/live/sessions/{session_id}").json()
        assert fetched["active"] is True
        assert test_client.post(
            "/api/v1/live/sessions/live-missing/revoke"
        ).status_code == 404
        revoked = test_client.post(
            f"/api/v1/live/sessions/{session_id}/revoke").json()
        assert revoked["active"] is False
        assert test_client.get(
            f"/api/v1/live/sessions/{session_id}").status_code == 403
        # git.push is never granted, unknown caps refuse.
        assert test_client.post("/api/v1/live/sessions", json={
            "interface": "web", "actor": "jelles",
            "capabilities": ["git.push"]}).status_code == 422
        assert test_client.post("/api/v1/live/sessions", json={
            "interface": "web", "actor": "jelles",
            "capabilities": ["nope.everything"]}).status_code == 422
        assert test_client.get(
            "/api/v1/live/sessions/live-missing").status_code == 404


def test_live_context_bounded(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-ctx", "hostname": "h",
            "capabilities": []})
        session_id = test_client.post("/api/v1/live/sessions",
                                      json={
                                          "interface": "web",
                                          "actor": "jelles",
                                          "capabilities": [
                                              "node.read",
                                              "task.read"]}).json()[
                                                  "session_id"]
        package = test_client.post("/api/v1/live/context", json={
            "session_id": session_id, "query": "wat draait er?",
            "budget": 2000}).json()
        assert "nodes" in package["sections"]
        assert "tasks" in package["sections"]
        assert "git" not in package["sections"]
        assert package["used"] <= 2000
        assert test_client.post("/api/v1/live/context", json={
            "session_id": "live-missing"}).status_code == 404


def test_live_git_separation(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        session_id = test_client.post("/api/v1/live/sessions",
                                      json={
                                          "interface": "web",
                                          "actor": "jelles",
                                          "capabilities": [
                                              "git.read",
                                              "git.diff",
                                              "git.commit"],
                                          "context_scope": {
                                              "include_git": True}}).json()[
                                                  "session_id"]
        package = test_client.post("/api/v1/live/context", json={
            "session_id": session_id}).json()
        assert "git" in package["sections"]
        # Proposing a commit is allowed; push is not a thing.
        proposed = test_client.post("/api/v1/live/propose", json={
            "session_id": session_id, "kind": "push",
            "target": "main", "payload": {}}).status_code
        assert proposed == 422
        denied = test_client.post("/api/v1/live/propose", json={
            "session_id": session_id, "kind": "inventory_write",
            "target": "inventory:object", "payload": {}})
        assert denied.status_code == 403


def test_live_inventory_propose(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        session_id = test_client.post("/api/v1/live/sessions",
                                      json={
                                          "interface": "web",
                                          "actor": "jelles",
                                          "capabilities": [
                                              "inventory.propose_write"]
                                      }).json()["session_id"]
        proposed = test_client.post("/api/v1/live/propose", json={
            "session_id": session_id, "kind": "inventory_write",
            "target": "inventory:object",
            "payload": {"entity_type": "object",
                        "fields": {"name": "Livebout"}},
            "actor": "jelles"}).json()
        assert proposed["status"] == "proposed"
        assert proposed["proposal"]["provenance"][
            "human_verified"] is False
        assert test_client.post("/api/v1/live/propose", json={
            "session_id": session_id, "kind": "nope",
            "target": "x", "payload": {}}).status_code == 422


def test_watcher_and_reports(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        scanned = test_client.get(
            "/api/v1/watcher/scan").json()
        assert "findings" in scanned
        report = test_client.get(
            "/api/v1/reports/morning").json()
        assert report["sections"]
        titles = [section["title"] for section in
                  report["sections"]]
        assert "Missions" in titles
        assert "Tasks" in titles
        domains = test_client.get("/api/v1/domains").json()
        assert {entry["domain"] for entry in domains} == {
            "health", "skills", "ingestion"}
        assert all(entry["status"] == "planned"
                   for entry in domains)
        assert test_client.get(
            "/api/v1/domains/health").json()["status"] == "planned"
        assert test_client.get(
            "/api/v1/domains/garmin").status_code == 404
