"""INVENTory controlled-write tests (BIG #5).

Payload validation, approval binding, execution with before/after,
and failure semantics. HTTP is faked with httpx.MockTransport;
no real INVENTory is touched.
"""

import asyncio
import json

import httpx
import pytest

from coordinator.app.controlled_writes import (
    decide_write,
    request_write_approval,
)
from coordinator.app.inventory_read import InventoryReader, Provenance
from coordinator.app.inventory_writes import (
    InventoryWriteFailedError,
    InventoryWriteRefusedError,
    InventoryWriter,
    build_create_payload,
    build_relationship_payload,
    build_update_payload,
    capability_for,
    execute_inventory_write,
    propose_inventory_write,
)


def run(coro):
    return asyncio.run(coro)


def ai_provenance() -> Provenance:
    return Provenance(source_type="ai-generated", creator_id="mycelium",
                      human_verified=False)


# -- payload validation -------------------------------------------------

def test_create_object_valid():
    body = build_create_payload(
        "object", {"name": "M3 bout", "quantity": 40})
    assert body["name"] == "M3 bout"
    assert body["quantity"] == 40
    assert body["provenance"]["human_verified"] is False


def test_create_unknown_entity_refused():
    with pytest.raises(InventoryWriteRefusedError, match="not a controlled"):
        build_create_payload("sensor", {"name": "x"})


def test_create_unauthorized_fields_refused():
    with pytest.raises(InventoryWriteRefusedError,
                       match="unauthorized fields"):
        build_create_payload(
            "object", {"name": "x", "price": 10, "owner": "y"})


def test_create_bad_status_refused():
    with pytest.raises(InventoryWriteRefusedError, match="unknown"):
        build_create_payload(
            "project", {"name": "x", "status": "flying"})


def test_update_empty_and_unknown_fields_refused():
    with pytest.raises(InventoryWriteRefusedError,
                       match="non-empty object"):
        build_update_payload("object", {})
    with pytest.raises(InventoryWriteRefusedError,
                       match="unauthorized fields"):
        build_update_payload("object", {"name": "x", "sql": "DROP"})


def test_human_verified_smuggling_refused():
    with pytest.raises(InventoryWriteRefusedError,
                       match="human_verified"):
        build_create_payload(
            "object", {"name": "x",
                       "provenance": {"source_type": "ai-generated",
                                      "creator_id": "qwen",
                                      "human_verified": True}})


def test_relationship_validation():
    body = build_relationship_payload(
        {"from_id": "obj_abc", "predicate": "part_of",
         "to_id": "proj_def"})
    assert body["predicate"] == "part_of"
    with pytest.raises(InventoryWriteRefusedError, match="must differ"):
        build_relationship_payload(
            {"from_id": "obj_abc", "predicate": "uses",
             "to_id": "obj_abc"})
    with pytest.raises(InventoryWriteRefusedError, match="unknown"):
        build_relationship_payload(
            {"from_id": "obj_abc", "predicate": "loves",
             "to_id": "proj_def"})
    with pytest.raises(InventoryWriteRefusedError, match="unknown prefix"):
        build_relationship_payload(
            {"from_id": "xyz_abc", "predicate": "uses",
             "to_id": "proj_def"})


def test_propose_update_prefix_mismatch_refused():
    with pytest.raises(InventoryWriteRefusedError, match="does not match"):
        propose_inventory_write(
            "wrt-x", "update", "object", {"name": "y"},
            entity_id="proj_wrong", actor="mycelium-test",
            provenance=ai_provenance())


def test_capabilities_are_dotted_per_collection():
    create = propose_inventory_write(
        "wrt-c", "create", "object", {"name": "x"},
        actor="t", provenance=ai_provenance())
    assert capability_for(create) == "inventory.objects.write"
    update = propose_inventory_write(
        "wrt-u", "update", "project", {"status": "active"},
        entity_id="proj_abc", actor="t",
        provenance=ai_provenance())
    assert capability_for(update) == "inventory.projects.write"
    relate = propose_inventory_write(
        "wrt-r", "create_relationship", "",
        {"from_id": "obj_a", "predicate": "uses",
         "to_id": "hw_b"}, actor="t",
        provenance=ai_provenance())
    assert capability_for(relate) == "inventory.relationships.write"


def test_non_loopback_writer_refused():
    with pytest.raises(InventoryWriteRefusedError, match="loopback"):
        InventoryWriter(base_url="http://192.168.1.10:8080")


# -- execution ----------------------------------------------------------

def approved(proposal):
    request = request_write_approval(proposal)
    return decide_write(request, proposal, "YES", decided_by="jelles")


class FakeStore:
    """Minimal in-memory INVENTory behind a MockTransport."""

    def __init__(self):
        self.objects: dict = {}
        self.relationships: list = []
        self.counter = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/api/v1/objects":
            body = json.loads(request.content.decode())
            self.counter += 1
            entity_id = f"obj_test{self.counter:03d}"
            record = {"id": entity_id, "name": body["name"],
                      "description": body.get("description", ""),
                      "quantity": body.get("quantity", 1),
                      "provenance": body.get("provenance", {}),
                      "created_at": "2026-01-01T00:00:00+00:00",
                      "updated_at": "2026-01-01T00:00:00+00:00"}
            self.objects[entity_id] = record
            return httpx.Response(201, json=record)
        if request.method == "GET" and path.startswith("/api/v1/objects/"):
            entity_id = path.rsplit("/", 1)[-1]
            record = self.objects.get(entity_id)
            if record is None:
                return httpx.Response(404, json={"detail": "not found"})
            return httpx.Response(200, json=record)
        if request.method == "PATCH" and path.startswith("/api/v1/objects/"):
            entity_id = path.rsplit("/", 1)[-1]
            record = self.objects.get(entity_id)
            if record is None:
                return httpx.Response(404, json={"detail": "not found"})
            body = json.loads(request.content.decode())
            for key in ("name", "description", "quantity"):
                if key in body:
                    record[key] = body[key]
            return httpx.Response(200, json=record)
        if request.method == "POST" and path == "/api/v1/relationships":
            body = json.loads(request.content.decode())
            self.counter += 1
            record = {"id": f"rel_test{self.counter:03d}",
                      "from_id": body["from_id"],
                      "predicate": body["predicate"],
                      "to_id": body["to_id"],
                      "metadata": body.get("metadata", {}),
                      "provenance": body.get("provenance", {}),
                      "created_at": "2026-01-01T00:00:00+00:00"}
            self.relationships.append(record)
            return httpx.Response(201, json=record)
        return httpx.Response(404, json={"detail": "no route"})


def make_reader_writer(store: FakeStore):
    transport = httpx.MockTransport(store.handler)
    reader = InventoryReader(transport=transport)
    writer = InventoryWriter(transport=transport)
    return reader, writer


def test_execute_create_roundtrip():
    store = FakeStore()
    reader, writer = make_reader_writer(store)
    proposal = propose_inventory_write(
        "wrt-create1", "create", "object",
        {"name": "M3 bout", "quantity": 40},
        actor="mycelium-test", provenance=ai_provenance())
    result = run(execute_inventory_write(
        proposal, approved(proposal), reader=reader, writer=writer))
    assert result.outcome == "executed"
    assert result.before == {}
    assert result.after["entity_id"].startswith("obj_")
    assert result.after["title"] == "M3 bout"
    assert result.provenance.human_verified is False
    assert result.error == ""


def test_execute_update_captures_before_after():
    store = FakeStore()
    reader, writer = make_reader_writer(store)
    create = propose_inventory_write(
        "wrt-c1", "create", "object", {"name": "Bout", "quantity": 5},
        actor="t", provenance=ai_provenance())
    created = run(execute_inventory_write(
        create, approved(create), reader=reader, writer=writer))
    entity_id = created.after["entity_id"]
    update = propose_inventory_write(
        "wrt-u1", "update", "object", {"quantity": 42},
        entity_id=entity_id, actor="t",
        provenance=ai_provenance())
    result = run(execute_inventory_write(
        update, approved(update), reader=reader, writer=writer))
    assert result.outcome == "executed"
    assert result.before["details"]["quantity"] == 5
    assert result.after["details"]["quantity"] == 42
    assert result.after["entity_id"] == entity_id


def test_execute_update_missing_target_fails():
    store = FakeStore()
    reader, writer = make_reader_writer(store)
    update = propose_inventory_write(
        "wrt-u2", "update", "object", {"quantity": 1},
        entity_id="obj_nonexistent", actor="t",
        provenance=ai_provenance())
    result = run(execute_inventory_write(
        update, approved(update), reader=reader, writer=writer))
    assert result.outcome == "failed"
    assert "does not exist" in result.error


def test_execute_relationship():
    store = FakeStore()
    reader, writer = make_reader_writer(store)
    proposal = propose_inventory_write(
        "wrt-r1", "create_relationship", "",
        {"from_id": "obj_aaa", "predicate": "part_of",
         "to_id": "proj_bbb"}, actor="t",
        provenance=ai_provenance())
    result = run(execute_inventory_write(
        proposal, approved(proposal), reader=reader, writer=writer))
    assert result.outcome == "executed"
    assert result.after["from_id"] == "obj_aaa"
    assert result.after["predicate"] == "part_of"
    assert result.after["relationship_id"].startswith("rel_")


def test_execute_without_approval_raises():
    store = FakeStore()
    reader, writer = make_reader_writer(store)
    proposal = propose_inventory_write(
        "wrt-no", "create", "object", {"name": "x"},
        actor="t", provenance=ai_provenance())
    request = request_write_approval(proposal)
    rejected = decide_write(request, proposal, "NO")
    with pytest.raises(ValueError, match="Only an approved"):
        run(execute_inventory_write(
            proposal, rejected, reader=reader, writer=writer))


def test_execute_server_error_is_failed_not_success():
    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    transport = httpx.MockTransport(failing)
    reader = InventoryReader(transport=transport)
    writer = InventoryWriter(transport=transport)
    proposal = propose_inventory_write(
        "wrt-f1", "create", "object", {"name": "x"},
        actor="t", provenance=ai_provenance())
    result = run(execute_inventory_write(
        proposal, approved(proposal), reader=reader, writer=writer))
    assert result.outcome == "failed"
    assert "500" in result.error


def test_execute_redirect_is_failed():
    def redirecting(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/elsewhere"})

    transport = httpx.MockTransport(redirecting)
    reader = InventoryReader(transport=transport)
    writer = InventoryWriter(transport=transport)
    proposal = propose_inventory_write(
        "wrt-f2", "create", "object", {"name": "x"},
        actor="t", provenance=ai_provenance())
    result = run(execute_inventory_write(
        proposal, approved(proposal), reader=reader, writer=writer))
    assert result.outcome == "failed"
    assert "redirect" in result.error.lower()
