"""Tests voor INVENTory Milestone 1B — Projects, Ideas, Relationships, Events."""
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path):
    os.environ["INVENTORY_DATABASE_PATH"] = str(tmp_path / "test_1b.db")
    # Re-import to pick up fresh env var
    import importlib
    import app.database as db_mod
    import app.main as main_mod
    importlib.reload(db_mod)
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


# =============================================================================
# PROJECT CRUD
# =============================================================================

def test_create_project(client):
    res = client.post("/api/v1/projects", json={"name": "3D Printer Build", "status": "active"})
    assert res.status_code == 201
    data = res.json()
    assert data["id"].startswith("proj_")
    assert data["name"] == "3D Printer Build"
    assert data["status"] == "active"
    assert data["provenance"]["human_verified"] is True


def test_list_projects(client):
    client.post("/api/v1/projects", json={"name": "Alpha"})
    client.post("/api/v1/projects", json={"name": "Beta"})
    res = client.get("/api/v1/projects")
    assert res.status_code == 200
    assert len(res.json()) == 2


def test_get_project_by_id(client):
    proj = client.post("/api/v1/projects", json={"name": "Filament Dryer"}).json()
    res = client.get(f"/api/v1/projects/{proj['id']}")
    assert res.status_code == 200
    assert res.json()["name"] == "Filament Dryer"


def test_update_project(client):
    proj = client.post("/api/v1/projects", json={"name": "Old Name", "status": "idea"}).json()
    res = client.patch(f"/api/v1/projects/{proj['id']}", json={"name": "New Name", "status": "active"})
    assert res.status_code == 200
    assert res.json()["name"] == "New Name"
    assert res.json()["status"] == "active"


def test_delete_project(client):
    proj = client.post("/api/v1/projects", json={"name": "To Delete"}).json()
    res = client.delete(f"/api/v1/projects/{proj['id']}")
    assert res.status_code == 204
    assert client.get(f"/api/v1/projects/{proj['id']}").status_code == 404


def test_project_invalid_status_rejected(client):
    res = client.post("/api/v1/projects", json={"name": "Bad", "status": "flying"})
    assert res.status_code == 422


# =============================================================================
# IDEA CRUD
# =============================================================================

def test_create_idea(client):
    res = client.post("/api/v1/ideas", json={"name": "Auto-label parts", "status": "raw"})
    assert res.status_code == 201
    data = res.json()
    assert data["id"].startswith("idea_")
    assert data["status"] == "raw"


def test_list_ideas(client):
    client.post("/api/v1/ideas", json={"name": "X"})
    client.post("/api/v1/ideas", json={"name": "Y"})
    assert len(client.get("/api/v1/ideas").json()) == 2


def test_update_idea(client):
    idea = client.post("/api/v1/ideas", json={"name": "Raw Idea", "status": "raw"}).json()
    res = client.patch(f"/api/v1/ideas/{idea['id']}", json={"status": "considered"})
    assert res.status_code == 200
    assert res.json()["status"] == "considered"


def test_delete_idea(client):
    idea = client.post("/api/v1/ideas", json={"name": "Delete me"}).json()
    assert client.delete(f"/api/v1/ideas/{idea['id']}").status_code == 204
    assert client.get(f"/api/v1/ideas/{idea['id']}").status_code == 404


# =============================================================================
# RELATIONSHIPS
# =============================================================================

def test_create_relationship_between_object_and_project(client):
    obj = client.post("/api/v1/objects", json={"name": "Motor"}).json()
    proj = client.post("/api/v1/projects", json={"name": "Printer"}).json()
    res = client.post("/api/v1/relationships", json={
        "from_id": obj["id"], "predicate": "used_in", "to_id": proj["id"]
    })
    assert res.status_code == 201
    data = res.json()
    assert data["id"].startswith("rel_")
    assert data["predicate"] == "used_in"
    assert data["from_id"] == obj["id"]
    assert data["to_id"] == proj["id"]


def test_create_relationship_idea_to_project(client):
    idea = client.post("/api/v1/ideas", json={"name": "Automate it"}).json()
    proj = client.post("/api/v1/projects", json={"name": "Automation Project"}).json()
    res = client.post("/api/v1/relationships", json={
        "from_id": idea["id"], "predicate": "became", "to_id": proj["id"]
    })
    assert res.status_code == 201
    assert res.json()["predicate"] == "became"


def test_create_relationship_object_to_object(client):
    obj1 = client.post("/api/v1/objects", json={"name": "Frame"}).json()
    obj2 = client.post("/api/v1/objects", json={"name": "Rail"}).json()
    res = client.post("/api/v1/relationships", json={
        "from_id": obj1["id"], "predicate": "contains", "to_id": obj2["id"]
    })
    assert res.status_code == 201


def test_self_referential_relationship_rejected(client):
    obj = client.post("/api/v1/objects", json={"name": "Motor"}).json()
    res = client.post("/api/v1/relationships", json={
        "from_id": obj["id"], "predicate": "related_to", "to_id": obj["id"]
    })
    assert res.status_code == 422


def test_list_relationships_for_entity(client):
    obj = client.post("/api/v1/objects", json={"name": "Bearing"}).json()
    proj = client.post("/api/v1/projects", json={"name": "CNC Build"}).json()
    client.post("/api/v1/relationships", json={"from_id": obj["id"], "predicate": "used_in", "to_id": proj["id"]})
    res = client.get(f"/api/v1/relationships?entity_id={obj['id']}")
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_delete_relationship(client):
    obj = client.post("/api/v1/objects", json={"name": "Capacitor"}).json()
    proj = client.post("/api/v1/projects", json={"name": "PCB"}).json()
    rel = client.post("/api/v1/relationships", json={
        "from_id": obj["id"], "predicate": "used_in", "to_id": proj["id"]
    }).json()
    assert client.delete(f"/api/v1/relationships/{rel['id']}").status_code == 204
    assert len(client.get("/api/v1/relationships").json()) == 0


def test_invalid_predicate_rejected(client):
    obj = client.post("/api/v1/objects", json={"name": "Motor"}).json()
    res = client.post("/api/v1/relationships", json={
        "from_id": obj["id"], "predicate": "invented_by", "to_id": "proj_fake"
    })
    assert res.status_code == 422


# =============================================================================
# EVENTS — APPEND ONLY HISTORY
# =============================================================================

def test_object_create_generates_event(client):
    obj = client.post("/api/v1/objects", json={"name": "Sensor"}).json()
    events = client.get(f"/api/v1/events?entity_id={obj['id']}").json()
    assert any(e["event_type"] == "object_created" for e in events)


def test_object_update_generates_event(client):
    obj = client.post("/api/v1/objects", json={"name": "Motor"}).json()
    client.patch(f"/api/v1/objects/{obj['id']}", json={"quantity": 5})
    events = client.get(f"/api/v1/events?entity_id={obj['id']}").json()
    assert any(e["event_type"] == "object_updated" for e in events)


def test_object_delete_registers_event_before_deletion(client):
    obj = client.post("/api/v1/objects", json={"name": "Doomed Object"}).json()
    obj_id = obj["id"]
    client.delete(f"/api/v1/objects/{obj_id}")
    # Object should be gone
    assert client.get(f"/api/v1/objects/{obj_id}").status_code == 404
    # But event must still exist
    events = client.get(f"/api/v1/events?entity_id={obj_id}").json()
    assert any(e["event_type"] == "object_deleted" for e in events)


def test_project_create_update_delete_events(client):
    proj = client.post("/api/v1/projects", json={"name": "P1"}).json()
    pid = proj["id"]
    client.patch(f"/api/v1/projects/{pid}", json={"status": "active"})
    client.delete(f"/api/v1/projects/{pid}")
    events = client.get(f"/api/v1/events?entity_id={pid}").json()
    types = [e["event_type"] for e in events]
    assert "project_created" in types
    assert "project_updated" in types
    assert "project_deleted" in types


def test_idea_create_update_delete_events(client):
    idea = client.post("/api/v1/ideas", json={"name": "I1"}).json()
    iid = idea["id"]
    client.patch(f"/api/v1/ideas/{iid}", json={"status": "considered"})
    client.delete(f"/api/v1/ideas/{iid}")
    events = client.get(f"/api/v1/events?entity_id={iid}").json()
    types = [e["event_type"] for e in events]
    assert "idea_created" in types
    assert "idea_updated" in types
    assert "idea_deleted" in types


def test_relationship_events(client):
    obj = client.post("/api/v1/objects", json={"name": "Wheel"}).json()
    proj = client.post("/api/v1/projects", json={"name": "Robot"}).json()
    rel = client.post("/api/v1/relationships", json={
        "from_id": obj["id"], "predicate": "used_in", "to_id": proj["id"]
    }).json()
    client.delete(f"/api/v1/relationships/{rel['id']}")
    events = client.get(f"/api/v1/events?entity_id={rel['id']}").json()
    types = [e["event_type"] for e in events]
    assert "relationship_created" in types
    assert "relationship_deleted" in types


def test_events_are_append_only(client):
    """Events can never be deleted via API — they accumulate."""
    obj = client.post("/api/v1/objects", json={"name": "Permanent"}).json()
    client.patch(f"/api/v1/objects/{obj['id']}", json={"quantity": 2})
    client.patch(f"/api/v1/objects/{obj['id']}", json={"quantity": 3})
    events = client.get(f"/api/v1/events?entity_id={obj['id']}").json()
    # 1 created + 2 updated = 3 events minimum
    assert len(events) >= 3


# =============================================================================
# PROVENANCE RULES
# =============================================================================

def test_ai_project_is_not_human_verified(client):
    res = client.post("/api/v1/projects", json={
        "name": "AI Spotted Project",
        "provenance": {"source_type": "ai-generated", "creator_id": "vision_agent"}
    })
    assert res.status_code == 201
    assert res.json()["provenance"]["human_verified"] is False


def test_ai_idea_is_not_human_verified(client):
    res = client.post("/api/v1/ideas", json={
        "name": "AI Raw Idea",
        "provenance": {"source_type": "ai-generated", "creator_id": "llm_agent"}
    })
    assert res.status_code == 201
    assert res.json()["provenance"]["human_verified"] is False
