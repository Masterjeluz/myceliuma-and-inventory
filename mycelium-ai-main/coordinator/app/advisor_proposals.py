"""Advice text to optional AdapterProposal (M8.2, untrusted input).

A model answer may carry one fenced ```json block describing a proposal.
Everything inside that block is UNTRUSTED: identities, provenance and
approval flags supplied by the model are never taken at face value.

Rules enforced here, on top of the M6.1 schema itself:

- proposal_id, request_id and adapter_id always come from the caller,
  never from the model. proposal_id derives deterministically.
- model_id, node_id and task_id from the block are accepted only when
  they pass M6.1 validation; anything else voids the whole proposal.
- provenance is always set by this module (ai-generated, unverified,
  referencing the advice); model-supplied provenance is ignored.
- requires_approval can only be True (M6.1 schema voids anything else).
- malformed blocks, missing actions and oversized text void the proposal
  and leave plain text advice standing alone (fail-closed, no fabrication).

No queue, no staging, no promotion, no approval, no dispatch. The result
is either a validated proposal or None.
"""

import json
import re
from typing import Any

from pydantic import ValidationError

from .adapter_contracts import AdapterProposal
from .inventory_read import Provenance

_FENCE_PATTERN = re.compile(r"```json\s*(\{.*?\})\s*```",
                            re.DOTALL | re.IGNORECASE)
MAX_BLOCK_CHARS = 2000
MAX_ACTION_CHARS = 2000
MAX_TEXT_LIST_ITEMS = 20
MAX_TEXT_ITEM_CHARS = 200


def _clean_text(value, max_chars: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > max_chars:
        return None
    return text


def _clean_text_list(value) -> list[str] | None:
    if not isinstance(value, list):
        return None
    cleaned: list[str] = []
    for item in value[:MAX_TEXT_LIST_ITEMS]:
        text = _clean_text(item, MAX_TEXT_ITEM_CHARS)
        if text is None:
            return None
        cleaned.append(text)
    return cleaned


def _proposal_id_for(request_id: str) -> str:
    return f"prop-{request_id}"[:80]


def extract_proposal(advice: str, *, adapter_id: str, request_id: str,
                     model_id: str | None = None, node_id: str | None = None,
                     task_id: str | None = None) -> AdapterProposal | None:
    """Build a validated proposal from advice text, or None.

    IDs come from explicit arguments (caller-controlled). The text block
    may only supply proposed_action, expected_output, risks, and the
    optional model/node/task links, each strictly validated.
    """
    if not isinstance(advice, str) or not advice.strip():
        return None
    match = _FENCE_PATTERN.search(advice)
    if match is None:
        return None
    raw = match.group(1)
    if len(raw) > MAX_BLOCK_CHARS:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if "requires_approval" in data and data["requires_approval"] is not True:
        return None
    claimed_provenance = data.get("provenance")
    if isinstance(claimed_provenance, dict) and claimed_provenance.get(
            "human_verified"):
        return None
    action = _clean_text(data.get("proposed_action"), MAX_ACTION_CHARS)
    if action is None:
        return None
    expected = _clean_text(data.get("expected_output", ""), MAX_ACTION_CHARS)
    if expected is None:
        return None
    risks = _clean_text_list(data.get("risks", []))
    if risks is None:
        return None
    links: dict[str, Any] = {}
    for key in ("model_id", "node_id", "task_id"):
        present = key in data
        supplied = data.get(key)
        fallback = {"model_id": model_id, "node_id": node_id,
                    "task_id": task_id}[key]
        if present:
            if supplied is not None and not isinstance(supplied, str):
                return None
            links[key] = supplied
        else:
            links[key] = fallback
    try:
        return AdapterProposal(
            proposal_id=_proposal_id_for(request_id),
            request_id=request_id,
            adapter_id=adapter_id,
            model_id=links["model_id"],
            node_id=links["node_id"],
            task_id=links["task_id"],
            proposed_action=action,
            expected_output=expected,
            risks=risks,
            provenance=Provenance(
                source_type="ai-generated",
                creator_id=f"advisor:{adapter_id}",
                human_verified=False,
                notes="proposal parsed from untrusted model text; "
                      "identities validated, provenance set locally",
            ),
            requires_approval=True,
        )
    except (ValidationError, ValueError, TypeError):
        return None
