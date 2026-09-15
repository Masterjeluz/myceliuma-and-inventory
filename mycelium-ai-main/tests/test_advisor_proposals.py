"""Tests for M8.2 advice-to-proposal extraction (untrusted model text).

No real model, no network, no database, no filesystem writes. One
integration test drives the mocked Ollama advisor into the extractor;
everything else calls the pure extractor directly.
"""
import asyncio
from pathlib import Path

import httpx

from coordinator.app.advisor_proposals import extract_proposal
from coordinator.app.ollama_advisor import OllamaAdvisor

ADAPTER = "reference-noop"
REQUEST = "req-81"


def run(coro):
    return asyncio.run(coro)


def advice_with(block: str) -> str:
    return ("Ik stel voor om een opbergmodule te ontwerpen.\n\n"
            f"```json\n{block}\n```\n\nGroet.")


def valid_block(**overrides):
    import json
    payload = {"proposed_action": "Ontwerp een opbergmodule.",
               "expected_output": "Een schets met maten.",
               "risks": ["hout is op"]}
    payload.update(overrides)
    return json.dumps(payload)


# --- behavior ------------------------------------------------------------------------

def test_plain_advice_has_no_proposal():
    assert extract_proposal("Gewoon advies zonder blok.",
                            adapter_id=ADAPTER, request_id=REQUEST) is None
    assert extract_proposal("", adapter_id=ADAPTER, request_id=REQUEST) is None
    assert extract_proposal(None, adapter_id=ADAPTER, request_id=REQUEST) is None


def test_valid_proposal():
    proposal = extract_proposal(advice_with(valid_block()),
                                adapter_id=ADAPTER, request_id=REQUEST,
                                model_id="mod_cam")
    assert proposal is not None
    assert proposal.proposal_id == "prop-req-81"
    assert proposal.request_id == REQUEST
    assert proposal.adapter_id == ADAPTER
    assert proposal.model_id == "mod_cam"
    assert proposal.proposed_action == "Ontwerp een opbergmodule."
    assert proposal.requires_approval is True
    assert proposal.provenance.human_verified is False
    assert proposal.provenance.source_type == "ai-generated"


def test_malformed_proposal_yields_none():
    assert extract_proposal("```json\n{geen json\n```",
                            adapter_id=ADAPTER, request_id=REQUEST) is None
    assert extract_proposal("```json\n[1, 2]\n```",
                            adapter_id=ADAPTER, request_id=REQUEST) is None
    assert extract_proposal("```json\n{}\n```",
                            adapter_id=ADAPTER, request_id=REQUEST) is None
    assert extract_proposal("```json\n" + valid_block(proposed_action="  ")
                            + "\n```",
                            adapter_id=ADAPTER, request_id=REQUEST) is None
    assert extract_proposal("```json\n" + "x" * 3000 + "\n```",
                            adapter_id=ADAPTER, request_id=REQUEST) is None


def test_tampered_flags_refused():
    assert extract_proposal(
        advice_with(valid_block(requires_approval=False)),
        adapter_id=ADAPTER, request_id=REQUEST) is None
    assert extract_proposal(
        advice_with(valid_block(
            provenance={"source_type": "user-created",
                        "creator_id": "model", "human_verified": True})),
        adapter_id=ADAPTER, request_id=REQUEST) is None


def test_wrong_ids_refused():
    assert extract_proposal(advice_with(valid_block(model_id="proj_x")),
                            adapter_id=ADAPTER, request_id=REQUEST) is None
    assert extract_proposal(advice_with(valid_block(task_id="nope")),
                            adapter_id=ADAPTER, request_id=REQUEST) is None
    assert extract_proposal(advice_with(valid_block()),
                            adapter_id=ADAPTER, request_id="bad id!") is None
    assert extract_proposal(advice_with(valid_block()),
                            adapter_id="bad adapter!", request_id=REQUEST) is None


def test_caller_links_used_when_block_silent():
    proposal = extract_proposal(advice_with(valid_block()),
                                adapter_id=ADAPTER, request_id=REQUEST,
                                node_id="node-7", task_id="task_3")
    assert proposal is not None
    assert proposal.node_id == "node-7"
    assert proposal.task_id == "task_3"


def test_proposal_independent_of_approval():
    proposal = extract_proposal(advice_with(valid_block()),
                                adapter_id=ADAPTER, request_id=REQUEST)
    assert proposal is not None
    assert not hasattr(proposal, "approved")
    assert not hasattr(proposal, "approval")


def test_no_queue_db_filesystem_side_effects(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proposal = extract_proposal(advice_with(valid_block()),
                                adapter_id=ADAPTER, request_id=REQUEST)
    assert proposal is not None
    assert list(tmp_path.iterdir()) == []


def test_no_execution_surface():
    import coordinator.app.advisor_proposals as module
    for name in dir(module):
        if name.startswith("__"):
            continue
        lowered = name.lower()
        for token in ("execute", "dispatch", "queue", "stage", "approve",
                      "claim", "complete"):
            assert token not in lowered, f"extractor must not offer {name}"
    source = (Path(__file__).resolve().parent.parent
              / "coordinator" / "app" / "advisor_proposals.py").read_text(
                  encoding="utf-8")
    for token in ("subprocess", "os.system", "socket", "httpx", "requests",
                  "torch", "transformers", "ollama", "serial", "GPIO",
                  "threading", "asyncio", "pathlib", "shutil", "open(",
                  "inference", "download"):
        assert token not in source, f"extractor must not use {token}"


def test_mocked_advisor_to_proposal_chain():
    def handle(request):
        return httpx.Response(200, json={
            "response": advice_with(valid_block())})
    advisor = OllamaAdvisor(
        base_url="http://127.0.0.1:11434", model="test-model",
        transport=httpx.MockTransport(handle))
    answered = run(advisor.advise(
        "Wat stel je voor?",
        [{"entity_type": "object", "entity_id": "obj_1", "title": "Hout",
          "snippet": "plank", "provenance": {"source_type": "user-created",
                                              "creator_id": "tester",
                                              "human_verified": True}}]))
    proposal = extract_proposal(answered.advice, adapter_id=ADAPTER,
                                request_id=REQUEST)
    assert proposal is not None
    assert proposal.requires_approval is True
    assert proposal.provenance.human_verified is False
