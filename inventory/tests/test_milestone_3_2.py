"""Tests voor INVENTory Milestone 3.2 — Sensor-entiteit (world model only).

Uitsluitend tijdelijke databases via INVENTORY_DATABASE_PATH. Geen echte
gebruikersdata wordt geraakt. Geen echte sensor wordt benaderd of uitgelezen:
alle tests beschrijven sensoren als data, zoals elk ander wereldmodel-record.
"""
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path):
    os.environ["INVENTORY_DATABASE_PATH"] = str(tmp_path / "test_sns.db")
    import importlib
    import app.database as db_mod
    import app.main as main_mod
    importlib.reload(db_mod)
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


def make_sensor(client, **overrides):
    payload = {"name": "DHT22 Woonkamer", "sensor_type": "temperatuur"}
    payload.update(overrides)
    res = client.post("/api/v1/sensors", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


# =============================================================================
# CRUD
# =============================================================================

def test_create_sensor(client):
    sns = make_sensor(client, manufacturer="Aosong", model="DHT22",
                      description="woonkamer klimaat", unit="°C",
                      measurement_type="float", status="available",
                      capabilities=["temperature", "humidity"],
                      interfaces=["gpio"], metadata={"kamer": "woonkamer"})
    assert sns["id"].startswith("sns_")
    assert sns["name"] == "DHT22 Woonkamer"
    assert sns["sensor_type"] == "temperatuur"
    assert sns["manufacturer"] == "Aosong"
    assert sns["model"] == "DHT22"
    assert sns["unit"] == "°C"
    assert sns["measurement_type"] == "float"
    assert sns["status"] == "available"
    assert sns["capabilities"] == ["temperature", "humidity"]
    assert sns["interfaces"] == ["gpio"]
    assert sns["metadata"] == {"kamer": "woonkamer"}


def test_read_sensor(client):
    created = make_sensor(client)
    res = client.get(f"/api/v1/sensors/{created['id']}")
    assert res.status_code == 200
    assert res.json() == created
    assert client.get("/api/v1/sensors/sns_bestaatniet").status_code == 404


def test_list_sensors(client):
    make_sensor(client, name="Sensor A", sensor_type="temperatuur")
    make_sensor(client, name="Sensor B", sensor_type="luchtvochtigheid")
    res = client.get("/api/v1/sensors")
    assert res.status_code == 200
    names = {sns["name"] for sns in res.json()}
    assert {"Sensor A", "Sensor B"} <= names


def test_update_sensor(client):
    created = make_sensor(client)
    res = client.patch(f"/api/v1/sensors/{created['id']}",
                       json={"status": "in_use", "unit": "°F",
                             "interfaces": ["gpio", "i2c"]})
    assert res.status_code == 200
    updated = res.json()
    assert updated["status"] == "in_use"
    assert updated["unit"] == "°F"
    assert updated["interfaces"] == ["gpio", "i2c"]
    assert updated["name"] == "DHT22 Woonkamer"
    assert client.patch("/api/v1/sensors/sns_bestaatniet",
                        json={"status": "retired"}).status_code == 404


def test_delete_sensor(client):
    created = make_sensor(client)
    assert client.delete(f"/api/v1/sensors/{created['id']}").status_code == 204
    assert client.get(f"/api/v1/sensors/{created['id']}").status_code == 404
    assert client.delete("/api/v1/sensors/sns_bestaatniet").status_code == 404


def test_sensor_ids_unique(client):
    ids = {make_sensor(client, name=f"Sensor {i}")["id"] for i in range(5)}
    assert len(ids) == 5
    assert all(sns_id.startswith("sns_") for sns_id in ids)


# =============================================================================
# Validatie en provenance
# =============================================================================

def test_sensor_validation(client):
    assert client.post("/api/v1/sensors", json={"sensor_type": "x"}).status_code == 422
    assert client.post("/api/v1/sensors", json={"name": "x"}).status_code == 422
    assert client.post("/api/v1/sensors",
                       json={"name": "x", "sensor_type": "y",
                             "status": "kapot"}).status_code == 422


def test_sensor_provenance_default(client):
    sns = make_sensor(client)
    assert sns["provenance"]["source_type"] == "user-created"
    assert sns["provenance"]["human_verified"] is True
    events = client.get("/api/v1/events", params={"entity_id": sns["id"]}).json()
    assert events and events[0]["event_type"] == "sensor_created"


def test_sensor_ai_provenance_unverified(client):
    sns = make_sensor(client, provenance={"source_type": "ai-generated",
                                          "creator_id": "test-model"})
    assert sns["provenance"]["source_type"] == "ai-generated"
    assert sns["provenance"]["human_verified"] is False


# =============================================================================
# Relatie met Hardware (bestaande predicaten, geen nieuwe)
# =============================================================================

def test_sensor_relationship_with_hardware(client):
    sns = make_sensor(client)
    hw = client.post("/api/v1/hardware",
                     json={"name": "Raspberry Pi 5",
                           "category": "single-board-computer"}).json()
    assert hw["id"].startswith("hw_")
    rel = client.post("/api/v1/relationships",
                      json={"from_id": sns["id"], "predicate": "part_of",
                            "to_id": hw["id"],
                            "metadata": {"aansluiting": "gpio"}}).json()
    assert rel["id"].startswith("rel_")
    assert rel["predicate"] == "part_of"
    linked = client.get("/api/v1/relationships",
                        params={"entity_id": sns["id"]}).json()
    assert [r["id"] for r in linked] == [rel["id"]]
    linked_hw = client.get("/api/v1/relationships",
                           params={"entity_id": hw["id"]}).json()
    assert [r["id"] for r in linked_hw] == [rel["id"]]


# =============================================================================
# Search en graph (M4-integratie)
# =============================================================================

def test_search_finds_sensor(client):
    sns = make_sensor(client, name="Unieke Bodemsensor", sensor_type="bodemvocht",
                      manufacturer="ZoekSensorFabrikant")
    res = client.get("/api/v1/search", params={"q": "Bodemsensor"})
    assert res.status_code == 200
    found = {(r["entity_type"], r["entity_id"]) for r in res.json()["results"]}
    assert ("sensor", sns["id"]) in found
    res = client.get("/api/v1/search",
                     params={"q": "ZoekSensorFabrikant", "type": "sensors"})
    assert res.status_code == 200
    assert {(r["entity_type"], r["entity_id"]) for r in res.json()["results"]} == {
        ("sensor", sns["id"])}


def test_graph_shows_sensor(client):
    sns = make_sensor(client)
    hw = client.post("/api/v1/hardware",
                     json={"name": "Weerstation", "category": "node"}).json()
    client.post("/api/v1/relationships",
                json={"from_id": sns["id"], "predicate": "part_of",
                      "to_id": hw["id"]})
    res = client.get("/api/v1/graph", params={"entity_id": sns["id"], "depth": 1})
    assert res.status_code == 200
    data = res.json()
    by_id = {n["entity_id"]: n for n in data["nodes"]}
    assert by_id[sns["id"]]["entity_type"] == "sensor"
    assert by_id[sns["id"]]["provenance"]["source_type"]
    assert hw["id"] in by_id
    res = client.get("/api/v1/graph", params={"entity_id": hw["id"], "depth": 1})
    assert sns["id"] in {n["entity_id"] for n in res.json()["nodes"]}


# =============================================================================
# UI (bestaand server-rendered patroon)
# =============================================================================

def test_sensor_ui_pages(client):
    sns = make_sensor(client)
    index = client.get("/sensors")
    assert index.status_code == 200
    assert "DHT22 Woonkamer" in index.text
    detail = client.get(f"/sensors/{sns['id']}")
    assert detail.status_code == 200
    assert "temperatuur" in detail.text
    assert f"/graph/{sns['id']}" in detail.text
    assert client.get("/sensors/sns_bestaatniet").status_code == 404
