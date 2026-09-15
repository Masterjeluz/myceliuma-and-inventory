"""Tests voor INVENTory Milestone 3.5 — Model-entiteit (world model data only).

Uitsluitend tijdelijke databases via INVENTORY_DATABASE_PATH. Geen echte
gebruikersdata wordt geraakt. Dit zijn databeschrijvingen van modellen:
geen runtime, geen inference, geen downloads, geen netwerk, geen GPU.
"""
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path):
    os.environ["INVENTORY_DATABASE_PATH"] = str(tmp_path / "test_mod.db")
    import importlib
    import app.database as db_mod
    import app.main as main_mod
    importlib.reload(db_mod)
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


def make_model(client, **overrides):
    payload = {"name": "Moondream Lokale VLM", "model_type": "vlm"}
    payload.update(overrides)
    res = client.post("/api/v1/models", json=payload)
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

def test_create_model(client):
    mod = make_model(client, provider="lokaal", model_identifier="moondream2",
                     description="beeldbeschrijving werkplaats", version="2026-09",
                     status="available", capabilities=["image_description", "ocr"],
                     interfaces=["http"], metadata={"geheugen": "lichtgewicht"})
    assert mod["id"].startswith("mod_")
    assert mod["name"] == "Moondream Lokale VLM"
    assert mod["provider"] == "lokaal"
    assert mod["model_identifier"] == "moondream2"
    assert mod["model_type"] == "vlm"
    assert mod["version"] == "2026-09"
    assert mod["status"] == "available"
    assert mod["capabilities"] == ["image_description", "ocr"]
    assert mod["interfaces"] == ["http"]
    assert mod["metadata"] == {"geheugen": "lichtgewicht"}


def test_read_model(client):
    created = make_model(client)
    res = client.get(f"/api/v1/models/{created['id']}")
    assert res.status_code == 200
    assert res.json() == created
    assert client.get("/api/v1/models/mod_bestaatniet").status_code == 404


def test_list_models(client):
    make_model(client, name="Model A", model_type="ocr")
    make_model(client, name="Model B", model_type="llm")
    res = client.get("/api/v1/models")
    assert res.status_code == 200
    names = {mod["name"] for mod in res.json()}
    assert {"Model A", "Model B"} <= names


def test_update_model(client):
    created = make_model(client)
    res = client.patch(f"/api/v1/models/{created['id']}",
                       json={"status": "in_use", "version": "2026-10",
                             "capabilities": ["image_description"]})
    assert res.status_code == 200
    updated = res.json()
    assert updated["status"] == "in_use"
    assert updated["version"] == "2026-10"
    assert updated["capabilities"] == ["image_description"]
    assert updated["name"] == "Moondream Lokale VLM"
    assert client.patch("/api/v1/models/mod_bestaatniet",
                        json={"status": "retired"}).status_code == 404


def test_delete_model(client):
    created = make_model(client)
    assert client.delete(f"/api/v1/models/{created['id']}").status_code == 204
    assert client.get(f"/api/v1/models/{created['id']}").status_code == 404
    assert client.delete("/api/v1/models/mod_bestaatniet").status_code == 404


def test_model_ids_unique(client):
    ids = {make_model(client, name=f"Model {i}")["id"] for i in range(5)}
    assert len(ids) == 5
    assert all(mod_id.startswith("mod_") for mod_id in ids)


# =============================================================================
# Validatie, types, provenance
# =============================================================================

def test_model_validation(client):
    assert client.post("/api/v1/models", json={"model_type": "vlm"}).status_code == 422
    assert client.post("/api/v1/models",
                       json={"name": "x", "model_type": "telepathie"}).status_code == 422


def test_model_types_allowlist(client):
    for model_type in ("llm", "vlm", "vision", "detection", "ocr",
                       "speech_to_text", "embedding", "other"):
        mod = make_model(client, name=f"Type {model_type}", model_type=model_type)
        assert mod["model_type"] == model_type


def test_model_provenance_default_and_events(client):
    mod = make_model(client)
    assert mod["provenance"]["source_type"] == "user-created"
    assert mod["provenance"]["human_verified"] is True
    events = client.get("/api/v1/events", params={"entity_id": mod["id"]}).json()
    assert events and events[0]["event_type"] == "model_created"


def test_model_ai_provenance_unverified(client):
    mod = make_model(client, provenance={"source_type": "ai-generated",
                                         "creator_id": "test-model"})
    assert mod["provenance"]["source_type"] == "ai-generated"
    assert mod["provenance"]["human_verified"] is False


# =============================================================================
# Relaties (bestaande predicaten: uses / related_to, geen runs_on)
# =============================================================================

def test_model_relationships(client):
    mod = make_model(client)
    hw = client.post("/api/v1/hardware",
                     json={"name": "Edge Pi", "category": "single-board-computer"}).json()
    cam = client.post("/api/v1/cameras",
                      json={"name": "Werkplaats Cam", "camera_type": "webcam"}).json()
    loc = client.post("/api/v1/locations",
                      json={"name": "Werkplaats", "location_type": "kamer"}).json()
    rel_hw = relate(client, mod["id"], "uses", hw["id"])
    rel_cam = relate(client, mod["id"], "related_to", cam["id"])
    rel_loc = relate(client, mod["id"], "related_to", loc["id"])
    assert rel_hw["predicate"] == "uses"
    linked = {r["to_id"] for r in client.get(
        "/api/v1/relationships", params={"entity_id": mod["id"]}).json()}
    assert linked == {hw["id"], cam["id"], loc["id"]}
    assert rel_cam["id"].startswith("rel_") and rel_loc["id"].startswith("rel_")


# =============================================================================
# Search en graph (M4-integratie)
# =============================================================================

def test_search_finds_model(client):
    mod = make_model(client, name="Unieke YOLO Detector", model_type="detection",
                     provider="ZoekModelProvider", model_identifier="uniekeyolo")
    res = client.get("/api/v1/search", params={"q": "Unieke YOLO"})
    assert res.status_code == 200
    found = {(r["entity_type"], r["entity_id"]) for r in res.json()["results"]}
    assert ("model", mod["id"]) in found
    res = client.get("/api/v1/search",
                     params={"q": "ZoekModelProvider", "type": "models"})
    assert res.status_code == 200
    assert {(r["entity_type"], r["entity_id"]) for r in res.json()["results"]} == {
        ("model", mod["id"])}
    res = client.get("/api/v1/search", params={"q": "uniekeyolo"})
    assert ("model", mod["id"]) in {
        (r["entity_type"], r["entity_id"]) for r in res.json()["results"]}


def test_graph_shows_model(client):
    mod = make_model(client)
    hw = client.post("/api/v1/hardware",
                     json={"name": "Inferentie Pi",
                           "category": "single-board-computer"}).json()
    relate(client, mod["id"], "uses", hw["id"])
    res = client.get("/api/v1/graph", params={"entity_id": mod["id"], "depth": 1})
    assert res.status_code == 200
    data = res.json()
    by_id = {n["entity_id"]: n for n in data["nodes"]}
    assert by_id[mod["id"]]["entity_type"] == "model"
    assert by_id[mod["id"]]["provenance"]["source_type"]
    assert hw["id"] in by_id
    assert data["edges"][0]["predicate"] == "uses"
    res = client.get("/api/v1/graph", params={"entity_id": hw["id"], "depth": 1})
    assert mod["id"] in {n["entity_id"] for n in res.json()["nodes"]}


# =============================================================================
# UI (bestaand server-rendered patroon)
# =============================================================================

def test_model_ui_pages(client):
    mod = make_model(client)
    index = client.get("/models")
    assert index.status_code == 200
    assert "Moondream Lokale VLM" in index.text
    detail = client.get(f"/models/{mod['id']}")
    assert detail.status_code == 200
    assert "vlm" in detail.text
    assert f"/graph/{mod['id']}" in detail.text
    assert client.get("/models/mod_bestaatniet").status_code == 404
