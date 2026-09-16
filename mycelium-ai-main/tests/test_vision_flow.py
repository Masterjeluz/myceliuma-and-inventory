"""Vision-to-world flow tests (BIG #6).

Identification with uncertainty, inert proposals, observation
verification, and the automatic-write prohibition: a vision
result without a human YES can never become a mutation.
"""

import os

import pytest

from coordinator.app.cameras import new_device, new_observation
from coordinator.app.inventory_read import Provenance
from coordinator.app.vision_flow import (
    VisionAnalysisRecord,
    identification_candidates,
    list_analyses,
    load_analysis,
    new_observation_verification_request,
    save_analysis,
    verify_observation,
    vision_to_file_proposal,
    vision_to_object_proposal,
)
from coordinator.app.vision_ingest import (
    SyntheticTestAdapter,
    ingest_snapshot,
)
from coordinator.app.vision_provider import (
    TestVisionProvider,
    VisionRequest,
    VisionResult,
    build_result,
)
from coordinator.app.verification import is_verified


def run(coro):
    import asyncio
    return asyncio.run(coro)


def make_vision(labels=("moer", "ring")):
    provider = TestVisionProvider(labels=list(labels))
    return run(provider.analyze(VisionRequest(
        observation_id="obs-flow1", device_id="cam-flow1",
        media_ref="cam-x.bmp")))


def make_observation(observation_id="obs-flow1",
                     device_id="cam-flow1"):
    return new_observation(observation_id, device_id, "snapshot",
                           media_ref="", width=64, height=48)


def test_candidates_keep_uncertainty_sorted():
    result = make_vision(("ring", "moer"))
    candidates = identification_candidates(result)
    assert [label for label, _ in candidates] == ["ring", "moer"]
    assert all(score == 0.5 for _, score in candidates)


def test_object_proposal_names_top_candidate_unverified():
    result = make_vision(("moer", "ring"))
    proposal = vision_to_object_proposal(
        result, make_observation(), proposal_id="wrt-vis1")
    assert proposal.mutation_type == "inventory.create"
    assert proposal.payload["fields"]["name"] == "moer"
    assert "ring" in proposal.payload["fields"]["description"]
    assert "niet geverifieerd" in proposal.payload["fields"][
        "description"]
    assert proposal.provenance.human_verified is False


def test_empty_analysis_never_proposes():
    result = build_result(
        VisionRequest(observation_id="obs-e", device_id="cam-e",
                      media_ref="cam-x.bmp"),
        "geen idee", "m")
    assert result.labels == []
    with pytest.raises(ValueError, match="no labels"):
        vision_to_object_proposal(
            result, make_observation("obs-e", "cam-e"),
            proposal_id="wrt-visx")


def test_file_proposal_from_media_payload():
    device = new_device("cam-flow2", "C", ["snapshot"], "manual")
    ingested = ingest_snapshot(device, SyntheticTestAdapter(),
                               test_origin=True)
    proposal = vision_to_file_proposal(
        ingested.file_payload, proposal_id="wrt-vis2")
    assert proposal.mutation_type == "inventory.create"
    assert proposal.payload["entity_type"] == "file"
    assert proposal.payload["fields"]["file_kind"] == "image"
    assert proposal.payload["fields"]["sha256"] == (
        ingested.media.sha256)
    with pytest.raises(ValueError, match="file payload"):
        vision_to_file_proposal({}, proposal_id="wrt-visx")


def test_observation_verification_passes():
    device = new_device("cam-flow3", "C", ["snapshot"], "manual")
    ingested = ingest_snapshot(device, SyntheticTestAdapter(),
                               test_origin=True)
    observation = ingested.observation
    request = new_observation_verification_request(
        "wrt-vis3", "0" * 64, observation)
    assert request.method == "camera.readback"
    verification = verify_observation(
        request, observation, media_exists=True)
    assert verification.outcome == "passed"
    assert is_verified(verification) is True
    # A pass confirms the record — never the pictured identity.
    assert "unconfirmed" in verification.note


def test_observation_verification_fails_and_inconclusive():
    observation = make_observation()
    request = new_observation_verification_request(
        "wrt-vis4", "0" * 64, observation)
    missing = verify_observation(request, None, media_exists=False)
    assert missing.outcome == "inconclusive"
    assert is_verified(missing) is False
    gone = verify_observation(request, observation, media_exists=False)
    assert gone.outcome == "failed"
    assert is_verified(gone) is False
    tampered = observation.model_copy(update={"device_id": "cam-ander"})
    mismatch = verify_observation(request, tampered, media_exists=True)
    assert mismatch.outcome == "failed"


def test_observation_claiming_verified_fails():
    observation = make_observation()
    forged = observation.model_copy(update={
        "provenance": Provenance(
            source_type="sensor-observed", creator_id="camera:x",
            human_verified=True, verified_by="iemand")})
    request = new_observation_verification_request(
        "wrt-vis5", "0" * 64, observation)
    verification = verify_observation(request, forged,
                                      media_exists=True)
    assert verification.outcome == "failed"
    assert is_verified(verification) is False


def test_no_execution_path_in_flow_module():
    import pathlib
    import coordinator.app.vision_flow as module
    source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    for token in ("execute_", "revalidate(", "decide_write",
                  "dispatch", ".commit(", ".push("):
        assert token not in source, f"forbidden token: {token}"
    # The only write contact is inert proposal construction.
    assert "propose_inventory_write" in source


def test_analysis_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "vis.db"))
    record = VisionAnalysisRecord(
        analysis_id="vis-1", observation_id="obs-flow1",
        device_id="cam-flow1",
        result={"labels": ["moer"]}, created_at="2026-01-01T00:00:00")
    save_analysis(record)
    assert load_analysis("vis-1").analysis_id == "vis-1"
    assert load_analysis("vis-missing") is None
    assert len(list_analyses("obs-flow1")) == 1


def test_high_confidence_never_auto_authorizes():
    """Confidence 0.99 without a human YES authorizes nothing: the
    flow module exposes no approval/execution surface at all."""
    import coordinator.app.vision_flow as module
    assert not hasattr(module, "approve")
    assert not hasattr(module, "execute")
    assert not hasattr(module, "auto_write")
    result = build_result(
        VisionRequest(observation_id="obs-h", device_id="cam-h",
                      media_ref="cam-x.bmp"),
        "label: moer (0.99)", "m")
    assert result.detected_objects[0].confidence == 0.99
    assert result.provenance.human_verified is False
