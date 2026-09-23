"""Central model router: one owner for normal model defaults.

Decision/config layer ONLY. Deterministic, no I/O, no HTTP calls,
no model execution, no task creation, no agents, no approvals, no
fallback loops. Callers ask for a task class and get a provider/model
resolution back; everything else (env overrides, availability,
execution) stays exactly where it already lives.

Boundaries (deliberate, tested):
- The router owns canonical default VALUES. The existing
  explicit-arg > env-var > default precedence chains in
  ollama_advisor / vision_provider / embeddings are untouched;
  they now fall back to the router-owned value.
- The code_worker -m pin is an explicit safety override. The
  worker never calls this router; the router only REPORTS the
  pinned value (imported from the worker, single source) so
  planners can see where code work routes without duplicating it.
- Tool-dependent execution never auto-routes to a local model:
  PROVEN_LOCAL_TOOL_MODELS is empty because no local model has
  proven native tool-calling through the full OpenCode request
  shape. An explicit operator model is passed through as an
  override, never validated as capable.
"""

from dataclasses import dataclass

TASK_CLASSES = frozenset({
    "chat",
    "research",
    "summarization",
    "vision",
    "embeddings",
    "code",
    "code-review",
    "tool_execution",
})

TEXT_TASK_CLASSES = frozenset({
    "chat",
    "research",
    "summarization",
})

CODE_TASK_CLASSES = frozenset({
    "code",
    "code-review",
})

# Canonical normal defaults. Single source; the provider modules
# fall back to these exact values (env/explicit-arg precedence above
# them is unchanged).
DEFAULT_LOCAL_MODEL = "qwen3.5:4b"
DEFAULT_VISION_MODEL = "qwen3-vl:4b"
DEFAULT_EMBED_MODEL = "nomic-embed-text"

# Local models with PROVEN native tool-calling through the full
# OpenCode request shape. Empty by measurement (qwen2.5-coder:7b and
# phi4-mini both mimic tool calls as text there); entries are only
# ever added with a passing native tool-call proof.
PROVEN_LOCAL_TOOL_MODELS = frozenset()


class ModelRefusedError(ValueError):
    """Unknown task class or unsafe automatic routing; nothing chosen."""


@dataclass(frozen=True)
class ModelRoute:
    task_class: str
    provider: str
    model: str
    local: bool
    operator_override: bool
    reason: str


def code_model_pin() -> str:
    """The worker safety pin, single-sourced from code_worker.
    Lazy import: the worker never imports the coordinator, so no cycle."""
    from code_worker.main import DEFAULT_OPENCODE_MODEL
    return str(DEFAULT_OPENCODE_MODEL)


def _explicit_route(task_class: str, explicit: str) -> ModelRoute:
    cleaned = str(explicit or "").strip()
    if not cleaned or "/" not in cleaned:
        raise ModelRefusedError(
            "explicit model must look like provider/name")
    provider, name = cleaned.split("/", 1)
    if not provider.strip() or not name.strip():
        raise ModelRefusedError(
            "explicit model must look like provider/name")
    return ModelRoute(
        task_class=task_class,
        provider=provider.strip(),
        model=name.strip(),
        local=provider.strip() == "ollama-local",
        operator_override=True,
        reason="explicit operator model; capability not verified")


def resolve_model(task_class: str,
                  explicit_model: str | None = None) -> ModelRoute:
    """Resolve provider/model for one task class. Pure function."""
    cleaned = str(task_class or "").strip()
    if cleaned not in TASK_CLASSES:
        raise ModelRefusedError(
            f"unknown task class {cleaned!r}; refusing")
    if cleaned == "tool_execution":
        if explicit_model is None:
            raise ModelRefusedError(
                "tool-dependent execution never auto-routes: no "
                "local model has proven native tool-calling; pass "
                "an explicit operator model")
        return _explicit_route(cleaned, explicit_model)
    if cleaned in CODE_TASK_CLASSES:
        pin = code_model_pin()
        provider, name = pin.split("/", 1)
        return ModelRoute(
            task_class=cleaned, provider=provider, model=name,
            local=False, operator_override=True,
            reason="code_worker safety pin; router reports, "
                   "never replaces")
    if cleaned == "vision":
        return ModelRoute(
            task_class=cleaned, provider="ollama",
            model=DEFAULT_VISION_MODEL, local=True,
            operator_override=False,
            reason="local VLM default; provider reports "
                   "UNAVAILABLE when absent")
    if cleaned == "embeddings":
        return ModelRoute(
            task_class=cleaned, provider="ollama",
            model=DEFAULT_EMBED_MODEL, local=True,
            operator_override=False,
            reason="local embedding default")
    return ModelRoute(
        task_class=cleaned, provider="ollama",
        model=DEFAULT_LOCAL_MODEL, local=True,
        operator_override=False,
        reason="local text default (chat/research/summarization)")
