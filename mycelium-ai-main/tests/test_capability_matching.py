"""Tests for M6.2 deterministic capability matching (data only).

No network, no subprocess, no filesystem writes, no hardware. Matching is
pure: the same inputs always yield the same verdicts.
"""
from pathlib import Path

import pytest
from pydantic import ValidationError

from coordinator.app.adapters import ReferenceNoopAdapter
from coordinator.app.capability_matching import (
    AdapterRegistry,
    MatchVerdict,
    ModelInfo,
    NodeInfo,
    TaskIntent,
    default_registry,
    match_task,
    propose_for_match,
)
from coordinator.app.inventory_read import Provenance


def registry():
    return default_registry()


def model(model_id="mod_cam", model_type="vision", capabilities=("ocr", "detect")):
    return ModelInfo(model_id=model_id, model_type=model_type,
                     capabilities=list(capabilities))


def task(requirements=("ocr",), task_id="task_1"):
    return TaskIntent(task_id=task_id, requirements=list(requirements))


def node(node_id="node-1", capabilities=()):
    return NodeInfo(node_id=node_id, capabilities=list(capabilities))


# --- matching --------------------------------------------------------------------

def test_exact_match_yields_candidate():
    verdicts = match_task(task(), [model()], registry())
    assert len(verdicts) == 1
    verdict = verdicts[0]
    assert verdict.compatible is True
    assert verdict.matched_requirements == ["ocr"]
    assert verdict.missing_requirements == []
    assert verdict.model_id == "mod_cam"
    assert verdict.adapter_id == "reference-noop"
    assert verdict.task_id == "task_1"
    assert verdict.reasons == []


def test_missing_capability_denies():
    verdicts = match_task(task(("ocr", "thermal")), [model()], registry())
    assert len(verdicts) == 1
    verdict = verdicts[0]
    assert verdict.compatible is False
    assert verdict.matched_requirements == ["ocr"]
    assert verdict.missing_requirements == ["thermal"]
    assert any("thermal" in reason for reason in verdict.reasons)


def test_multiple_candidates_deterministic_order():
    models = [model("mod_b"), model("mod_a")]
    first = match_task(task(), models, registry())
    second = match_task(task(), list(reversed(models)), registry())
    assert [v.model_id for v in first] == ["mod_a", "mod_b"]
    assert first == second


def test_empty_requirements_match_all_by_policy():
    verdicts = match_task(task(requirements=()), [model()], registry())
    assert len(verdicts) == 1
    assert verdicts[0].compatible is True
    assert verdicts[0].matched_requirements == []


def test_unknown_model_has_no_verdict():
    with pytest.raises(ValidationError):
        ModelInfo(model_id="proj_x", model_type="vision", capabilities=["ocr"])
    verdicts = match_task(task(), [{"model_id": "proj_x"}], registry())
    assert verdicts == []


def test_unknown_adapter_has_no_verdicts():
    verdicts = match_task(task(), [model()], registry(), adapter_id="ghost")
    assert verdicts == []


def test_capability_mismatch_and_normalization():
    verdicts = match_task(task(("OCR", " Lidar ")), [model()], registry())
    assert verdicts[0].compatible is False
    assert verdicts[0].missing_requirements == ["lidar"]
    verdicts = match_task(task(("OCR",)), [model()], registry())
    assert verdicts[0].compatible is True


def test_model_type_and_node_gates():
    reg = AdapterRegistry()
    reg.register(ReferenceNoopAdapter(), model_types={"ocr"},
                 required_node_capabilities={"camera"})
    verdicts = match_task(task(("ocr",)), [model("mod_x", "vision", ("ocr",))],
                          reg, node=node())
    assert verdicts[0].compatible is False
    assert any("vision" in reason for reason in verdicts[0].reasons)
    verdicts = match_task(task(("ocr",)), [model("mod_x", "ocr", ("ocr",))],
                          reg, node=node())
    assert verdicts[0].compatible is False
    assert verdicts[0].missing_node_capabilities == ["camera"]
    verdicts = match_task(task(("ocr",)), [model("mod_x", "ocr", ("ocr",))],
                          reg, node=node(capabilities=["camera"]))
    assert verdicts[0].compatible is True
    assert verdicts[0].node_id == "node-1"


# --- proposals ---------------------------------------------------------------------

def test_compatible_verdict_proposes_with_approval():
    verdicts = match_task(task(), [model()], registry())
    proposal = propose_for_match(
        verdicts[0], registry(), "mreq-1",
        provenance=Provenance(source_type="user-created", creator_id="tester",
                              human_verified=True))
    assert proposal.requires_approval is True
    assert proposal.provenance.human_verified is False
    assert proposal.provenance.source_type == "ai-generated"
    assert "user-created/tester" in (proposal.provenance.notes or "")
    assert proposal.model_id == "mod_cam"
    assert proposal.task_id == "task_1"


def test_incompatible_verdict_never_proposes():
    verdicts = match_task(task(("thermal",)), [model()], registry())
    assert verdicts[0].compatible is False
    with pytest.raises(ValueError):
        propose_for_match(verdicts[0], registry(), "mreq-1")


# --- absence of execution ---------------------------------------------------------------

EXECUTION_ATTRS = ("execute", "act", "run", "infer", "fetch", "download",
                   "shell", "perform", "dispatch", "invoke")


def test_no_execution_attributes():
    import coordinator.app.capability_matching as matching_mod
    for name in dir(matching_mod):
        if name.startswith("__"):
            continue
        assert name.lower() not in EXECUTION_ATTRS, f"module must not offer {name}"
    for cls in (AdapterRegistry, MatchVerdict, ModelInfo, NodeInfo, TaskIntent):
        for name in dir(cls):
            assert name.lower() not in EXECUTION_ATTRS


def test_implementation_has_no_io_tokens():
    source = (Path(__file__).resolve().parent.parent
              / "coordinator" / "app" / "capability_matching.py").read_text(
                  encoding="utf-8")
    for token in ("subprocess", "os.system", "socket", "httpx", "requests",
                  "torch", "transformers", "ollama", "serial", "GPIO",
                  "threading", "asyncio", "pathlib", "shutil", "open(",
                  "execute", "infer", "fetch", "download"):
        assert token not in source, f"matching layer must not use {token}"
