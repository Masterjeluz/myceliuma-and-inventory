import importlib
import os

from fastapi.testclient import TestClient


def get_client(tmp_path):
    os.environ["INVENTORY_DATABASE_PATH"] = str(tmp_path / "inventory_test.db")
    import app.database as db_mod
    import app.main as main_mod
    importlib.reload(db_mod)
    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def test_create_object_has_stable_id_and_provenance(tmp_path):
    with get_client(tmp_path) as client:
        payload = {
            "name": "Arduino Uno R3",
            "description": "ATmega328P microcontroller development board",
            "quantity": 3,
            "provenance": {
                "source_type": "user-created",
                "creator_id": "jelles",
                "notes": "Found in workshop bin 4"
            }
        }
        res = client.post("/api/v1/objects", json=payload)
        assert res.status_code == 201
        data = res.json()

        # Check stable ID
        assert data["id"].startswith("obj_")
        assert len(data["id"]) >= 12
        assert data["name"] == "Arduino Uno R3"
        assert data["quantity"] == 3
        assert data["provenance"]["source_type"] == "user-created"
        assert data["provenance"]["creator_id"] == "jelles"
        assert data["provenance"]["human_verified"] is True
        assert data["created_at"] is not None
        assert data["updated_at"] is not None


def test_get_object_by_id_and_list_objects(tmp_path):
    with get_client(tmp_path) as client:
        # Create object
        created = client.post("/api/v1/objects", json={"name": "Soldering Iron", "quantity": 1}).json()
        obj_id = created["id"]

        # Fetch single object
        res = client.get(f"/api/v1/objects/{obj_id}")
        assert res.status_code == 200
        assert res.json()["name"] == "Soldering Iron"

        # List all objects
        all_objs = client.get("/api/v1/objects").json()
        assert len(all_objs) == 1
        assert all_objs[0]["id"] == obj_id


def test_update_object(tmp_path):
    with get_client(tmp_path) as client:
        created = client.post("/api/v1/objects", json={"name": "Resistor 10k", "quantity": 100}).json()
        obj_id = created["id"]

        # Update quantity and description
        update_res = client.patch(
            f"/api/v1/objects/{obj_id}",
            json={"quantity": 150, "description": "1/4 Watt, 5% tolerance"}
        )
        assert update_res.status_code == 200
        updated_data = update_res.json()
        assert updated_data["quantity"] == 150
        assert updated_data["description"] == "1/4 Watt, 5% tolerance"
        assert updated_data["name"] == "Resistor 10k"


def test_delete_object(tmp_path):
    with get_client(tmp_path) as client:
        created = client.post("/api/v1/objects", json={"name": "Broken Cable", "quantity": 1}).json()
        obj_id = created["id"]

        # Delete
        delete_res = client.delete(f"/api/v1/objects/{obj_id}")
        assert delete_res.status_code == 204

        # Verify it's gone
        get_res = client.get(f"/api/v1/objects/{obj_id}")
        assert get_res.status_code == 404


def test_ai_observation_is_not_human_verified_by_default(tmp_path):
    with get_client(tmp_path) as client:
        payload = {
            "name": "Unknown Motor",
            "quantity": 1,
            "provenance": {
                "source_type": "ai-generated",
                "creator_id": "vision_agent",
                "confidence_score": 0.88
            }
        }
        res = client.post("/api/v1/objects", json=payload)
        assert res.status_code == 201
        data = res.json()

        # Crucial principle: AI-generated data cannot silently be verified
        assert data["provenance"]["source_type"] == "ai-generated"
        assert data["provenance"]["human_verified"] is False
        assert data["provenance"]["confidence_score"] == 0.88


def test_invalid_input_is_rejected(tmp_path):
    with get_client(tmp_path) as client:
        # Empty name rejected
        res1 = client.post("/api/v1/objects", json={"name": "", "quantity": 1})
        assert res1.status_code == 422

        # Negative quantity rejected
        res2 = client.post("/api/v1/objects", json={"name": "Valid Name", "quantity": -5})
        assert res2.status_code == 422

        # Invalid source_type rejected
        res3 = client.post(
            "/api/v1/objects",
            json={"name": "Valid Name", "provenance": {"source_type": "magic-telepathy"}}
        )
        assert res3.status_code == 422


def test_web_interface_endpoints(tmp_path):
    with get_client(tmp_path) as client:
        # Create an object via web form
        form_res = client.post(
            "/web/objects",
            data={"name": "Drill Press", "description": "Benchtop 350W", "quantity": "1", "source_type": "user-created"},
            follow_redirects=False
        )
        assert form_res.status_code == 303

        # Web index view
        index_res = client.get("/")
        assert index_res.status_code == 200
        assert "Drill Press" in index_res.text
        assert "INVENTory" in index_res.text

        # Web detail view
        objects = client.get("/api/v1/objects").json()
        obj_id = objects[0]["id"]
        detail_res = client.get(f"/objects/{obj_id}")
        assert detail_res.status_code == 200
        assert "Drill Press" in detail_res.text
        # New dark UI uses h1 with object name and shows the ID
        assert obj_id in detail_res.text
