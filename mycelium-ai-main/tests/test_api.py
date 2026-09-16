from fastapi.testclient import TestClient


def test_node_can_claim_matching_task(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "test.db"))
    from coordinator.app.main import app
    with TestClient(app) as client:
        registration = {"node_id": "test-worker", "hostname": "workshop", "tier": "worker",
                        "capabilities": ["python"], "cpu_cores": 2, "memory_mb": 1024, "energy_source": "solar",
                        "node_token": "api-token-12345678"}
        assert client.post("/api/v1/nodes/register", json=registration).status_code == 201
        created = client.post("/api/v1/tasks", json={"kind": "system_inventory", "required_capabilities": ["python"]})
        assert created.status_code == 201
        claimed = client.post("/api/v1/tasks/claim/test-worker", params={"node_token": "api-token-12345678"})
        assert claimed.status_code == 200
        assert claimed.json()["kind"] == "system_inventory"
        assert client.post(f"/api/v1/tasks/{claimed.json()['id']}/complete", json={"success": True, "result": {}}).status_code == 204
        assert client.get("/api/v1/tasks").json()[0]["status"] == "completed"
