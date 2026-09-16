"""Verification tests (BIG #5).

Approval is permission, verification is truth. Only an explicit
pass from an independent readback counts; forged, missing,
failed or inconclusive verifications never become success.
"""

import asyncio

import httpx
import pytest

from coordinator.app.controlled_writes import (
    WriteResult,
    decide_write,
    now,
    request_write_approval,
    write_fingerprint,
)
from coordinator.app.inventory_read import (
    EntityRecord,
    GraphEdge,
    GraphResponse,
    InventoryReader,
    Provenance,
)
from coordinator.app.inventory_writes import (
    InventoryWriter,
    execute_inventory_write,
    propose_inventory_write,
)
from coordinator.app.verification import (
    VerificationResult,
    is_verified,
    new_verification_request,
    verify_inventory_write,
)


def run(coro):
    return asyncio.run(coro)


def ai_provenance() -> Provenance:
    return Provenance(source_type="ai-generated", creator_id="mycelium",
                      human_verified=False)


class FakeReader(InventoryReader):
    """Independent readback stub: entities + one graph."""

    def __init__(self, entities=None, edges=None, broken=False):
        self._entities = entities or {}
        self._edges = edges or []
        self._broken = broken

    async def get(self, entity_type, entity_id):
        if self._broken:
            raise RuntimeError("world unreadable")
        return self._entities.get(entity_id)

    async def graph(self, entity_id, depth=1):
        if self._broken:
            raise RuntimeError("world unreadable")
        return GraphResponse(
            entity_id=entity_id, depth=depth, nodes=[],
            edges=[GraphEdge(id=edge["id"], from_id=edge["from_id"],
                             predicate=edge["predicate"],
                             to_id=edge["to_id"])
                   for edge in self._edges])


def approved_result(proposal, outcome="executed", after=None,
                    before=None):
    request = request_write_approval(proposal)
    approval = decide_write(request, proposal, "YES")
    return WriteResult(
        proposal_id=proposal.proposal_id,
        fingerprint=write_fingerprint(proposal),
        outcome=outcome, before=before or {}, after=after or {},
        actor=proposal.actor, executed_at=now(),
        provenance=ai_provenance())


def make_entity(entity_id="obj_aaa", title="Bout"):
    return EntityRecord(
        entity_type="object", entity_id=entity_id, title=title,
        provenance=Provenance(source_type="ai-generated",
                              creator_id="mycelium",
                              human_verified=False),
        details={"name": title, "quantity": 42,
                 "description": "M3 bout"})


def test_successful_verification_passes():
    proposal = propose_inventory_write(
        "wrt-v1", "create", "object",
        {"name": "Bout", "quantity": 42}, actor="t",
        provenance=ai_provenance())
    result = approved_result(
        proposal, after={"entity_id": "obj_aaa"})
    request = new_verification_request(
        proposal.proposal_id, result.fingerprint,
        "inventory.readback",
        {"kind": "entity", "entity_type": "object",
         "entity_id": "obj_aaa", "name": "Bout", "quantity": 42})
    reader = FakeReader(entities={"obj_aaa": make_entity()})
    verification = run(verify_inventory_write(
        request, result, reader=reader))
    assert verification.outcome == "passed"
    assert is_verified(verification) is True
    # Observed and inferred stay separate; no model opinion decided.
    assert verification.observed["exists"] is True
    assert verification.inferred == ""
    assert verification.provenance.human_verified is False


def test_failed_verification_is_not_verified():
    proposal = propose_inventory_write(
        "wrt-v2", "create", "object",
        {"name": "Bout", "quantity": 42}, actor="t",
        provenance=ai_provenance())
    result = approved_result(
        proposal, after={"entity_id": "obj_aaa"})
    request = new_verification_request(
        proposal.proposal_id, result.fingerprint,
        "inventory.readback",
        {"kind": "entity", "entity_type": "object",
         "entity_id": "obj_aaa", "quantity": 99})
    reader = FakeReader(entities={"obj_aaa": make_entity()})
    verification = run(verify_inventory_write(
        request, result, reader=reader))
    assert verification.outcome == "failed"
    assert is_verified(verification) is False


def test_missing_entity_fails_not_passes():
    proposal = propose_inventory_write(
        "wrt-v3", "create", "object", {"name": "Spook"},
        actor="t", provenance=ai_provenance())
    result = approved_result(
        proposal, after={"entity_id": "obj_ghost"})
    request = new_verification_request(
        proposal.proposal_id, result.fingerprint,
        "inventory.readback",
        {"kind": "entity", "entity_type": "object",
         "entity_id": "obj_ghost"})
    verification = run(verify_inventory_write(
        request, result, reader=FakeReader()))
    assert verification.outcome == "failed"
    assert is_verified(verification) is False


def test_unreadable_world_is_inconclusive_never_success():
    proposal = propose_inventory_write(
        "wrt-v4", "create", "object", {"name": "x"},
        actor="t", provenance=ai_provenance())
    result = approved_result(
        proposal, after={"entity_id": "obj_aaa"})
    request = new_verification_request(
        proposal.proposal_id, result.fingerprint,
        "inventory.readback",
        {"kind": "entity", "entity_type": "object",
         "entity_id": "obj_aaa"})
    verification = run(verify_inventory_write(
        request, result, reader=FakeReader(broken=True)))
    assert verification.outcome == "inconclusive"
    assert is_verified(verification) is False


def test_failed_execution_verifies_as_failed():
    proposal = propose_inventory_write(
        "wrt-v5", "create", "object", {"name": "x"},
        actor="t", provenance=ai_provenance())
    result = approved_result(proposal, outcome="failed")
    request = new_verification_request(
        proposal.proposal_id, result.fingerprint,
        "inventory.readback",
        {"kind": "entity", "entity_type": "object",
         "entity_id": "obj_aaa"})
    verification = run(verify_inventory_write(
        request, result, reader=FakeReader()))
    assert verification.outcome == "failed"
    assert is_verified(verification) is False


def test_forged_result_binding_rejected():
    proposal = propose_inventory_write(
        "wrt-v6", "create", "object", {"name": "x"},
        actor="t", provenance=ai_provenance())
    result = approved_result(
        proposal, after={"entity_id": "obj_aaa"})
    request = new_verification_request(
        proposal.proposal_id, "0" * 64, "inventory.readback",
        {"kind": "entity", "entity_type": "object",
         "entity_id": "obj_aaa"})
    with pytest.raises(ValueError, match="different result"):
        run(verify_inventory_write(
            request, result, reader=FakeReader()))
    other = new_verification_request(
        "wrt-other", result.fingerprint, "inventory.readback",
        {"kind": "entity", "entity_type": "object",
         "entity_id": "obj_aaa"})
    with pytest.raises(ValueError, match="does not belong"):
        run(verify_inventory_write(
            other, result, reader=FakeReader()))


def test_result_payload_alone_never_verifies():
    """Even a glowing result dict is not verification."""
    assert is_verified(None) is False
    inconclusive = VerificationResult(
        verification_id="ver_x", proposal_id="wrt_x",
        result_fingerprint="0" * 64, outcome="inconclusive",
        method="inventory.readback")
    assert is_verified(inconclusive) is False


def test_relationship_verification_reads_graph():
    proposal = propose_inventory_write(
        "wrt-v7", "create_relationship", "",
        {"from_id": "obj_aaa", "predicate": "part_of",
         "to_id": "proj_bbb"}, actor="t",
        provenance=ai_provenance())
    result = approved_result(
        proposal, after={"relationship_id": "rel_1",
                         "from_id": "obj_aaa",
                         "predicate": "part_of",
                         "to_id": "proj_bbb"})
    request = new_verification_request(
        proposal.proposal_id, result.fingerprint,
        "inventory.graph_readback",
        {"kind": "relationship", "from_id": "obj_aaa",
         "predicate": "part_of", "to_id": "proj_bbb"})
    reader = FakeReader(edges=[{
        "id": "rel_1", "from_id": "obj_aaa",
        "predicate": "part_of", "to_id": "proj_bbb"}])
    verification = run(verify_inventory_write(
        request, result, reader=reader))
    assert verification.outcome == "passed"
    assert is_verified(verification) is True
    # A forged after-payload without the graph edge fails.
    lonely = FakeReader(edges=[])
    failed = run(verify_inventory_write(
        request, result, reader=lonely))
    assert failed.outcome == "failed"


def test_end_to_end_write_then_verify():
    """Create through the writer, verify through the reader."""
    import json as _json

    store: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = _json.loads(request.content.decode())
            record = {"id": "obj_live1", "name": body["name"],
                      "description": body.get("description", ""),
                      "quantity": body.get("quantity", 1),
                      "provenance": {},
                      "created_at": "2026-01-01T00:00:00+00:00",
                      "updated_at": "2026-01-01T00:00:00+00:00"}
            store["obj_live1"] = record
            return httpx.Response(201, json=record)
        record = store.get("obj_live1")
        if record is None:
            return httpx.Response(404, json={})
        return httpx.Response(200, json=record)

    transport = httpx.MockTransport(handler)
    reader = InventoryReader(transport=transport)
    writer = InventoryWriter(transport=transport)
    proposal = propose_inventory_write(
        "wrt-live", "create", "object",
        {"name": "Levend onderdeel", "quantity": 3},
        actor="t", provenance=ai_provenance())
    approval_request = request_write_approval(proposal)
    approval = decide_write(approval_request, proposal, "YES")
    result = run(execute_inventory_write(
        proposal, approval, reader=reader, writer=writer))
    assert result.outcome == "executed"
    verify_request = new_verification_request(
        proposal.proposal_id, result.fingerprint,
        "inventory.readback",
        {"kind": "entity", "entity_type": "object",
         "entity_id": "obj_live1", "name": "Levend onderdeel",
         "quantity": 3})
    verification = run(verify_inventory_write(
        verify_request, result, reader=reader))
    assert verification.outcome == "passed"
    assert is_verified(verification) is True
