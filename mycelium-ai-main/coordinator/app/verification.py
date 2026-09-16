"""First-class verification for controlled writes (BIG #5).

APPROVAL means: "the human permits this proposed action."
VERIFICATION means: "it was checked that the expected result
actually came about." They are never the same object or status:

- an approval never sets human_verified=True;
- a successful mutation never means verified=True;
- verification is always a separate step with its own method,
  source, timestamp and provenance.

A verification describes OBSERVED (what an independent read
returned) separately from INFERRED (optional model analysis,
clearly labeled, never decisive). "The model thinks it probably
worked" is never a pass.

Outcomes:

- passed — independent readback matches the expectation;
- failed — execution succeeded but the world does not match
  (final state is NOT verified);
- inconclusive — the world could not be read (final state is
  NOT verified, no FACT promotion).

A forged or missing verification never becomes success: only
``outcome == "passed"`` counts as verified.
"""

import secrets
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .inventory_read import InventoryReader, Provenance

VerificationOutcome = Literal["passed", "failed", "inconclusive"]

VALID_METHODS = frozenset({
    "inventory.readback",
    "inventory.graph_readback",
    "git.readback",
    "camera.readback",
    "print.telemetry_readback",
    "print.camera_readback",
})


class VerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_id: str = Field(min_length=3, max_length=80)
    proposal_id: str = Field(min_length=3, max_length=80)
    result_fingerprint: str = Field(min_length=64, max_length=64,
                                    pattern=r"^[0-9a-f]{64}$")
    method: str = Field(min_length=1, max_length=40)
    expected: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    """The outcome of one independent check. Only passed verifies."""

    model_config = ConfigDict(extra="forbid")

    verification_id: str = Field(min_length=3, max_length=80)
    proposal_id: str = Field(min_length=3, max_length=80)
    result_fingerprint: str = Field(min_length=64, max_length=64,
                                    pattern=r"^[0-9a-f]{64}$")
    outcome: VerificationOutcome = "inconclusive"
    method: str = Field(min_length=1, max_length=40)
    expected: dict[str, Any] = Field(default_factory=dict)
    observed: dict[str, Any] = Field(default_factory=dict)
    inferred: str = Field(default="", max_length=2000)
    source: str = Field(default="", max_length=200)
    verified_at: str = ""
    observer: str = Field(default="mycelium-verifier",
                          min_length=1, max_length=80)
    note: str = Field(default="", max_length=1000)
    provenance: Provenance = Field(default_factory=Provenance)


def generate_verification_id() -> str:
    return f"ver_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def new_verification_request(proposal_id: str,
                             result_fingerprint: str,
                             method: str,
                             expected: dict) -> VerificationRequest:
    if method not in VALID_METHODS:
        raise ValueError(
            f"Unknown verification method '{method}'; expected one of "
            f"{sorted(VALID_METHODS)}")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("Verification needs a non-empty expectation")
    return VerificationRequest(
        verification_id=generate_verification_id(),
        proposal_id=proposal_id,
        result_fingerprint=result_fingerprint,
        method=method,
        expected=dict(expected),
    )


def is_verified(result: VerificationResult) -> bool:
    """Only an explicit pass counts. Failed, inconclusive and forged
    results are never verified."""
    return (isinstance(result, VerificationResult)
            and result.outcome == "passed")


def _base_result(request: VerificationRequest,
                 observer: str) -> dict:
    return {
        "verification_id": request.verification_id,
        "proposal_id": request.proposal_id,
        "result_fingerprint": request.result_fingerprint,
        "method": request.method,
        "expected": dict(request.expected),
        "observer": observer,
        "provenance": Provenance(
            source_type="sensor-observed", creator_id=observer,
            human_verified=False,
            notes="independent verification read; "
                  "human verification needs a human"),
    }


async def verify_inventory_write(request: VerificationRequest,
                                 result, *,
                                 reader: InventoryReader,
                                 observer: str = "mycelium-verifier",
                                 now_str: str | None = None
                                 ) -> VerificationResult:
    """Verify one inventory write by independent readback.

    The result payload is NEVER trusted: the entity (or graph) is
    re-read through the read bridge and compared field by field.
    Unreadable worlds yield inconclusive — never a pass.
    """
    from datetime import datetime, timezone
    from .controlled_writes import WriteResult
    if not isinstance(result, WriteResult):
        raise ValueError("Verification needs a WriteResult")
    if result.proposal_id != request.proposal_id:
        raise ValueError("Verification does not belong to this result")
    if request.result_fingerprint != result.fingerprint:
        raise ValueError("Verification binds to a different result")
    if result.outcome != "executed":
        return VerificationResult(
            **_base_result(request, observer),
            outcome="failed",
            observed={"execution_outcome": result.outcome},
            source="write-result",
            verified_at=now_str or datetime.now(timezone.utc).isoformat(),
            note="execution did not succeed; nothing to verify",
        )
    base = _base_result(request, observer)
    stamp = now_str or base["provenance"].created_at or ""
    try:
        observed = await _observe_inventory(request, result, reader)
    except Exception as error:
        return VerificationResult(
            **base, outcome="inconclusive",
            observed={"read_error": str(error)[:500]},
            source="inventory-read-bridge",
            verified_at=stamp,
            note="world unreadable; verification inconclusive, "
                 "no FACT promotion",
        )
    if _matches(request.expected, observed):
        return VerificationResult(
            **base, outcome="passed", observed=observed,
            source="inventory-read-bridge", verified_at=stamp,
            note="independent readback matches the expectation",
        )
    return VerificationResult(
        **base, outcome="failed", observed=observed,
        source="inventory-read-bridge", verified_at=stamp,
        note="independent readback differs from the expectation; "
             "execution succeeded but the result is NOT verified",
    )


async def _observe_inventory(request: VerificationRequest,
                             result, reader: InventoryReader) -> dict:
    expected = request.expected
    kind = str(expected.get("kind", "entity"))
    if kind == "entity":
        entity_type = str(expected.get("entity_type", ""))
        entity_id = str(expected.get("entity_id", ""))
        record = await reader.get(entity_type, entity_id)
        if record is None:
            return {"exists": False, "entity_id": entity_id}
        observed: dict[str, Any] = {
            "exists": True,
            "entity_id": record.entity_id,
            "title": record.title,
            "name": record.title,
            "details": dict(record.details),
        }
        for key in ("quantity", "description", "status"):
            if key in record.details:
                observed[key] = record.details[key]
        return observed
    if kind == "relationship":
        entity_id = str(expected.get("from_id", ""))
        graph = await reader.graph(entity_id, 1)
        edges = [{"id": edge.id, "from_id": edge.from_id,
                  "predicate": edge.predicate, "to_id": edge.to_id}
                 for edge in graph.edges]
        return {"from_id": entity_id, "edges": edges}
    raise ValueError(f"Unknown verification expectation kind '{kind}'")


def _matches(expected: dict, observed: dict) -> bool:
    kind = str(expected.get("kind", "entity"))
    if kind == "entity":
        if not observed.get("exists"):
            return False
        # title/name are spellings of the same INVENTory field.
        name = observed.get("name")
        for field in ("entity_id", "quantity", "description", "status"):
            if field in expected and expected[field] != observed.get(field):
                return False
        for field in ("title", "name"):
            if field in expected and expected[field] != name:
                return False
        expected_fields = expected.get("fields", {})
        if isinstance(expected_fields, dict):
            details = observed.get("details", {})
            for key, value in expected_fields.items():
                if key in ("name", "title"):
                    if value != observed.get("name"):
                        return False
                elif details.get(key, observed.get(key)) != value:
                    return False
        return True
    if kind == "relationship":
        wanted = (str(expected.get("from_id", "")),
                  str(expected.get("predicate", "")),
                  str(expected.get("to_id", "")))
        for edge in observed.get("edges", []):
            if ((edge.get("from_id"), edge.get("predicate"),
                 edge.get("to_id")) == wanted):
                return True
        return False
    return False
