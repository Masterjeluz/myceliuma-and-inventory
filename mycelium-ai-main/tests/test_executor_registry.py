"""Tests for the M7.3 executor registry (pure discovery, no execution).

No servers, no nodes, no database, no network. Every test is a pure
function call; nothing here can start, approve, or complete anything.
"""
from pathlib import Path

import pytest

from coordinator.app.executor_registry import (
    EXEC_NAMESPACE,
    ExecutorRegistry,
    ExecutorSpec,
    default_executor_registry,
    resolve_executor,
    supports_node,
)


@pytest.fixture()
def registry():
    return default_executor_registry()


def spec(**overrides):
    payload = {"executor_id": "system_inventory", "kind": "system_inventory",
               "capability": "exec:system_inventory"}
    payload.update(overrides)
    return ExecutorSpec.model_validate(payload)


# --- registry contents ---------------------------------------------------------------

def test_default_registry_holds_only_system_inventory(registry):
    assert registry.kinds() == ["system_inventory"]
    assert registry.executor_ids() == ["system_inventory"]
    entry = resolve_executor(registry, "system_inventory")
    assert entry.capability == "exec:system_inventory"
    assert entry.executor_id == "system_inventory"
    assert entry.allowed_side_effects == []


def test_known_kind_resolves(registry):
    entry = resolve_executor(registry, "system_inventory")
    assert isinstance(entry, ExecutorSpec)
    assert entry.kind == "system_inventory"


@pytest.mark.parametrize("kind", [None, "", 123, "unknown_kind", "SYSTEM_INVENTORY",
                                  "system_inventory ", " exec:system_inventory",
                                  "system_inventory_extra", "system_inventor"])
def test_unknown_malformed_kinds_deny(registry, kind):
    assert resolve_executor(registry, kind) is None


# --- node capability matching ----------------------------------------------------------

def test_matching_capability(registry):
    entry = resolve_executor(registry, "system_inventory")
    assert supports_node(entry, ["exec:system_inventory"]) is True
    assert supports_node(entry, ["other", "EXEC:SYSTEM_INVENTORY"]) is True


@pytest.mark.parametrize("caps", [
    [], ["system_inventory"], ["exec:unknown"], ["exec:system_inventory_extra"],
    ["exec:system"], ["exec:"], ["xexec:system_inventory"], "exec:system_inventory",
    None, [123], [""],
])
def test_non_matching_capabilities_deny(registry, caps):
    entry = resolve_executor(registry, "system_inventory")
    assert supports_node(entry, caps) is False


def test_no_prefix_or_substring_matching(registry):
    entry = resolve_executor(registry, "system_inventory")
    assert supports_node(entry, ["exec:system_inventory_v2"]) is False
    assert supports_node(entry, ["my-exec:system_inventory-x"]) is False


# --- registry integrity ------------------------------------------------------------------

def test_duplicates_impossible():
    registry = ExecutorRegistry()
    registry.register(spec())
    with pytest.raises(ValueError):
        registry.register(spec())
    with pytest.raises(ValueError):
        registry.register(spec(executor_id="other", capability="exec:other"))
    with pytest.raises(ValueError):
        registry.register(spec(executor_id="other", kind="other"))
    with pytest.raises(ValueError):
        registry.register("not-a-spec")


def test_deterministic_output():
    first = default_executor_registry()
    second = default_executor_registry()
    assert first.kinds() == second.kinds()
    assert (first.kinds(), first.executor_ids()
            ) == (second.kinds(), second.executor_ids())


def test_namespace_constant():
    assert EXEC_NAMESPACE == "exec:"


# --- no execution, no side effects ------------------------------------------------------------------

def test_match_causes_nothing():
    registry = default_executor_registry()
    entry = resolve_executor(registry, "system_inventory")
    assert supports_node(entry, ["exec:system_inventory"]) is True
    assert registry.kinds() == ["system_inventory"]


def test_no_execution_attributes():
    import coordinator.app.executor_registry as module
    for name in dir(module):
        if name.startswith("__"):
            continue
        lowered = name.lower()
        for token in ("execute", "dispatch", "assign", "claim", "complete",
                      "run", "approve", "perform"):
            assert token not in lowered, f"registry must not offer {name}"


def test_implementation_has_no_io_tokens():
    source = (Path(__file__).resolve().parent.parent
              / "coordinator" / "app" / "executor_registry.py").read_text(
                  encoding="utf-8")
    for token in ("subprocess", "os.system", "shell", "socket", "httpx",
                  "requests", "torch", "transformers", "ollama", "GPIO",
                  "serial", "driver", "inference", "download",
                  "filesystem execution", "threading", "asyncio", "pathlib",
                  "shutil", "open("):
        assert token not in source, f"registry must not use {token}"
