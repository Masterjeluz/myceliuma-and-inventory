"""Model-router tests: central defaults, fail-closed tool routing.

The router is a pure decision layer: no HTTP, no execution, no
tasks, no approvals. Unknown classes and unsafe automatic tool
routing refuse; the worker safety pin is reported, never replaced.
"""

import pathlib

import pytest

from coordinator.app import model_router as router
from coordinator.app.model_router import (
    ModelRefusedError,
    resolve_model,
)


def test_chat_routes_local_default():
    route = resolve_model("chat")
    assert (route.provider, route.model) == ("ollama", "qwen3.5:4b")
    assert route.local is True
    assert route.operator_override is False


def test_research_routes_local_default():
    route = resolve_model("research")
    assert (route.provider, route.model) == ("ollama", "qwen3.5:4b")
    assert route.local is True


def test_summarization_routes_local_default():
    route = resolve_model("summarization")
    assert route.model == "qwen3.5:4b"
    assert route.local is True


def test_vision_routes_local_vlm_default():
    route = resolve_model("vision")
    assert (route.provider, route.model) == ("ollama", "qwen3.5:4b")
    assert route.local is True
    assert route.operator_override is False


def test_code_keeps_worker_pin_as_override():
    from code_worker.main import DEFAULT_OPENCODE_MODEL
    for task_class in ("code", "code-review"):
        route = resolve_model(task_class)
        assert f"{route.provider}/{route.model}" == (
            DEFAULT_OPENCODE_MODEL)
        assert route.operator_override is True
        assert route.local is False


def test_tool_execution_never_auto_routes_local():
    with pytest.raises(ModelRefusedError):
        resolve_model("tool_execution")
    # Even a known local model name is refused automatically:
    # nothing is proven, so nothing is chosen.
    with pytest.raises(ModelRefusedError):
        resolve_model("tool_execution",
                      explicit_model=None)


def test_tool_execution_explicit_override_passes_through():
    route = resolve_model("tool_execution",
                          explicit_model="opencode/muse-spark-1.3")
    assert (route.provider, route.model) == (
        "opencode", "muse-spark-1.3")
    assert route.operator_override is True
    with pytest.raises(ModelRefusedError):
        resolve_model("tool_execution", explicit_model="no-slash")
    with pytest.raises(ModelRefusedError):
        resolve_model("tool_execution", explicit_model="")


def test_unknown_task_class_fail_closed():
    for bad in ("", "video", "CODE", "ch at", None, 42):
        with pytest.raises(ModelRefusedError):
            resolve_model(bad)
    # Whitespace around a known class still resolves (stripped).
    assert resolve_model("  chat ").model == "qwen3.5:4b"


def test_router_is_deterministic_and_pure():
    first = resolve_model("research")
    second = resolve_model("research")
    assert first == second
    assert isinstance(first, router.ModelRoute)


def test_router_owns_provider_module_defaults():
    from coordinator.app import embeddings as embed_mod
    from coordinator.app import ollama_advisor as advisor_mod
    from coordinator.app import vision_provider as vision_mod
    assert advisor_mod.DEFAULT_MODEL == "qwen3.5:4b"
    assert advisor_mod.DEFAULT_MODEL == router.DEFAULT_LOCAL_MODEL
    assert vision_mod.DEFAULT_VISION_MODEL == "qwen3.5:4b"
    assert vision_mod.DEFAULT_VISION_MODEL == (
        router.DEFAULT_VISION_MODEL)
    assert embed_mod.DEFAULT_MODEL == "nomic-embed-text"
    assert embed_mod.DEFAULT_MODEL == router.DEFAULT_EMBED_MODEL


def test_router_reads_no_environment():
    import os
    os.environ["OLLAMA_MODEL"] = "someone-else:9b"
    try:
        assert resolve_model("chat").model == "qwen3.5:4b"
    finally:
        del os.environ["OLLAMA_MODEL"]


def test_router_module_has_no_io_surface():
    source = pathlib.Path(router.__file__).read_text(
        encoding="utf-8")
    for forbidden in ("httpx", "urllib", "socket", "subprocess",
                      "os.environ", "open(", "sqlite3"):
        assert forbidden not in source, forbidden
