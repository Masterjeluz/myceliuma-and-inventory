"""Tests voor INVENTory Milestone 3.3 — Camera-entiteit (world model only).

Uitsluitend tijdelijke databases via INVENTORY_DATABASE_PATH. Geen echte
gebruikersdata wordt geraakt. Geen echte camera wordt benaderd, geopend of
uitgelezen: alle tests beschrijven camera's als data, zoals elk ander
wereldmodel-record. Geen capture, geen streams, geen vision, geen AI.
"""
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path):
    os.environ["INVENTORY_DATABASE_PATH"] = str(tmp_path / "test_cam.db")
    import importlib
    import app.database as db_mod
    import app.main as main_mod
    importlib.reload(db_mod)
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


def make_camera(client, **overrides):
    payload = {"name": "Werkplaats USB-cam", "camera_type": "webcam"}
    payload.update(overrides)
    res = client.post("/api/v1/cameras", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


# =============================================================================
# CRUD
# =============================================================================

def test_create_camera(client):
    cam = make_camera(client, manufacturer="Logitech", model="C920",
                      description="werkplaats-overzicht", resolution="1920x1080",
                      status="available", capabilities=["video", "microfoon"],
                      interfaces=["usb"], metadata={"plek": "plafond"})
    assert cam["id"].startswith("cam_")
    assert cam["name"] == "Werkplaats USB-cam"
    assert cam["camera_type"] == "webcam"
    assert cam["manufacturer"] == "Logitech"
    assert cam["model"] == "C920"
    assert cam["resolution"] == "1920x1080"
    assert cam["status"] == "available"
    assert cam["capabilities"] == ["video", "microfoon"]
    assert cam["interfaces"] == ["usb"]
    assert cam["metadata"] == {"plek": "plafond"}


def test_read_camera(client):
    created = make_camera(client)
    res = client.get(f"/api/v1/cameras/{created['id']}")
    assert res.status_code == 200
    assert res.json() == created
    assert client.get("/api/v1/cameras/cam_bestaatniet").status_code == 404


def test_list_cameras(client):
    make_camera(client, name="Cam A", camera_type="webcam")
    make_camera(client, name="Cam B", camera_type="ip-camera")
    res = client.get("/api/v1/cameras")
    assert res.status_code == 200
    names = {cam["name"] for cam in res.json()}
    assert {"Cam A", "Cam B"} <= names


def test_update_camera(client):
    created = make_camera(client)
    res = client.patch(f"/api/v1/cameras/{created['id']}",
                       json={"status": "in_use", "resolution": "1280x720",
                             "capabilities": ["video"]})
    assert res.status_code == 200
    updated = res.json()
    assert updated["status"] == "in_use"
    assert updated["resolution"] == "1280x720"
    assert updated["capabilities"] == ["video"]
    assert updated["name"] == "Werkplaats USB-cam"
    assert client.patch("/api/v1/cameras/cam_bestaatniet",
                        json={"status": "retired"}).status_code == 404


def test_delete_camera(client):
    created = make_camera(client)
    assert client.delete(f"/api/v1/cameras/{created['id']}").status_code == 204
    assert client.get(f"/api/v1/cameras/{created['id']}").status_code == 404
    assert client.delete("/api/v1/cameras/cam_bestaatniet").status_code == 404


def test_camera_ids_unique(client):
    ids = {make_camera(client, name=f"Camera {i}")["id"] for i in range(5)}
    assert len(ids) == 5
    assert all(cam_id.startswith("cam_") for cam_id in ids)


# =============================================================================
# Validatie en provenance
# =============================================================================

def test_camera_validation(client):
    assert client.post("/api/v1/cameras", json={"camera_type": "x"}).status_code == 422
    assert client.post("/api/v1/cameras", json={"name": "x"}).status_code == 422
    assert client.post("/api/v1/cameras",
                       json={"name": "x", "camera_type": "y",
                             "status": "opnemen"}).status_code == 422


def test_camera_provenance_default(client):
    cam = make_camera(client)
    assert cam["provenance"]["source_type"] == "user-created"
    assert cam["provenance"]["human_verified"] is True
    events = client.get("/api/v1/events", params={"entity_id": cam["id"]}).json()
    assert events and events[0]["event_type"] == "camera_created"


def test_camera_ai_provenance_unverified(client):
    cam = make_camera(client, provenance={"source_type": "ai-generated",
                                          "creator_id": "test-model"})
    assert cam["provenance"]["source_type"] == "ai-generated"
    assert cam["provenance"]["human_verified"] is False


# =============================================================================
# Relatie met Hardware (bestaande predicaten, geen nieuwe)
# =============================================================================

def test_camera_relationship_with_hardware(client):
    cam = make_camera(client)
    hw = client.post("/api/v1/hardware",
                     json={"name": "Print Server",
                           "category": "single-board-computer"}).json()
    assert hw["id"].startswith("hw_")
    rel = client.post("/api/v1/relationships",
                      json={"from_id": cam["id"], "predicate": "part_of",
                            "to_id": hw["id"],
                            "metadata": {"montage": "behuizing"}}).json()
    assert rel["id"].startswith("rel_")
    assert rel["predicate"] == "part_of"
    linked = client.get("/api/v1/relationships",
                        params={"entity_id": cam["id"]}).json()
    assert [r["id"] for r in linked] == [rel["id"]]
    linked_hw = client.get("/api/v1/relationships",
                           params={"entity_id": hw["id"]}).json()
    assert [r["id"] for r in linked_hw] == [rel["id"]]


# =============================================================================
# Search en graph (M4-integratie)
# =============================================================================

def test_search_finds_camera(client):
    cam = make_camera(client, name="Unieke Microscoopcam", camera_type="microscoop",
                      manufacturer="ZoekCamFabrikant")
    res = client.get("/api/v1/search", params={"q": "Microscoopcam"})
    assert res.status_code == 200
    found = {(r["entity_type"], r["entity_id"]) for r in res.json()["results"]}
    assert ("camera", cam["id"]) in found
    res = client.get("/api/v1/search",
                     params={"q": "ZoekCamFabrikant", "type": "cameras"})
    assert res.status_code == 200
    assert {(r["entity_type"], r["entity_id"]) for r in res.json()["results"]} == {
        ("camera", cam["id"])}


def test_graph_shows_camera(client):
    cam = make_camera(client)
    hw = client.post("/api/v1/hardware",
                     json={"name": "Cam Server", "category": "node"}).json()
    client.post("/api/v1/relationships",
                json={"from_id": cam["id"], "predicate": "part_of",
                      "to_id": hw["id"]})
    res = client.get("/api/v1/graph", params={"entity_id": cam["id"], "depth": 1})
    assert res.status_code == 200
    data = res.json()
    by_id = {n["entity_id"]: n for n in data["nodes"]}
    assert by_id[cam["id"]]["entity_type"] == "camera"
    assert by_id[cam["id"]]["provenance"]["source_type"]
    assert hw["id"] in by_id
    res = client.get("/api/v1/graph", params={"entity_id": hw["id"], "depth": 1})
    assert cam["id"] in {n["entity_id"] for n in res.json()["nodes"]}


# =============================================================================
# UI (bestaand server-rendered patroon)
# =============================================================================

def test_camera_ui_pages(client):
    cam = make_camera(client)
    index = client.get("/cameras")
    assert index.status_code == 200
    assert "Werkplaats USB-cam" in index.text
    detail = client.get(f"/cameras/{cam['id']}")
    assert detail.status_code == 200
    assert "webcam" in detail.text
    assert f"/graph/{cam['id']}" in detail.text
    assert client.get("/cameras/cam_bestaatniet").status_code == 404
