"""Tests for the M6.1 adapter data contracts (no execution surface).

No network, no subprocess, no filesystem writes, no hardware. The reference
adapter runs in-process and must prove it performs no I/O besides returning
a proposal object.
"""
from pathlib import Path

import pytest
from pydantic import ValidationError

from coordinator.app.adapter_contracts import AdapterProposal, AdapterRequest
from coordinator.app.adapters import (
    Adapter,
    ReferenceNoopAdapter,
    REFERENCE_ADAPTER_ID,
)

PROV = {"source_type": "user-created", "creator_id": "tester",
        "human_verified": True}


def make_request(**overrides):
    payload = {"request_id": "req-1", "adapter_id": REFERENCE_ADAPTER_ID,
               "input": {"object_id": "obj_abc"}, "provenance": dict(PROV)}
    payload.update(overrides)
    return AdapterRequest.model_validate(payload)


# --- contract validation ---------------------------------------------------------

def test_valid_request_and_ids():
    req = make_request(model_id="mod_x", node_id="node-1", task_id="task_9")
    assert req.model_id == "mod_x"
    assert req.task_id == "task_9"


@pytest.mark.parametrize("field,value", [
    ("model_id", "proj_x"), ("model_id", "model-x"), ("model_id", ""),
    ("task_id", "mod_x"), ("task_id", "task"), ("task_id", ""),
    ("node_id", "a"), ("node_id", "node/x"), ("node_id", ""),
    ("request_id", ""), ("request_id", "ab"), ("request_id", "req/x"),
    ("adapter_id", ""), ("adapter_id", "ref/noop"),
])
def test_invalid_ids_refused(field, value):
    with pytest.raises(ValidationError):
        make_request(**{field: value})


def test_missing_required_fields_refused():
    with pytest.raises(ValidationError):
        AdapterRequest.model_validate({"adapter_id": REFERENCE_ADAPTER_ID})
    with pytest.raises(ValidationError):
        AdapterProposal.model_validate({"request_id": "req-1"})


def test_proposal_requires_approval_always():
    base = {"proposal_id": "prop-1", "request_id": "req-1",
            "adapter_id": REFERENCE_ADAPTER_ID,
            "proposed_action": "do nothing", "provenance": {
                "source_type": "ai-generated", "creator_id": "adapter:x",
                "human_verified": False}}
    ok = AdapterProposal.model_validate(base)
    assert ok.requires_approval is True
    with pytest.raises(ValidationError):
        AdapterProposal.model_validate({**base, "requires_approval": False})
    with pytest.raises(ValidationError):
        AdapterProposal.model_validate({**base, "provenance": {
            "source_type": "ai-generated", "creator_id": "adapter:x",
            "human_verified": True}})
    with pytest.raises(ValidationError):
        AdapterProposal.model_validate({**base, "proposed_action": ""})


# --- reference adapter ---------------------------------------------------------------

def test_reference_adapter_produces_proposal_only():
    adapter = ReferenceNoopAdapter()
    first = adapter.propose(make_request())
    second = adapter.propose(make_request())
    assert first == second
    assert first.adapter_id == REFERENCE_ADAPTER_ID
    assert first.request_id == "req-1"
    assert first.requires_approval is True
    assert first.expected_output and first.risks
    assert first.provenance.source_type == "ai-generated"
    assert first.provenance.human_verified is False
    assert "user-created/tester" in (first.provenance.notes or "")


def test_reference_adapter_rejects_foreign_adapter_id():
    adapter = ReferenceNoopAdapter()
    with pytest.raises(ValueError):
        adapter.propose(make_request(adapter_id="other-adapter"))


def test_no_execute_surface():
    for name in ("execute", "act", "run", "infer", "fetch", "download",
                 "read", "write", "shell"):
        assert not hasattr(Adapter, name), f"Adapter must not offer {name}"
        assert not hasattr(ReferenceNoopAdapter, name), (
            f"ReferenceNoopAdapter must not offer {name}")


def test_adapter_modules_contain_no_io():
    for module in ("adapter_contracts.py", "adapters.py"):
        source = (Path(__file__).resolve().parent.parent
                  / "coordinator" / "app" / module).read_text(encoding="utf-8")
        for forbidden in ("subprocess", "os.system", "socket", "httpx",
                          "requests", "urllib", "open(", "pathlib",
                          "shutil", "threading", "asyncio", "torch",
                          "transformers", "ollama", "cv2", "serial",
                          "inference", "download"):
            assert forbidden not in source, f"{module} must not use {forbidden}"


def test_reference_adapter_performs_no_filesystem_writes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.iterdir())
    ReferenceNoopAdapter().propose(make_request())
    assert set(tmp_path.iterdir()) == before
