"""Tests for the M5.2 read-only world proxy (coordinator world routes).

The InventoryReader is replaced with fakes; no real INVENTory server, no real
network. Coordinator database tables must stay untouched by world routes.
"""
import os

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.inventory_read import (
    EntityRecord,
    GraphResponse,
    InventoryRefusedError,
    InventoryUnavailable,
    SearchResponse,
)

PROV = {"source_type": "sensor-observed", "creator_id": "bridge-test",
        "human_verified": False}


class FakeReader:
    """Stand-in for InventoryReader; records delegated calls."""

    def __init__(self, *args, **kwargs):
        self.calls = []
        self.behavior = "ok"

    async def search(self, q, type=None):
        self.calls.append(("search", q, type))
        if self.behavior == "unavailable":
            raise InventoryUnavailable("down")
        if self.behavior == "refused":
            raise InventoryRefusedError("nope")
        return SearchResponse(query=q, total=1, results=[{
            "entity_type": "object", "entity_id": "obj_1", "title": "Moer",
            "snippet": "rvs", "provenance": PROV}])

    async def get(self, entity_type, entity_id):
        self.calls.append(("get", entity_type, entity_id))
        if self.behavior == "unavailable":
            raise InventoryUnavailable("down")
        if self.behavior == "refused":
            raise InventoryRefusedError("nope")
        if self.behavior == "missing":
            return None
        return EntityRecord(entity_type=entity_type, entity_id=entity_id,
                            title="Moer", provenance=PROV,
                            details={"quantity": 2})

    async def graph(self, entity_id, depth=1):
        self.calls.append(("graph", entity_id, depth))
        if self.behavior == "unavailable":
            raise InventoryUnavailable("down")
        if self.behavior == "refused":
            raise InventoryRefusedError("nope")
        return GraphResponse(entity_id=entity_id, depth=depth, nodes=[{
            "entity_type": "object", "entity_id": entity_id,
            "title": "Moer", "provenance": PROV}], edges=[{
            "id": "rel_1", "from_id": entity_id, "predicate": "used_in",
            "to_id": "proj_1", "metadata": {}, "provenance": PROV}])


@pytest.fixture()
def client(tmp_path, monkeypatch):
    os.environ["MYCELIUM_DATABASE_PATH"] = str(tmp_path / "proxy.db")
    fake = FakeReader()
    monkeypatch.setattr(main_mod, "InventoryReader", lambda *a, **k: fake)
    with TestClient(main_mod.app) as test_client:
        test_client.fake_reader = fake
        yield test_client


def test_world_search_delegates(client):
    res = client.get("/api/v1/world/search", params={"q": "moer", "type": "objects"})
    assert res.status_code == 200
    assert client.fake_reader.calls == [("search", "moer", "objects")]
    data = res.json()
    assert data["total"] == 1
    assert data["results"][0]["entity_id"] == "obj_1"
    assert data["results"][0]["provenance"]["source_type"] == "sensor-observed"
    assert data["results"][0]["provenance"]["human_verified"] is False


def test_world_entity_delegates(client):
    res = client.get("/api/v1/world/entity/project/proj_9")
    assert res.status_code == 200
    assert client.fake_reader.calls == [("get", "project", "proj_9")]
    data = res.json()
    assert data["entity_id"] == "proj_9"
    assert data["details"] == {"quantity": 2}


def test_world_entity_missing_is_404(client):
    client.fake_reader.behavior = "missing"
    res = client.get("/api/v1/world/entity/object/obj_nope")
    assert res.status_code == 404


def test_world_graph_delegates(client):
    res = client.get("/api/v1/world/graph",
                     params={"entity_id": "obj_1", "depth": 2})
    assert res.status_code == 200
    assert client.fake_reader.calls == [("graph", "obj_1", 2)]
    data = res.json()
    assert len(data["nodes"]) == 1
    assert data["edges"][0]["predicate"] == "used_in"
    assert data["edges"][0]["provenance"]["source_type"] == "sensor-observed"


def test_world_unavailable_is_502(client):
    client.fake_reader.behavior = "unavailable"
    assert client.get("/api/v1/world/search", params={"q": "x"}).status_code == 502
    assert client.get("/api/v1/world/entity/object/obj_1").status_code == 502
    assert client.get("/api/v1/world/graph",
                      params={"entity_id": "obj_1"}).status_code == 502


def test_world_refused_is_422(client):
    client.fake_reader.behavior = "refused"
    assert client.get("/api/v1/world/search", params={"q": "x"}).status_code == 422
    assert client.get("/api/v1/world/entity/object/obj_1").status_code == 422
    assert client.get("/api/v1/world/graph",
                      params={"entity_id": "obj_1"}).status_code == 422


def test_world_validation_without_fake(tmp_path, monkeypatch):
    """Real reader validation still guards the proxy (non-loopback env)."""
    os.environ["MYCELIUM_DATABASE_PATH"] = str(tmp_path / "proxy2.db")
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://example.com/")
    with TestClient(main_mod.app) as real_client:
        assert real_client.get("/api/v1/world/search",
                               params={"q": "x"}).status_code == 422
        assert real_client.get("/api/v1/world/graph",
                               params={"entity_id": "obj_1",
                                       "depth": 5}).status_code == 422
    monkeypatch.delenv("INVENTORY_BASE_URL", raising=False)


def test_world_routes_do_no_writes(client):
    client.get("/api/v1/world/search", params={"q": "moer"})
    client.get("/api/v1/world/entity/object/obj_1")
    client.get("/api/v1/world/graph", params={"entity_id": "obj_1"})
    world_routes = [r for r in main_mod.app.routes
                    if getattr(r, "path", "").startswith("/api/v1/world")]
    assert len(world_routes) == 3
    assert {m for r in world_routes for m in r.methods} == {"GET"}
    from coordinator.app.database import connection
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
