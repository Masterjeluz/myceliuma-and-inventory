"""Tests voor INVENTory Milestone 3.1 — Hardware-entiteit.

Uitsluitend tijdelijke databases via INVENTORY_DATABASE_PATH. Geen echte
gebruikersdata wordt geraakt. Geen echte hardware wordt benaderd: alle tests
beschrijven hardware als data, zoals elk ander wereldmodel-record.
"""
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path):
    os.environ["INVENTORY_DATABASE_PATH"] = str(tmp_path / "test_hw.db")
    import importlib
    import app.database as db_mod
    import app.main as main_mod
    importlib.reload(db_mod)
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


def make_hw(client, **overrides):
    payload = {"name": "Raspberry Pi 5", "category": "single-board-computer"}
    payload.update(overrides)
    res = client.post("/api/v1/hardware", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


# =============================================================================
# CRUD
# =============================================================================

def test_create_hardware(client):
    hw = make_hw(client, manufacturer="Raspberry Pi Ltd", model="Pi 5 8GB",
                 description="werkplaats-controller", status="available",
                 capabilities=["gpio", "wifi"], interfaces=["usb-c", "hdmi"],
                 metadata={"locatie": "werkbank"})
    assert hw["id"].startswith("hw_")
    assert hw["name"] == "Raspberry Pi 5"
    assert hw["manufacturer"] == "Raspberry Pi Ltd"
    assert hw["model"] == "Pi 5 8GB"
    assert hw["category"] == "single-board-computer"
    assert hw["status"] == "available"
    assert hw["capabilities"] == ["gpio", "wifi"]
    assert hw["interfaces"] == ["usb-c", "hdmi"]
    assert hw["metadata"] == {"locatie": "werkbank"}


def test_read_hardware(client):
    created = make_hw(client)
    res = client.get(f"/api/v1/hardware/{created['id']}")
    assert res.status_code == 200
    assert res.json() == created
    assert client.get("/api/v1/hardware/hw_bestaatniet").status_code == 404


def test_list_hardware(client):
    make_hw(client, name="Printer A", category="3d-printer")
    make_hw(client, name="Laptop B", category="computer")
    res = client.get("/api/v1/hardware")
    assert res.status_code == 200
    names = {hw["name"] for hw in res.json()}
    assert {"Printer A", "Laptop B"} <= names


def test_update_hardware(client):
    created = make_hw(client)
    res = client.patch(f"/api/v1/hardware/{created['id']}",
                       json={"status": "in_use", "capabilities": ["gpio"],
                             "description": "nu in gebruik"})
    assert res.status_code == 200
    updated = res.json()
    assert updated["status"] == "in_use"
    assert updated["capabilities"] == ["gpio"]
    assert updated["description"] == "nu in gebruik"
    assert updated["name"] == "Raspberry Pi 5"
    assert client.patch("/api/v1/hardware/hw_bestaatniet",
                        json={"status": "retired"}).status_code == 404


def test_delete_hardware(client):
    created = make_hw(client)
    assert client.delete(f"/api/v1/hardware/{created['id']}").status_code == 204
    assert client.get(f"/api/v1/hardware/{created['id']}").status_code == 404
    assert client.delete("/api/v1/hardware/hw_bestaatniet").status_code == 404


def test_hardware_ids_unique(client):
    ids = {make_hw(client, name=f"Apparaat {i}")["id"] for i in range(5)}
    assert len(ids) == 5
    assert all(hw_id.startswith("hw_") for hw_id in ids)


# =============================================================================
# Validatie en provenance
# =============================================================================

def test_hardware_validation(client):
    assert client.post("/api/v1/hardware", json={"category": "x"}).status_code == 422
    assert client.post("/api/v1/hardware", json={"name": "x"}).status_code == 422
    assert client.post("/api/v1/hardware",
                       json={"name": "x", "category": "y",
                             "status": "vliegend"}).status_code == 422


def test_hardware_provenance_default(client):
    hw = make_hw(client)
    assert hw["provenance"]["source_type"] == "user-created"
    assert hw["provenance"]["human_verified"] is True
    events = client.get("/api/v1/events", params={"entity_id": hw["id"]}).json()
    assert events and events[0]["event_type"] == "hardware_created"


def test_hardware_ai_provenance_unverified(client):
    hw = make_hw(client, provenance={"source_type": "ai-generated",
                                     "creator_id": "test-model"})
    assert hw["provenance"]["source_type"] == "ai-generated"
    assert hw["provenance"]["human_verified"] is False


# =============================================================================
# Relaties (bestaande predicaten, geen nieuwe)
# =============================================================================

def test_hardware_relationship_with_project(client):
    hw = make_hw(client)
    proj = client.post("/api/v1/projects", json={"name": "Printer Build"}).json()
    rel = client.post("/api/v1/relationships",
                      json={"from_id": hw["id"], "predicate": "used_in",
                            "to_id": proj["id"],
                            "metadata": {"rol": "controller"}}).json()
    assert rel["id"].startswith("rel_")
    assert rel["predicate"] == "used_in"
    linked = client.get("/api/v1/relationships",
                        params={"entity_id": hw["id"]}).json()
    assert [r["id"] for r in linked] == [rel["id"]]


# =============================================================================
# Search en graph (M4-integratie)
# =============================================================================

def test_search_finds_hardware(client):
    hw = make_hw(client, name="Unieke Boormachine", category="gereedschap",
                 manufacturer="ZoekFabrikant")
    res = client.get("/api/v1/search", params={"q": "Boormachine"})
    assert res.status_code == 200
    found = {(r["entity_type"], r["entity_id"]) for r in res.json()["results"]}
    assert ("hardware", hw["id"]) in found
    res = client.get("/api/v1/search",
                     params={"q": "ZoekFabrikant", "type": "hardware"})
    assert res.status_code == 200
    assert {(r["entity_type"], r["entity_id"]) for r in res.json()["results"]} == {
        ("hardware", hw["id"])}


def test_graph_shows_hardware(client):
    hw = make_hw(client)
    proj = client.post("/api/v1/projects", json={"name": "Bouw"}).json()
    client.post("/api/v1/relationships",
                json={"from_id": hw["id"], "predicate": "used_in",
                      "to_id": proj["id"]})
    res = client.get("/api/v1/graph", params={"entity_id": hw["id"], "depth": 1})
    assert res.status_code == 200
    data = res.json()
    by_id = {n["entity_id"]: n for n in data["nodes"]}
    assert by_id[hw["id"]]["entity_type"] == "hardware"
    assert by_id[hw["id"]]["provenance"]["source_type"]
    assert proj["id"] in by_id
    res = client.get("/api/v1/graph", params={"entity_id": proj["id"], "depth": 1})
    assert hw["id"] in {n["entity_id"] for n in res.json()["nodes"]}


# =============================================================================
# UI (bestaand server-rendered patroon)
# =============================================================================

def test_hardware_ui_pages(client):
    hw = make_hw(client)
    index = client.get("/hardware")
    assert index.status_code == 200
    assert "Raspberry Pi 5" in index.text
    detail = client.get(f"/hardware/{hw['id']}")
    assert detail.status_code == 200
    assert "single-board-computer" in detail.text
    assert f"/graph/{hw['id']}" in detail.text
    assert client.get("/hardware/hw_bestaatniet").status_code == 404
