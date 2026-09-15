"""Tests voor INVENTory Milestone 3.6 — Task-entiteit (world model data only).

Uitsluitend tijdelijke databases via INVENTORY_DATABASE_PATH. Geen echte
gebruikersdata wordt geraakt. Een Task-record beschrijft werk; deze tests
voeren niets uit: geen subprocess, geen netwerk, geen hardware, geen AI.
"""
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path):
    os.environ["INVENTORY_DATABASE_PATH"] = str(tmp_path / "test_task.db")
    import importlib
    import app.database as db_mod
    import app.main as main_mod
    importlib.reload(db_mod)
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


def make_task(client, **overrides):
    payload = {"name": "Werkplaats inspecteren", "task_type": "inspect"}
    payload.update(overrides)
    res = client.post("/api/v1/tasks", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def relate(client, from_id, predicate, to_id):
    res = client.post("/api/v1/relationships",
                      json={"from_id": from_id, "predicate": predicate,
                            "to_id": to_id})
    assert res.status_code == 201, res.text
    return res.json()


# =============================================================================
# CRUD
# =============================================================================

def test_create_task(client):
    task = make_task(client, description="maandelijkse ronde",
                     status="ready", priority=7,
                     input_requirements=["werkplaats toegankelijk"],
                     expected_output="fotoreeks",
                     parameters={"diepte": 1}, metadata={"ronde": "maandelijks"})
    assert task["id"].startswith("task_")
    assert task["name"] == "Werkplaats inspecteren"
    assert task["task_type"] == "inspect"
    assert task["description"] == "maandelijkse ronde"
    assert task["status"] == "ready"
    assert task["priority"] == 7
    assert task["input_requirements"] == ["werkplaats toegankelijk"]
    assert task["expected_output"] == "fotoreeks"
    assert task["parameters"] == {"diepte": 1}
    assert task["metadata"] == {"ronde": "maandelijks"}


def test_read_task(client):
    created = make_task(client)
    res = client.get(f"/api/v1/tasks/{created['id']}")
    assert res.status_code == 200
    assert res.json() == created
    assert client.get("/api/v1/tasks/task_bestaatniet").status_code == 404


def test_list_tasks(client):
    make_task(client, name="Taak A", task_type="observe")
    make_task(client, name="Taak B", task_type="measure")
    res = client.get("/api/v1/tasks")
    assert res.status_code == 200
    names = {task["name"] for task in res.json()}
    assert {"Taak A", "Taak B"} <= names


def test_update_task(client):
    created = make_task(client)
    res = client.patch(f"/api/v1/tasks/{created['id']}",
                       json={"status": "completed", "priority": 9,
                             "expected_output": "rapport"})
    assert res.status_code == 200
    updated = res.json()
    assert updated["status"] == "completed"
    assert updated["priority"] == 9
    assert updated["expected_output"] == "rapport"
    assert updated["name"] == "Werkplaats inspecteren"
    assert client.patch("/api/v1/tasks/task_bestaatniet",
                        json={"status": "cancelled"}).status_code == 404


def test_delete_task(client):
    created = make_task(client)
    assert client.delete(f"/api/v1/tasks/{created['id']}").status_code == 204
    assert client.get(f"/api/v1/tasks/{created['id']}").status_code == 404
    assert client.delete("/api/v1/tasks/task_bestaatniet").status_code == 404


def test_task_ids_unique(client):
    ids = {make_task(client, name=f"Taak {i}")["id"] for i in range(5)}
    assert len(ids) == 5
    assert all(task_id.startswith("task_") for task_id in ids)


# =============================================================================
# Validatie: types, status, priority
# =============================================================================

def test_task_validation(client):
    assert client.post("/api/v1/tasks", json={"task_type": "inspect"}).status_code == 422
    assert client.post("/api/v1/tasks",
                       json={"name": "x", "task_type": "uitvoeren"}).status_code == 422
    assert client.post("/api/v1/tasks",
                       json={"name": "x", "status": "bezig"}).status_code == 422
    assert client.post("/api/v1/tasks",
                       json={"name": "x", "priority": 101}).status_code == 422
    assert client.post("/api/v1/tasks",
                       json={"name": "x", "priority": -1}).status_code == 422


def test_task_types_and_statuses_allowlist(client):
    for task_type in ("observe", "identify", "measure", "classify", "inspect",
                      "transform", "analyze", "monitor", "other"):
        task = make_task(client, name=f"Type {task_type}", task_type=task_type)
        assert task["task_type"] == task_type
    for status in ("pending", "ready", "running", "completed", "failed",
                   "cancelled"):
        task = make_task(client, name=f"Status {status}", status=status)
        assert task["status"] == status


# =============================================================================
# Provenance en events
# =============================================================================

def test_task_provenance_default_and_events(client):
    task = make_task(client)
    assert task["provenance"]["source_type"] == "user-created"
    assert task["provenance"]["human_verified"] is True
    events = client.get("/api/v1/events", params={"entity_id": task["id"]}).json()
    assert events and events[0]["event_type"] == "task_created"


def test_task_ai_provenance_unverified(client):
    task = make_task(client, provenance={"source_type": "ai-generated",
                                         "creator_id": "test-model"})
    assert task["provenance"]["source_type"] == "ai-generated"
    assert task["provenance"]["human_verified"] is False


# =============================================================================
# Relaties (bestaande predicaten, geen executie)
# =============================================================================

def test_task_relationships(client):
    task = make_task(client)
    mod = client.post("/api/v1/models",
                      json={"name": "Kijker", "model_type": "vision"}).json()
    cam = client.post("/api/v1/cameras",
                      json={"name": "Werkplaats Cam",
                            "camera_type": "webcam"}).json()
    hw = client.post("/api/v1/hardware",
                     json={"name": "Hoek Pi",
                           "category": "single-board-computer"}).json()
    rel_mod = relate(client, task["id"], "uses", mod["id"])
    rel_cam = relate(client, task["id"], "uses", cam["id"])
    rel_hw = relate(client, task["id"], "related_to", hw["id"])
    assert rel_mod["predicate"] == "uses"
    linked = {r["to_id"] for r in client.get(
        "/api/v1/relationships", params={"entity_id": task["id"]}).json()}
    assert linked == {mod["id"], cam["id"], hw["id"]}
    assert rel_cam["id"].startswith("rel_") and rel_hw["id"].startswith("rel_")


# =============================================================================
# Search en graph (M4-integratie)
# =============================================================================

def test_search_finds_task(client):
    task = make_task(client, name="Unieke Voorraadmeting", task_type="measure",
                     description="tel de moeren")
    res = client.get("/api/v1/search", params={"q": "Voorraadmeting"})
    assert res.status_code == 200
    found = {(r["entity_type"], r["entity_id"]) for r in res.json()["results"]}
    assert ("task", task["id"]) in found
    res = client.get("/api/v1/search", params={"q": "measure", "type": "tasks"})
    assert res.status_code == 200
    assert {(r["entity_type"], r["entity_id"]) for r in res.json()["results"]} == {
        ("task", task["id"])}


def test_graph_shows_task(client):
    task = make_task(client)
    mod = client.post("/api/v1/models",
                      json={"name": "Teller", "model_type": "detection"}).json()
    relate(client, task["id"], "uses", mod["id"])
    res = client.get("/api/v1/graph", params={"entity_id": task["id"], "depth": 1})
    assert res.status_code == 200
    data = res.json()
    by_id = {n["entity_id"]: n for n in data["nodes"]}
    assert by_id[task["id"]]["entity_type"] == "task"
    assert by_id[task["id"]]["provenance"]["source_type"]
    assert mod["id"] in by_id
    assert data["edges"][0]["predicate"] == "uses"
    res = client.get("/api/v1/graph", params={"entity_id": mod["id"], "depth": 1})
    assert task["id"] in {n["entity_id"] for n in res.json()["nodes"]}


# =============================================================================
# UI (bestaand server-rendered patroon)
# =============================================================================

def test_task_ui_pages(client):
    task = make_task(client)
    index = client.get("/tasks")
    assert index.status_code == 200
    assert "Werkplaats inspecteren" in index.text
    detail = client.get(f"/tasks/{task['id']}")
    assert detail.status_code == 200
    assert "inspect" in detail.text
    assert f"/graph/{task['id']}" in detail.text
    assert client.get("/tasks/task_bestaatniet").status_code == 404
