"""Explicit executor registry for Mycelium (M7.3).

Identity plus capability discovery only. This module answers three
questions and nothing more:

- is this kind registered? (:func:`resolve_executor`)
- which spec belongs to it? (the returned :class:`ExecutorSpec`)
- does a node claim the matching capability? (:func:`supports_node`)

It never authorizes, never dispatches, never completes, and never
approves anything. A successful registry match means exclusively:
"this executor exists and this node claims the matching capability."

Namespace rule: only capabilities of the exact form ``exec:<kind>``
count. Bare names, longer names sharing a prefix, and names from other
namespaces never match. No substring or fuzzy matching anywhere.
"""

from pydantic import BaseModel, ConfigDict, Field

EXEC_NAMESPACE = "exec:"
SYSTEM_INVENTORY_KIND = "system_inventory"


class ExecutorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executor_id: str = Field(min_length=1, max_length=80)
    kind: str = Field(min_length=1, max_length=80)
    capability: str = Field(min_length=1, max_length=80)
    input_contract: dict = Field(default_factory=dict)
    output_contract: dict = Field(default_factory=dict)
    allowed_side_effects: list[str] = Field(default_factory=list)


def _canonical_capability(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text or not text.startswith(EXEC_NAMESPACE):
        return None
    return text


class ExecutorRegistry:
    """Explicit, deterministic registry. Entries are fixed at construction."""

    def __init__(self):
        self._by_kind: dict[str, ExecutorSpec] = {}
        self._ids: set[str] = set()
        self._capabilities: set[str] = set()

    def register(self, spec: ExecutorSpec) -> ExecutorSpec:
        if not isinstance(spec, ExecutorSpec):
            raise ValueError("Only ExecutorSpec entries can be registered")
        if spec.executor_id in self._ids:
            raise ValueError(f"Duplicate executor_id '{spec.executor_id}'")
        if spec.kind in self._by_kind:
            raise ValueError(f"Duplicate kind '{spec.kind}'")
        if spec.capability in self._capabilities:
            raise ValueError(f"Duplicate capability '{spec.capability}'")
        self._by_kind[spec.kind] = spec
        self._ids.add(spec.executor_id)
        self._capabilities.add(spec.capability)
        return spec

    def kinds(self) -> list[str]:
        return sorted(self._by_kind)

    def executor_ids(self) -> list[str]:
        return sorted(self._ids)


def resolve_executor(registry: ExecutorRegistry, kind) -> ExecutorSpec | None:
    """Exact lookup of a registered kind. Unknown or malformed kinds deny."""
    if not isinstance(kind, str) or not kind:
        return None
    return registry._by_kind.get(kind)


def supports_node(spec: ExecutorSpec, node_capabilities) -> bool:
    """Exact capability check: the node must claim spec.capability verbatim.

    Node entries are normalized (trimmed, lowercased) exactly as M6.2
    permits; the registry value itself is canonical. Anything else denies.
    """
    if not isinstance(spec, ExecutorSpec):
        return False
    if not isinstance(node_capabilities, (list, tuple, set)):
        return False
    claimed = set()
    for entry in node_capabilities:
        canonical = _canonical_capability(entry)
        if canonical is not None:
            claimed.add(canonical)
    return spec.capability in claimed


def default_executor_registry() -> ExecutorRegistry:
    """Registry holding only the pre-existing system_inventory executor."""
    registry = ExecutorRegistry()
    registry.register(ExecutorSpec(
        executor_id=SYSTEM_INVENTORY_KIND,
        kind=SYSTEM_INVENTORY_KIND,
        capability=f"{EXEC_NAMESPACE}{SYSTEM_INVENTORY_KIND}",
        input_contract={},
        output_contract={"operating_system": "str", "machine": "str",
                         "cpu_cores": "int", "memory_mb": "int"},
        allowed_side_effects=[],
    ))
    return registry
