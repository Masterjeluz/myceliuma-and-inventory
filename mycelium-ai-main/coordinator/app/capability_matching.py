"""Deterministic capability matching: task intent -> model -> adapter -> node.

Pure data layer (M6.2): the same inputs always yield the same verdicts.
Matching is explicit — every verdict lists what matched, what is missing,
and why a candidate was denied. Doubt defaults to deny.

Vocabularies reused unchanged:
- INVENTory Model records: mod_ ID, model_type, capabilities list.
- Mycelium nodes: node ID, capabilities list.
- INVENTory Task records: task_ ID, input_requirements list.
- M6.1 adapters: an adapter_id plus a registration declaring supported
  model types and required node capabilities.

Nothing here contacts a node, consults a model, or starts any work.
Proposals are produced exclusively through M6.1 adapters and always
require human approval. Empty requirements match every candidate; this
policy is explicit and documented, not an oversight.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .adapter_contracts import (
    MODEL_ID_PREFIX,
    SAFE_ID_PATTERN,
    TASK_ID_PREFIX,
    AdapterProposal,
    AdapterRequest,
)
from .adapters import REFERENCE_ADAPTER_ID, Adapter, ReferenceNoopAdapter
from .inventory_read import Provenance


def _normalize(values) -> list[str]:
    seen: list[str] = []
    for value in values or []:
        text = str(value).strip().lower()
        if text and text not in seen:
            seen.append(text)
    return sorted(seen)


class ModelInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=5, max_length=120)
    model_type: str = Field(default="other", min_length=1, max_length=40)
    capabilities: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("model_id")
    @classmethod
    def _check_model_id(cls, value):
        if not value.startswith(MODEL_ID_PREFIX):
            raise ValueError(f"model_id must start with '{MODEL_ID_PREFIX}'")
        return value


class NodeInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=3, max_length=80, pattern=SAFE_ID_PATTERN)
    capabilities: list[str] = Field(default_factory=list, max_length=30)


class TaskIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str | None = Field(default=None, max_length=120)
    requirements: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("task_id")
    @classmethod
    def _check_task_id(cls, value):
        if value is not None and not value.startswith(TASK_ID_PREFIX):
            raise ValueError(f"task_id must start with '{TASK_ID_PREFIX}'")
        return value


class AdapterRegistration:
    """An adapter plus the conditions under which it may be considered."""

    def __init__(self, adapter: Adapter, model_types=None,
                 required_node_capabilities=()):
        if not isinstance(adapter, Adapter) or not adapter.adapter_id:
            raise ValueError("Registration needs an Adapter with an adapter_id")
        self.adapter_id = adapter.adapter_id
        self.adapter = adapter
        self.model_types = (frozenset(model_types)
                            if model_types is not None else None)
        self.required_node_capabilities = frozenset(
            _normalize(required_node_capabilities))


class AdapterRegistry:
    """Explicit in-memory registry. No automatic discovery of any kind."""

    def __init__(self):
        self._entries: dict[str, AdapterRegistration] = {}

    def register(self, adapter: Adapter, model_types=None,
                 required_node_capabilities=()) -> AdapterRegistration:
        entry = AdapterRegistration(adapter, model_types,
                                    required_node_capabilities)
        self._entries[entry.adapter_id] = entry
        return entry

    def get(self, adapter_id) -> AdapterRegistration | None:
        return self._entries.get(str(adapter_id))

    def adapter_ids(self) -> list[str]:
        return sorted(self._entries)


def default_registry() -> AdapterRegistry:
    """Registry holding only the deterministic reference adapter."""
    registry = AdapterRegistry()
    registry.register(ReferenceNoopAdapter())
    return registry


class MatchVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str | None = None
    model_id: str = ""
    adapter_id: str = ""
    node_id: str | None = None
    compatible: bool = False
    matched_requirements: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    missing_node_capabilities: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


def _coerce_model(raw) -> ModelInfo | None:
    if isinstance(raw, ModelInfo):
        return raw
    if isinstance(raw, dict):
        try:
            return ModelInfo.model_validate(raw)
        except Exception:
            return None
    return None


def match_task(task: TaskIntent, models, registry: AdapterRegistry,
               adapter_id: str | None = None,
               node: NodeInfo | None = None) -> list[MatchVerdict]:
    """Match a task intent against models, adapters and an optional node.

    Returns one verdict per (model, adapter) pair, sorted by
    (model_id, adapter_id). Unknown adapters yield no verdicts at all;
    invalid model entries are skipped without a verdict.
    """
    if adapter_id is not None:
        entries = []
        entry = registry.get(adapter_id)
        if entry is not None:
            entries = [entry]
    else:
        entries = [registry.get(aid) for aid in registry.adapter_ids()]
        entries = [entry for entry in entries if entry is not None]

    valid_models: list[ModelInfo] = []
    for raw in models or []:
        info = _coerce_model(raw)
        if info is not None:
            valid_models.append(info)
    valid_models.sort(key=lambda item: item.model_id)

    required = _normalize(task.requirements)
    node_caps = _normalize(node.capabilities) if node is not None else []
    verdicts: list[MatchVerdict] = []
    for info in valid_models:
        model_caps = _normalize(info.capabilities)
        for entry in entries:
            reasons: list[str] = []
            matched = [item for item in required if item in model_caps]
            missing = [item for item in required if item not in model_caps]
            if entry.model_types is not None and info.model_type not in entry.model_types:
                reasons.append(
                    f"adapter '{entry.adapter_id}' does not support "
                    f"model type '{info.model_type}'")
            if missing:
                reasons.append(
                    f"model '{info.model_id}' lacks: {', '.join(missing)}")
            missing_node: list[str] = []
            if node is None:
                if entry.required_node_capabilities:
                    missing_node = sorted(entry.required_node_capabilities)
                    reasons.append(
                        "node unknown; adapter requires: "
                        + ", ".join(missing_node))
            else:
                missing_node = [item for item in entry.required_node_capabilities
                                if item not in node_caps]
                if missing_node:
                    reasons.append(
                        f"node '{node.node_id}' lacks: "
                        + ", ".join(sorted(missing_node)))
            verdicts.append(MatchVerdict(
                task_id=task.task_id,
                model_id=info.model_id,
                adapter_id=entry.adapter_id,
                node_id=node.node_id if node is not None else None,
                compatible=not reasons,
                matched_requirements=matched,
                missing_requirements=missing,
                missing_node_capabilities=sorted(missing_node),
                reasons=reasons,
            ))
    verdicts.sort(key=lambda item: (item.model_id, item.adapter_id))
    return verdicts


def propose_for_match(verdict: MatchVerdict, registry: AdapterRegistry,
                      request_id: str, extra_input: dict | None = None,
                      provenance: Provenance | None = None) -> AdapterProposal:
    """Ask the verdict's adapter for a proposal. Incompatible verdicts refuse."""
    if not verdict.compatible:
        raise ValueError("Incompatible verdicts never yield proposals")
    entry = registry.get(verdict.adapter_id)
    if entry is None:
        raise ValueError(f"Unknown adapter '{verdict.adapter_id}'")
    payload: dict[str, Any] = {"matched_requirements": verdict.matched_requirements}
    if isinstance(extra_input, dict):
        payload.update(extra_input)
    request = AdapterRequest(
        request_id=request_id,
        adapter_id=entry.adapter_id,
        model_id=verdict.model_id,
        node_id=verdict.node_id,
        task_id=verdict.task_id,
        input=payload,
        provenance=provenance if provenance is not None else Provenance(),
    )
    return entry.adapter.propose(request)
