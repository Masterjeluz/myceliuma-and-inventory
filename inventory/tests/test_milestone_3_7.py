"""Tests voor INVENTory Milestone 3.7 — Actuator-entiteit (world model only).

Uitsluitend tijdelijke databases via INVENTORY_DATABASE_PATH. Geen echte
gebruikersdata wordt geraakt. Een Actuator-record beschrijft een mogelijke
uitvoerder; deze tests voeren niets uit: geen GPIO, geen drivers, geen
netwerk, geen hardware. Alleen data, zoals elk ander wereldmodel-record.
"""
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path):
    os.environ["INVENTORY_DATABASE_PATH"] = str(tmp_path / "test_act.db")
    import importlib
    import app.database as db_mod
    import app.main as main_mod
    importlib.reload(db_mod)
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


def make_actuator(client, **overrides):
    payload = {"name": "Ventilator Werkplaats", "actuator_type": "fan"}
    payload.update(overrides)
    res = client.post("/api/v1/actuators", json=payload)
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

def test_create_actuator(client):
    act = make_actuator(client, manufacturer="Noctua", model="NF-A12",
                        description="luchtcirculatie werkplaats",
                        status="available",
                        capabilities=["turn_on", "turn_off", "set_speed"],
                        interfaces=["pwm"], parameters={"pwm_pin": 18},
                        metadata={"plek": "plafond"})
    assert act["id"].startswith("act_")
    assert act["name"] == "Ventilator Werkplaats"
    assert act["actuator_type"] == "fan"
    assert act["manufacturer"] == "Noctua"
    assert act["model"] == "NF-A12"
    assert act["status"] == "available"
    assert act["capabilities"] == ["turn_on", "turn_off", "set_speed"]
    assert act["interfaces"] == ["pwm"]
    assert act["parameters"] == {"pwm_pin": 18}
    assert act["metadata"] == {"plek": "plafond"}


def test_read_actuator(client):
    created = make_actuator(client)
    res = client.get(f"/api/v1/actuators/{created['id']}")
    assert res.status_code == 200
    assert res.json() == created
    assert client.get("/api/v1/actuators/act_bestaatniet").status_code == 404


def test_list_actuators(client):
    make_actuator(client, name="Relais A", actuator_type="relay")
    make_actuator(client, name="Led B", actuator_type="led")
    res = client.get("/api/v1/actuators")
    assert res.status_code == 200
    names = {act["name"] for act in res.json()}
    assert {"Relais A", "Led B"} <= names


def test_update_actuator(client):
    created = make_actuator(client)
    res = client.patch(f"/api/v1/actuators/{created['id']}",
                       json={"status": "in_use",
                             "capabilities": ["turn_on", "turn_off"],
                             "parameters": {"pwm_pin": 19}})
    assert res.status_code == 200
    updated = res.json()
    assert updated["status"] == "in_use"
    assert updated["capabilities"] == ["turn_on", "turn_off"]
    assert updated["parameters"] == {"pwm_pin": 19}
    assert updated["name"] == "Ventilator Werkplaats"
    assert client.patch("/api/v1/actuators/act_bestaatniet",
                        json={"status": "retired"}).status_code == 404


def test_delete_actuator(client):
    created = make_actuator(client)
    assert client.delete(f"/api/v1/actuators/{created['id']}").status_code == 204
    assert client.get(f"/api/v1/actuators/{created['id']}").status_code == 404
    assert client.delete("/api/v1/actuators/act_bestaatniet").status_code == 404


def test_actuator_ids_unique(client):
    ids = {make_actuator(client, name=f"Actuator {i}")["id"] for i in range(5)}
    assert len(ids) == 5
    assert all(act_id.startswith("act_") for act_id in ids)


# =============================================================================
# Validatie: types en status
# =============================================================================

def test_actuator_validation(client):
    assert client.post("/api/v1/actuators",
                       json={"actuator_type": "fan"}).status_code == 422


def test_actuator_types_allowlist(client):
    for actuator_type in ("motor", "relay", "led", "servo", "pump", "valve",
                          "heater", "fan", "display", "speaker", "robotic",
                          "other"):
        act = make_actuator(client, name=f"Type {actuator_type}",
                            actuator_type=actuator_type)
        assert act["actuator_type"] == actuator_type
    assert client.post("/api/v1/actuators",
                       json={"name": "x",
                             "actuator_type": "teleport"}).status_code == 422


def test_actuator_status_allowlist(client):
    for status in ("available", "in_use", "maintenance", "retired", "unknown"):
        act = make_actuator(client, name=f"Status {status}", status=status)
        assert act["status"] == status


# =============================================================================
# Provenance en events
# =============================================================================

def test_actuator_provenance_default_and_events(client):
    act = make_actuator(client)
    assert act["provenance"]["source_type"] == "user-created"
    assert act["provenance"]["human_verified"] is True
    events = client.get("/api/v1/events", params={"entity_id": act["id"]}).json()
    assert events and events[0]["event_type"] == "actuator_created"


def test_actuator_ai_provenance_unverified(client):
    act = make_actuator(client, provenance={"source_type": "ai-generated",
                                            "creator_id": "test-model"})
    assert act["provenance"]["source_type"] == "ai-generated"
    assert act["provenance"]["human_verified"] is False


# =============================================================================
# Relaties: datarelaties, geen executie (bestaande predicaten)
# =============================================================================

def test_actuator_relationships(client):
    act = make_actuator(client)
    hw = client.post("/api/v1/hardware",
                     json={"name": "Ventilator Controller",
                           "category": "single-board-computer"}).json()
    loc = client.post("/api/v1/locations",
                      json={"name": "Werkplaats",
                            "location_type": "kamer"}).json()
    task = client.post("/api/v1/tasks",
                       json={"name": "Luchten", "task_type": "other"}).json()
    rel_hw = relate(client, act["id"], "part_of", hw["id"])
    rel_loc = relate(client, act["id"], "stored_in", loc["id"])
    rel_task = relate(client, act["id"], "related_to", task["id"])
    assert rel_hw["predicate"] == "part_of"
    assert rel_loc["predicate"] == "stored_in"
    assert rel_task["predicate"] == "related_to"
    linked = {r["to_id"] for r in client.get(
        "/api/v1/relationships", params={"entity_id": act["id"]}).json()}
    assert linked == {hw["id"], loc["id"], task["id"]}


# =============================================================================
# Search en graph (M4-integratie)
# =============================================================================

def test_search_finds_actuator(client):
    act = make_actuator(client, name="Unieke Klep", actuator_type="valve",
                        manufacturer="ZoekActFabrikant")
    res = client.get("/api/v1/search", params={"q": "Unieke Klep"})
    assert res.status_code == 200
    found = {(r["entity_type"], r["entity_id"]) for r in res.json()["results"]}
    assert ("actuator", act["id"]) in found
    res = client.get("/api/v1/search",
                     params={"q": "ZoekActFabrikant", "type": "actuators"})
    assert res.status_code == 200
    assert {(r["entity_type"], r["entity_id"]) for r in res.json()["results"]} == {
        ("actuator", act["id"])}


def test_graph_shows_actuator(client):
    act = make_actuator(client)
    hw = client.post("/api/v1/hardware",
                     json={"name": "Relais Bord", "category": "controller"}).json()
    relate(client, act["id"], "part_of", hw["id"])
    res = client.get("/api/v1/graph", params={"entity_id": act["id"], "depth": 1})
    assert res.status_code == 200
    data = res.json()
    by_id = {n["entity_id"]: n for n in data["nodes"]}
    assert by_id[act["id"]]["entity_type"] == "actuator"
    assert by_id[act["id"]]["provenance"]["source_type"]
    assert hw["id"] in by_id
    assert data["edges"][0]["predicate"] == "part_of"
    res = client.get("/api/v1/graph", params={"entity_id": hw["id"], "depth": 1})
    assert act["id"] in {n["entity_id"] for n in res.json()["nodes"]}


# =============================================================================
# UI (bestaand server-rendered patroon, met geen-executie-disclaimer)
# =============================================================================

def test_actuator_ui_pages(client):
    act = make_actuator(client)
    index = client.get("/actuators")
    assert index.status_code == 200
    assert "Ventilator Werkplaats" in index.text
    assert "voert geen hardware-acties uit" in index.text
    detail = client.get(f"/actuators/{act['id']}")
    assert detail.status_code == 200
    assert "fan" in detail.text
    assert "voert geen hardware-acties uit" in detail.text
    assert f"/graph/{act['id']}" in detail.text
    assert client.get("/actuators/act_bestaatniet").status_code == 404
