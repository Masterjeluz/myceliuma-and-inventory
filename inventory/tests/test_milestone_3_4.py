"""Tests voor INVENTory Milestone 3.4 — Location-entiteit (world model only).

Uitsluitend tijdelijke databases via INVENTORY_DATABASE_PATH. Geen echte
gebruikersdata wordt geraakt. Geen GPS, vision, SLAM, 3D of sensoruitlezing:
alle tests beschrijven locaties als data. Hiërarchie loopt uitsluitend via
bestaande relationships (part_of), nooit via een tweede mechanisme.
"""
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path):
    os.environ["INVENTORY_DATABASE_PATH"] = str(tmp_path / "test_loc.db")
    import importlib
    import app.database as db_mod
    import app.main as main_mod
    importlib.reload(db_mod)
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


def make_location(client, **overrides):
    payload = {"name": "Werkplaats", "location_type": "kamer"}
    payload.update(overrides)
    res = client.post("/api/v1/locations", json=payload)
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

def test_create_location(client):
    loc = make_location(client, description="klusruimte begane grond",
                        status="in_use", metadata={"verdieping": 0})
    assert loc["id"].startswith("loc_")
    assert loc["name"] == "Werkplaats"
    assert loc["location_type"] == "kamer"
    assert loc["description"] == "klusruimte begane grond"
    assert loc["status"] == "in_use"
    assert loc["metadata"] == {"verdieping": 0}


def test_read_location(client):
    created = make_location(client)
    res = client.get(f"/api/v1/locations/{created['id']}")
    assert res.status_code == 200
    assert res.json() == created
    assert client.get("/api/v1/locations/loc_bestaatniet").status_code == 404


def test_list_locations(client):
    make_location(client, name="Garage", location_type="garage")
    make_location(client, name="Kast", location_type="kast")
    res = client.get("/api/v1/locations")
    assert res.status_code == 200
    names = {loc["name"] for loc in res.json()}
    assert {"Garage", "Kast"} <= names


def test_update_location(client):
    created = make_location(client)
    res = client.patch(f"/api/v1/locations/{created['id']}",
                       json={"status": "maintenance",
                             "description": "tijdelijk in onderhoud"})
    assert res.status_code == 200
    updated = res.json()
    assert updated["status"] == "maintenance"
    assert updated["description"] == "tijdelijk in onderhoud"
    assert updated["name"] == "Werkplaats"
    assert client.patch("/api/v1/locations/loc_bestaatniet",
                        json={"status": "retired"}).status_code == 404


def test_delete_location(client):
    created = make_location(client)
    assert client.delete(f"/api/v1/locations/{created['id']}").status_code == 204
    assert client.get(f"/api/v1/locations/{created['id']}").status_code == 404
    assert client.delete("/api/v1/locations/loc_bestaatniet").status_code == 404


def test_location_ids_unique(client):
    ids = {make_location(client, name=f"Plek {i}")["id"] for i in range(5)}
    assert len(ids) == 5
    assert all(loc_id.startswith("loc_") for loc_id in ids)


# =============================================================================
# Validatie en provenance
# =============================================================================

def test_location_validation(client):
    assert client.post("/api/v1/locations",
                       json={"location_type": "x"}).status_code == 422
    assert client.post("/api/v1/locations", json={"name": "x"}).status_code == 422
    assert client.post("/api/v1/locations",
                       json={"name": "x", "location_type": "y",
                             "status": "verhuisd"}).status_code == 422


def test_location_provenance_default(client):
    loc = make_location(client)
    assert loc["provenance"]["source_type"] == "user-created"
    assert loc["provenance"]["human_verified"] is True
    events = client.get("/api/v1/events", params={"entity_id": loc["id"]}).json()
    assert events and events[0]["event_type"] == "location_created"


def test_location_ai_provenance_unverified(client):
    loc = make_location(client, provenance={"source_type": "ai-generated",
                                            "creator_id": "test-model"})
    assert loc["provenance"]["source_type"] == "ai-generated"
    assert loc["provenance"]["human_verified"] is False


# =============================================================================
# Hiërarchie via bestaande relationships (part_of, geen nieuw predicaat)
# =============================================================================

def test_location_hierarchy_via_relationships(client):
    huis = make_location(client, name="Uniek Huis", location_type="huis")
    werkplaats = make_location(client, name="Unieke Werkplaats", location_type="kamer")
    werkbank = make_location(client, name="Unieke Werkbank", location_type="werkplek")
    relate(client, werkplaats["id"], "part_of", huis["id"])
    relate(client, werkbank["id"], "part_of", werkplaats["id"])
    res = client.get("/api/v1/graph",
                     params={"entity_id": werkbank["id"], "depth": 2})
    assert res.status_code == 200
    node_ids = {n["entity_id"] for n in res.json()["nodes"]}
    assert {huis["id"], werkplaats["id"], werkbank["id"]} <= node_ids
    predicates = {e["predicate"] for e in res.json()["edges"]}
    assert predicates == {"part_of"}


# =============================================================================
# Hardware / Sensor / Camera → Location (bestaand stored_in-predicaat)
# =============================================================================

def test_hardware_sensor_camera_to_location(client):
    loc = make_location(client, name="Unieke Schuur", location_type="schuur")
    hw = client.post("/api/v1/hardware",
                     json={"name": "Schuur Printer",
                           "category": "3d-printer"}).json()
    sns = client.post("/api/v1/sensors",
                      json={"name": "Schuur Sensor",
                            "sensor_type": "temperatuur"}).json()
    cam = client.post("/api/v1/cameras",
                      json={"name": "Schuur Cam",
                            "camera_type": "webcam"}).json()
    for entity in (hw, sns, cam):
        rel = relate(client, entity["id"], "stored_in", loc["id"])
        assert rel["predicate"] == "stored_in"
    linked = {r["from_id"] for r in client.get(
        "/api/v1/relationships", params={"entity_id": loc["id"]}).json()}
    assert linked == {hw["id"], sns["id"], cam["id"]}
    res = client.get("/api/v1/graph", params={"entity_id": loc["id"], "depth": 1})
    assert res.status_code == 200
    assert {hw["id"], sns["id"], cam["id"]} <= {
        n["entity_id"] for n in res.json()["nodes"]}


# =============================================================================
# Search en graph (M4-integratie)
# =============================================================================

def test_search_finds_location(client):
    loc = make_location(client, name="Unieke Kas", location_type="tuinkas")
    res = client.get("/api/v1/search", params={"q": "Unieke Kas"})
    assert res.status_code == 200
    found = {(r["entity_type"], r["entity_id"]) for r in res.json()["results"]}
    assert ("location", loc["id"]) in found
    res = client.get("/api/v1/search",
                     params={"q": "tuinkas", "type": "locations"})
    assert res.status_code == 200
    assert {(r["entity_type"], r["entity_id"]) for r in res.json()["results"]} == {
        ("location", loc["id"])}


def test_graph_shows_location(client):
    loc = make_location(client)
    hw = client.post("/api/v1/hardware",
                     json={"name": "Bank Printer", "category": "3d-printer"}).json()
    relate(client, hw["id"], "stored_in", loc["id"])
    res = client.get("/api/v1/graph", params={"entity_id": loc["id"], "depth": 1})
    assert res.status_code == 200
    data = res.json()
    by_id = {n["entity_id"]: n for n in data["nodes"]}
    assert by_id[loc["id"]]["entity_type"] == "location"
    assert by_id[loc["id"]]["provenance"]["source_type"]
    assert hw["id"] in by_id


# =============================================================================
# UI (bestaand server-rendered patroon)
# =============================================================================

def test_location_ui_pages(client):
    loc = make_location(client)
    index = client.get("/locations")
    assert index.status_code == 200
    assert "Werkplaats" in index.text
    detail = client.get(f"/locations/{loc['id']}")
    assert detail.status_code == 200
    assert "kamer" in detail.text
    assert f"/graph/{loc['id']}" in detail.text
    assert client.get("/locations/loc_bestaatniet").status_code == 404
