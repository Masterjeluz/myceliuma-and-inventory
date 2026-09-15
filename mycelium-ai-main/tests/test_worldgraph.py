"""World-graph foundation tests (BIG #4, §21).

Uniform node/edge projection, type allow-lists, depth bounds,
mission/agent overlay, caps, and the HTTP endpoint.
"""

import os

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.inventory_read import (
    GraphEdge, GraphNode, Provenance,
)
from coordinator.app.worldgraph import build_world_graph


def run(coro):
    import asyncio
    return asyncio.run(coro)


class FakeReader:
    def __init__(self, nodes=None, edges=None, fail=None):
        self._nodes = nodes or []
        self._edges = edges or []
        self._fail = fail

    async def graph(self, entity_id, depth=1):
        if self._fail:
            raise self._fail
        from coordinator.app.inventory_read import GraphResponse
        return GraphResponse(entity_id=entity_id, depth=depth,
                             nodes=list(self._nodes),
                             edges=list(self._edges))


def node(entity_id, kind="object", title="Ding"):
    return GraphNode(entity_type=kind, entity_id=entity_id, title=title,
                     provenance=Provenance(human_verified=True))


def test_projection_and_type_filter():
    reader = FakeReader(
        nodes=[node("obj_1"), node("weird", kind="quantum")],
        edges=[GraphEdge(id="rel_1", from_id="obj_1", predicate="used_in",
                         to_id="proj_2", provenance=Provenance())])
    graph = run(build_world_graph(reader, "obj_1", 1))
    ids = {entry["id"] for entry in graph["nodes"]}
    assert "obj_1" in ids and "weird" not in ids
    assert graph["edges"][0]["predicate"] == "used_in"
    assert graph["nodes"][0]["source"] == "inventory"
    assert graph["nodes"][0]["metadata"]["human_verified"] is True


def test_depth_bounded_and_unavailable_propagates():
    with pytest.raises(ValueError):
        run(build_world_graph(FakeReader(), "obj_1", 9))
    from coordinator.app.inventory_read import InventoryUnavailable
    with pytest.raises(InventoryUnavailable):
        run(build_world_graph(
            FakeReader(fail=InventoryUnavailable("down")), "obj_1", 1))


def test_mission_and_agent_overlay(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "g.db"))
    from coordinator.app.missions import new_mission, save_mission
    mission = new_mission("mission_g", "conv-1", "doel", [
        {"kind": "readout", "description": "x",
         "parameters": {"source": "project"}}],
        context_records=[{"entity_id": "obj_1"}])
    save_mission(mission)
    reader = FakeReader(nodes=[node("obj_1")])
    graph = run(build_world_graph(
        reader, "obj_1", 1, include_missions=True,
        agent_nodes=[{"node_id": "desktop_1",
                      "capabilities": ["agent:desktop"]},
                     {"node_id": "", "capabilities": []}]))
    by_id = {entry["id"]: entry for entry in graph["nodes"]}
    assert by_id["mission_g"]["type"] == "mission"
    assert by_id["mission_g"]["source"] == "mycelium"
    assert by_id["desktop_1"]["type"] == "agent"
    assert any(edge["predicate"] == "uses_context"
               for edge in graph["edges"])


def test_graph_endpoint(tmp_path, monkeypatch):
    os.environ["MYCELIUM_DATABASE_PATH"] = str(tmp_path / "g.db")
    os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = str(tmp_path / "g-chat.db")

    class EndpointReader(FakeReader):
        async def graph(self, entity_id, depth=1):
            from coordinator.app.inventory_read import (
                GraphResponse, InventoryRefusedError)
            if not entity_id.startswith("obj_"):
                raise InventoryRefusedError("bad prefix")
            return GraphResponse(
                entity_id=entity_id, depth=depth,
                nodes=[node("obj_1")], edges=[])

    monkeypatch.setattr(main_mod, "InventoryReader",
                        lambda *a, **k: EndpointReader())
    with TestClient(main_mod.app) as test_client:
        ok_response = test_client.get("/api/v1/graph",
                                      params={"entity_id": "obj_1"})
        assert ok_response.status_code == 200, ok_response.text
        assert ok_response.json()["nodes"][0]["id"] == "obj_1"
        assert test_client.get("/api/v1/graph", params={
            "entity_id": "obj_1", "depth": 9}).status_code == 422
        assert test_client.get("/api/v1/graph", params={
            "entity_id": "nope"}).status_code == 422
