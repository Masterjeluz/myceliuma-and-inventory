"""Vision-to-world flow for Mycelium (BIG #6).

Chains the existing pieces without a second approval, write or
verification system:

    camera observation -> VLM analysis (ADVICE)
        -> WriteProposal (inert, BIG #5)
        -> human exact-YES (existing dialect)
        -> controlled write (BIG #5, approval-bound)
        -> independent verification (BIG #5 readback)

Rules (tested, all fail-closed):

- This module PROPOSES and VERIFIES only. It contains no
  execution path: no execute call, no revalidation shortcut,
  no auto-write on high confidence. A vision result without a
  human YES can never become an INVENTory mutation — not even
  at confidence 0.99.
- Identification keeps uncertainty: every candidate label with
  its model-supplied confidence lands in the proposal
  description; the top candidate names the object but is never
  marked verified.
- Observation verification checks the stored observation
  (identity, source camera, media reference, timestamp,
  sensor-observed/unverified provenance) plus local media
  existence. observation != fact, before and after.
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .cameras import CameraObservation
from .inventory_read import Provenance
from .inventory_writes import propose_inventory_write
from .controlled_writes import WriteProposal
from .verification import (
    VerificationRequest,
    VerificationResult,
    generate_verification_id,
    is_verified,
)

VISION_ADAPTER_ID = "mycelium-vision"


class VisionAnalysisRecord(BaseModel):
    """Stored VLM analysis: structured advice bound to one
    observation. Owned by Mycelium (chat/agent database)."""

    model_config = ConfigDict(extra="forbid")

    analysis_id: str = Field(min_length=3, max_length=80)
    observation_id: str = Field(min_length=3, max_length=80)
    device_id: str = Field(min_length=3, max_length=80)
    result: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


def identification_candidates(vision_result) -> list[tuple[str, float]]:
    """Candidate (label, confidence) pairs, best first. Model-
    supplied confidences are ordering hints, never truth."""
    detected = getattr(vision_result, "detected_objects", []) or []
    candidates: list[tuple[str, float]] = []
    for item in detected:
        label = getattr(item, "label", "")
        confidence = getattr(item, "confidence", 0.0)
        if isinstance(label, str) and label.strip():
            try:
                score = max(0.0, min(1.0, float(confidence)))
            except (TypeError, ValueError):
                score = 0.0
            candidates.append((label.strip(), score))
    candidates.sort(key=lambda entry: -entry[1])
    return candidates


def _candidate_description(candidates: list[tuple[str, float]],
                           vision_result, observation_id: str) -> str:
    lines = [f"VLM-kandidaten uit {observation_id} (advies, "
             "niet geverifieerd):"]
    for label, confidence in candidates[:10]:
        lines.append(f"- {label} (model-confidence {confidence:.2f})")
    description = str(getattr(vision_result, "description", "")
                      or "")[:500]
    if description:
        lines.append(f"VLM-beschrijving: {description}")
    lines.append("Identiteit onbevestigd tot menselijke goedkeuring "
                 "en onafhankelijke verificatie.")
    return "\n".join(lines)[:2000]


def vision_to_object_proposal(vision_result, observation,
                              *, proposal_id: str,
                              actor: str = "mycelium"
                              ) -> WriteProposal:
    """One inert inventory.create proposal from a VLM analysis.

    Refuses when the analysis carries no labels: an empty
    analysis never becomes a proposal, let alone a write.
    """
    candidates = identification_candidates(vision_result)
    if not candidates:
        raise ValueError(
            "Vision analysis carries no labels; refusing to propose")
    top_label = candidates[0][0]
    observation_id = str(getattr(
        observation, "observation_id",
        getattr(vision_result, "observation_id", "")))
    return propose_inventory_write(
        proposal_id, "create", "object",
        {"name": top_label[:200],
         "description": _candidate_description(
             candidates, vision_result, observation_id)},
        actor=actor)


def vision_to_file_proposal(file_payload: dict, *,
                            proposal_id: str,
                            actor: str = "mycelium") -> WriteProposal:
    """One inert inventory.create/file proposal for captured media."""
    if not isinstance(file_payload, dict) or not file_payload:
        raise ValueError("File proposal needs a media file payload")
    return propose_inventory_write(
        proposal_id, "create", "file", dict(file_payload),
        actor=actor)


def new_observation_verification_request(
        proposal_id: str, result_fingerprint: str,
        observation: CameraObservation) -> VerificationRequest:
    """Expectation for one observation: identity, source camera,
    media reference — read back independently, never trusted."""
    return VerificationRequest(
        verification_id=generate_verification_id(),
        proposal_id=proposal_id,
        result_fingerprint=result_fingerprint,
        method="camera.readback",
        expected={
            "kind": "observation",
            "observation_id": observation.observation_id,
            "device_id": observation.device_id,
            "media_ref": observation.media_ref,
        },
    )


def verify_observation(request: VerificationRequest,
                       observation: CameraObservation | None, *,
                       media_exists: bool,
                       now_str: str | None = None
                       ) -> VerificationResult:
    """Verify one camera observation against the store record plus
    local media existence. observation != fact: a pass confirms
    the capture record, never the identity of what is pictured."""
    stamp = now_str or datetime.now(timezone.utc).isoformat()
    base = {
        "verification_id": request.verification_id,
        "proposal_id": request.proposal_id,
        "result_fingerprint": request.result_fingerprint,
        "method": "camera.readback",
        "expected": dict(request.expected),
        "observer": "mycelium-verifier",
        "provenance": Provenance(
            source_type="sensor-observed",
            creator_id="mycelium-verifier", human_verified=False,
            notes="independent observation readback; identity of "
                  "pictured content stays unconfirmed"),
    }
    expected = request.expected
    if not isinstance(observation, CameraObservation):
        return VerificationResult(
            **base, outcome="inconclusive",
            observed={"stored": False},
            source="observation-store", verified_at=stamp,
            note="observation not in store; inconclusive, no promotion")
    observed = {
        "stored": True,
        "observation_id": observation.observation_id,
        "device_id": observation.device_id,
        "media_ref": observation.media_ref,
        "media_exists": bool(media_exists),
        "created_at": observation.created_at,
        "provenance": observation.provenance.model_dump(mode="json"),
    }
    for field in ("observation_id", "device_id", "media_ref"):
        if (field in expected
                and expected[field] != observed.get(field)):
            return VerificationResult(
                **base, outcome="failed", observed=observed,
                source="observation-store", verified_at=stamp,
                note=f"{field} mismatch; NOT verified")
    if not media_exists:
        return VerificationResult(
            **base, outcome="failed", observed=observed,
            source="observation-store", verified_at=stamp,
            note="media file missing locally; NOT verified")
    if observation.provenance.human_verified:
        return VerificationResult(
            **base, outcome="failed", observed=observed,
            source="observation-store", verified_at=stamp,
            note="observation claims human verification it cannot "
                 "hold from capture alone; NOT verified")
    return VerificationResult(
        **base, outcome="passed", observed=observed,
        source="observation-store", verified_at=stamp,
        note="stored observation matches identity, source camera "
             "and local media; pictured identity still unconfirmed")


def save_analysis(record: VisionAnalysisRecord) -> None:
    from .database import dump, init_chat_database, chat_connection
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO vision_analyses
        (analysis_id, observation_id, record, created_at)
        VALUES (?, ?, ?, ?)""",
                    (record.analysis_id, record.observation_id,
                     dump(record.model_dump(mode="json")),
                     record.created_at or
                     datetime.now(timezone.utc).isoformat()))


def load_analysis(analysis_id: str) -> VisionAnalysisRecord | None:
    from .database import init_chat_database, chat_connection, load
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT record FROM vision_analyses "
                         "WHERE analysis_id=?",
                         (analysis_id,)).fetchone()
    if row is None:
        return None
    return VisionAnalysisRecord.model_validate(load(row["record"]))


def list_analyses(observation_id: str, limit: int = 10
                  ) -> list[VisionAnalysisRecord]:
    from .database import init_chat_database, chat_connection, load
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute(
            """SELECT record FROM vision_analyses WHERE observation_id=?
            ORDER BY created_at DESC LIMIT ?""",
            (observation_id, max(1, min(limit, 50)))).fetchall()
    return [VisionAnalysisRecord.model_validate(load(row["record"]))
            for row in rows]


__all__ = [
    "VISION_ADAPTER_ID",
    "VisionAnalysisRecord",
    "identification_candidates",
    "is_verified",
    "load_analysis",
    "list_analyses",
    "new_observation_verification_request",
    "save_analysis",
    "verify_observation",
    "vision_to_file_proposal",
    "vision_to_object_proposal",
]
