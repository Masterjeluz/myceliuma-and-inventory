"""Living automation (BIG #38): safe continuity across the workshop.

Observe → research → propose → wait-for-YES → act inside an
approved plan → observe → verify → record. Mycelium keeps
going where work is already safe and approved, and stops
exactly where human authority begins.

This module adds NO new execution power and NO second
mission engine:

- Runs are records (chat DB, ``automation_runs`` table):
  goal, ordered bounded steps, bounds, state, waiting
  bundle, provenance. Steps execute only through existing
  functions (research engine, knowledge, missions executor,
  camera, workshop, conversation intel, packets, notify).
- Step kinds come from a closed allow-list; anything else
  refuses at creation AND at drive time (default-deny).
- Consequential work is PREPARED (draft mission, inert
  proposal) and then the run WAITS with the exact gate
  named. Resume re-reads live store state — approvals are
  never fabricated, never inferred, never reused stale.
- Bounds on every run (steps, runtime, retries,
  consecutive failures). Fail-closed with exact reasons.
- No background threads: drive/resume are explicit calls
  from API buttons only.

Decision vocabulary comes from decisions.py
(CONTINUE/RETRY/REPLAN/WAITING_FOR_HUMAN/WAITING_FOR_AGENT/
BLOCKED/FAILED/COMPLETED/CANCELLED). Bus events use the
existing automation.* types. Notifications reuse existing
notify_center kinds.
"""

from __future__ import annotations

import secrets
import time

from pydantic import BaseModel, ConfigDict, Field

from .inventory_read import Provenance

#: Closed set of step kinds automation may execute. Anything
#: else refuses at creation and at drive time. Read-only and
#: candidate-tier work runs freely; preparation steps create
#: inert drafts/proposals and then WAIT for the human gate.
SAFE_STEP_KINDS = frozenset({
    "observe",
    "readout",
    "search",
    "research_queue",
    "research_execute",
    "conversation_analyze",
    "intel_analyze",
    "knowledge_candidate",
    "symbiosis_propose",
    "craft_update",
    "context_packet",
    "notify",
    "mission_tick",
    "mission_propose",
    "write_propose",
    "fab_prepare",
    "node_prepare",
    "camera_session",
    "wait",
})

#: Steps allowed while an overnight run is armed. Strictly
#: read-only research/analysis/candidate/proposal/notify
#: work. Mission ticks, proposals, fabrication prep and
#: camera ingest stay out: the night shift observes and
#: prepares, it never advances executable state.
OVERNIGHT_SAFE_KINDS = frozenset({
    "observe",
    "readout",
    "search",
    "research_queue",
    "research_execute",
    "conversation_analyze",
    "intel_analyze",
    "knowledge_candidate",
    "symbiosis_propose",
    "craft_update",
    "context_packet",
    "notify",
    "wait",
})

#: Closed gate types a step may wait on. Resume re-checks
#: the live store named here — never a cached verdict.
GATE_TYPES = frozenset({
    "mission_approved",
    "write_approved",
    "desktop_decided",
    "candidate_advanced",
    "research_completed",
    "time_elapsed",
})

RUN_STATES = (
    "running",
    "waiting_for_human",
    "waiting_for_agent",
    "blocked",
    "failed",
    "completed",
    "cancelled",
)

STEP_STATES = (
    "pending",
    "running",
    "done",
    "waiting",
    "failed",
    "skipped",
)

MAX_STEPS = 20
MAX_RUNTIME_SECONDS = 3600
MAX_RETRIES = 5
MAX_CONSECUTIVE_FAILURES = 5

_SECRET_HINTS = ("token", "secret", "password", "passwd",
                 "api_key", "apikey", "bearer", "credential",
                 "private_key", "client_secret")


class AutomationRefusedError(ValueError):
    """Automation validation refused; nothing was stored or driven."""


class AutomationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=3, max_length=80)
    kind: str = Field(min_length=1, max_length=40)
    params: dict = Field(default_factory=dict)
    gate: dict = Field(default_factory=dict)
    status: str = Field(default="pending", max_length=20)
    attempts: int = Field(default=0, ge=0)
    result: dict = Field(default_factory=dict)
    error: str = Field(default="", max_length=1000)


class AutomationRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=3, max_length=80)
    goal: str = Field(min_length=1, max_length=500)
    mission_id: str = Field(default="", max_length=80)
    template_id: str = Field(default="", max_length=80)
    steps: list[AutomationStep] = Field(default_factory=list,
                                        max_length=MAX_STEPS)
    bounds: dict = Field(default_factory=dict)
    state: str = Field(default="running", max_length=30)
    waiting: dict = Field(default_factory=dict)
    overnight: bool = False
    provenance: Provenance = Field(default_factory=Provenance)
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def generate_run_id() -> str:
    return f"auto_{secrets.token_hex(6)}"


def init_automation_tables() -> None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS automation_runs (
            run_id TEXT PRIMARY KEY,
            record TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_automation_status
            ON automation_runs(status, updated_at);
        """)


def _default_bounds() -> dict:
    return {"max_steps": MAX_STEPS,
            "max_runtime_seconds": 600,
            "max_retries": 2,
            "max_consecutive_failures": 3}


def check_bounds(raw: dict | None) -> dict:
    """Validate run bounds. Fail-closed on nonsense."""
    bounds = _default_bounds()
    if raw is None:
        return bounds
    if not isinstance(raw, dict):
        raise AutomationRefusedError("bounds must be an object")
    try:
        max_steps = int(raw.get("max_steps", bounds["max_steps"]))
        max_runtime = int(raw.get("max_runtime_seconds",
                                  bounds["max_runtime_seconds"]))
        max_retries = int(raw.get("max_retries",
                                  bounds["max_retries"]))
        max_failures = int(raw.get("max_consecutive_failures",
                                   bounds["max_consecutive_failures"]))
    except (TypeError, ValueError):
        raise AutomationRefusedError("bounds must be integers")
    if not 1 <= max_steps <= MAX_STEPS:
        raise AutomationRefusedError(
            f"max_steps must be 1..{MAX_STEPS}")
    if not 1 <= max_runtime <= MAX_RUNTIME_SECONDS:
        raise AutomationRefusedError(
            f"max_runtime_seconds must be 1..{MAX_RUNTIME_SECONDS}")
    if not 0 <= max_retries <= MAX_RETRIES:
        raise AutomationRefusedError(
            f"max_retries must be 0..{MAX_RETRIES}")
    if not 1 <= max_failures <= MAX_CONSECUTIVE_FAILURES:
        raise AutomationRefusedError(
            "max_consecutive_failures must be "
            f"1..{MAX_CONSECUTIVE_FAILURES}")
    return {"max_steps": max_steps,
            "max_runtime_seconds": max_runtime,
            "max_retries": max_retries,
            "max_consecutive_failures": max_failures}


def check_gate(raw: dict | None) -> dict:
    """Validate a step gate. Empty gate means 'no gate'."""
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise AutomationRefusedError("gate must be an object")
    kind = str(raw.get("type", "")).strip()[:40]
    if kind not in GATE_TYPES:
        raise AutomationRefusedError(
            f"Unknown gate type '{kind}'; expected one of "
            f"{sorted(GATE_TYPES)}")
    ref = str(raw.get("ref", "")).strip()[:120]
    if kind != "time_elapsed" and not ref:
        raise AutomationRefusedError(
            f"Gate '{kind}' needs a ref id")
    gate = {"type": kind, "ref": ref}
    if kind == "time_elapsed":
        gate["until"] = str(raw.get("until", ""))[:40]
    if kind == "write_approved":
        gate["fingerprint"] = str(raw.get("fingerprint", ""))[:128]
    return gate


def check_step(raw: dict, index: int) -> AutomationStep:
    """Validate one step definition. Closed kinds, bounded params."""
    if not isinstance(raw, dict):
        raise AutomationRefusedError(
            f"Step {index} must be an object")
    kind = str(raw.get("kind", "")).strip()[:40]
    if kind not in SAFE_STEP_KINDS:
        raise AutomationRefusedError(
            f"Step {index} kind '{kind}' is not automatable; "
            f"expected one of {sorted(SAFE_STEP_KINDS)}")
    params = raw.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise AutomationRefusedError(
            f"Step {index} params must be an object")
    if len(params) > 12:
        raise AutomationRefusedError(
            f"Step {index} carries too many params (≤12)")
    cleaned: dict = {}
    for key, value in params.items():
        name = str(key or "")[:40]
        try:
            cleaned[name] = _clean_param(value, depth=0)
        except AutomationRefusedError as error:
            raise AutomationRefusedError(
                f"Step {index} param '{name}': {error}") from error
    # Secret scans apply to machine-bound payloads only
    # (write_propose payloads, node_prepare payloads — checked
    # by their own validators at drive time). Free-text fields
    # (goals, questions, candidate text) may legitimately
    # mention words like "password" when researching them.
    _validate_params(kind, cleaned, index)
    return AutomationStep(
        step_id=f"astep_{index:02d}",
        kind=kind, params=cleaned,
        gate=check_gate(raw.get("gate")))


def _validate_params(kind: str, params: dict, index: int) -> None:
    """Fail-fast static checks at creation time. Executors
    re-check everything at drive time (defense in depth);
    registry-dependent checks (nodes exist, files exist)
    happen at drive time only, since stores change."""
    get = params.get
    if kind == "node_prepare":
        from .nodemesh import (ALLOWED_CAPABILITY_PREFIXES,
                               ALLOWED_TASK_KINDS)
        task_kind = str(get("task_kind", "")).strip()[:80]
        capability = str(get("capability", "")).strip()
        if task_kind not in ALLOWED_TASK_KINDS:
            raise AutomationRefusedError(
                f"Step {index}: task kind not delegable")
        if not capability or capability == "*" or \
                "*" in capability or len(capability) > 120:
            raise AutomationRefusedError(
                f"Step {index}: wildcard/oversized capability "
                "refused")
        if not capability.startswith(ALLOWED_CAPABILITY_PREFIXES):
            raise AutomationRefusedError(
                f"Step {index}: capability not delegable")
    elif kind == "craft_update":
        from .symbiosis import clean_entity
        try:
            clean_entity(get("entity_id", ""))
        except ValueError as error:
            raise AutomationRefusedError(
                f"Step {index}: {error}") from error
    elif kind == "symbiosis_propose":
        from .camera_ecosystem import LINK_PREDICATES
        from .symbiosis import clean_entity
        if str(get("predicate", "")).strip()[:40] not in \
                LINK_PREDICATES:
            raise AutomationRefusedError(
                f"Step {index}: predicate not in the closed set")
        for field in ("from_id", "to_id"):
            try:
                clean_entity(get(field, ""))
            except ValueError as error:
                raise AutomationRefusedError(
                    f"Step {index}: {error}") from error
        if str(get("from_id", "")).strip() == \
                str(get("to_id", "")).strip():
            raise AutomationRefusedError(
                f"Step {index}: symbiosis needs two entities")
    elif kind == "mission_tick":
        mid = str(get("mission_id", "")).strip()
        if mid and not mid.startswith("mission_"):
            raise AutomationRefusedError(
                f"Step {index}: mission_tick needs a mission_id; "
                "empty resolves at drive time from a draft "
                "proposed earlier in the run")
    elif kind == "mission_propose":
        if not str(get("goal", "")).strip():
            raise AutomationRefusedError(
                f"Step {index}: mission_propose needs a goal")
    elif kind == "write_propose":
        from .controlled_writes import VALID_MUTATION_TYPES
        if str(get("mutation_type", "")).strip()[:40] not in \
                VALID_MUTATION_TYPES:
            raise AutomationRefusedError(
                f"Step {index}: unknown mutation type")
        if not str(get("target", "")).strip():
            raise AutomationRefusedError(
                f"Step {index}: write_propose needs a target")
        payload = get("payload", {}) or {}
        if not isinstance(payload, dict) or len(payload) > 12:
            raise AutomationRefusedError(
                f"Step {index}: payload must be a small object")
        lowered = _json_dump(payload).lower()
        for hint in _SECRET_HINTS:
            if hint in lowered:
                raise AutomationRefusedError(
                    f"Step {index}: payload must not carry secrets")
    elif kind == "knowledge_candidate":
        from .knowledge import CANDIDATE_TYPES
        if str(get("kind", "note")).strip()[:40] not in \
                CANDIDATE_TYPES:
            raise AutomationRefusedError(
                f"Step {index}: unknown candidate kind")
        if not str(get("title", "")).strip() or \
                not str(get("text", "")).strip():
            raise AutomationRefusedError(
                f"Step {index}: candidate needs title and text")
    elif kind == "camera_session":
        if str(get("op", "run")).strip()[:20] not in (
                "run", "describe", "propose"):
            raise AutomationRefusedError(
                f"Step {index}: camera op must be run, describe "
                "or propose")
    elif kind == "fab_prepare":
        if str(get("op", "prepare")).strip()[:20] not in (
                "prepare", "slice", "propose"):
            raise AutomationRefusedError(
                f"Step {index}: fab op must be prepare, slice or "
                "propose")
        if not str(get("job_id", "")).strip():
            raise AutomationRefusedError(
                f"Step {index}: fab_prepare needs a job_id")
    elif kind == "research_queue":
        if not str(get("question", "")).strip():
            raise AutomationRefusedError(
                f"Step {index}: research_queue needs a question")
        if str(get("priority", "MEDIUM")).strip().upper() not in (
                "HIGH", "MEDIUM", "LOW"):
            raise AutomationRefusedError(
                f"Step {index}: bad research priority")
    elif kind == "research_execute":
        if not str(get("run_id", "")).strip().startswith("res_"):
            raise AutomationRefusedError(
                f"Step {index}: research_execute needs a run_id")
    elif kind in ("observe", "readout"):
        if str(get("source", "")).strip()[:40] not in (
                "missions", "candidates", "research", "nodes",
                "inbox", "events", "project", "inventory"):
            raise AutomationRefusedError(
                f"Step {index}: unknown observe/readout source")


def _clean_param(value: object, depth: int = 0):
    """Depth-limited recursive cleaning: text/number/bool, short
    lists and shallow objects only. Anything else refuses.
    Depth 3 covers mission-step params
    (steps → step → parameters → value)."""
    if depth > 3:
        raise AutomationRefusedError("nesting too deep (≤3)")
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, list):
        return [_clean_param(item, depth + 1)
                for item in value[:10]]
    if isinstance(value, dict):
        cleaned: dict = {}
        for item_key, item_value in list(value.items())[:12]:
            cleaned[str(item_key or "")[:40]] = _clean_param(
                item_value, depth + 1)
        return cleaned
    raise AutomationRefusedError(
        "unsupported type (text/number/bool/short list/"
        "shallow object only)")


def _json_dump(value: object) -> str:
    import json as _json
    try:
        return _json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)


def _bus(event_type: str, summary: str, *,
         mission_id: str = "") -> None:
    try:
        from .events import new_event as _new
        from .events import save_event as _save
        _save(_new(event_type, summary[:500],
                   mission_id=mission_id[:80]))
    except Exception:
        pass


def _notify_nodes(kind: str, title: str, body: str = "",
                  related_entity: str = "",
                  related_mission: str = "") -> None:
    """Best-effort IN_APP fan-out. Failure never breaks a run."""
    try:
        from . import main as _main
        from .notify_center import send as _send
        nodes = _main.list_nodes()[:10]
    except Exception:
        return
    for row in nodes:
        node_id = str(row.get("node_id", ""))
        if not node_id:
            continue
        try:
            _send(node_id, kind, title[:200], body[:1000],
                  related_entity=related_entity[:100],
                  related_mission=related_mission[:80])
        except Exception:
            continue


def save_run(run: AutomationRun) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_automation_tables()
    init_chat_database()
    with chat_connection() as db:
        db.execute(
            """INSERT INTO automation_runs
            (run_id, record, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
            record=excluded.record, status=excluded.status,
            updated_at=excluded.updated_at""",
            (run.run_id, dump(run.model_dump(mode="json")),
             run.state, run.created_at or _now(), _now()))


def load_run(run_id: str) -> AutomationRun | None:
    from .database import chat_connection, init_chat_database, load
    init_automation_tables()
    init_chat_database()
    cleaned = str(run_id or "").strip()[:80]
    with chat_connection() as db:
        row = db.execute("SELECT record FROM automation_runs "
                         "WHERE run_id=?", (cleaned,)).fetchone()
    if row is None:
        return None
    return AutomationRun.model_validate(load(row["record"]))


def list_runs(limit: int = 50, state: str = "") -> list[AutomationRun]:
    from .database import chat_connection, init_chat_database, load
    init_automation_tables()
    init_chat_database()
    count = max(1, min(int(limit or 50), 200))
    with chat_connection() as db:
        if state:
            rows = db.execute(
                "SELECT record FROM automation_runs WHERE status=? "
                "ORDER BY updated_at DESC LIMIT ?",
                (str(state)[:30], count)).fetchall()
        else:
            rows = db.execute(
                "SELECT record FROM automation_runs ORDER BY "
                "updated_at DESC LIMIT ?", (count,)).fetchall()
    return [AutomationRun.model_validate(load(row["record"]))
            for row in rows]


def create_run(goal: str, steps: list[dict], *,
               mission_id: str = "",
               template_id: str = "",
               bounds: dict | None = None,
               overnight: bool = False,
               actor: str = "web") -> AutomationRun:
    """Create a run. Validates every step; stores nothing executable."""
    cleaned_goal = str(goal or "").strip()
    if not cleaned_goal:
        raise AutomationRefusedError("automation needs a goal")
    if not isinstance(steps, list) or not steps:
        raise AutomationRefusedError(
            "automation needs 1..20 steps")
    if len(steps) > MAX_STEPS:
        raise AutomationRefusedError(
            f"automation takes at most {MAX_STEPS} steps")
    cleaned_mission = str(mission_id or "").strip()[:80]
    if cleaned_mission:
        from .missions import load_mission
        try:
            mission = load_mission(cleaned_mission)
        except ValueError as error:
            raise AutomationRefusedError(str(error)) from error
        if mission is None:
            raise AutomationRefusedError("mission not found")
    checked = [check_step(raw, index)
               for index, raw in enumerate(steps)]
    if overnight:
        unsafe = [step.kind for step in checked
                  if step.kind not in OVERNIGHT_SAFE_KINDS]
        if unsafe:
            raise AutomationRefusedError(
                "overnight runs allow read-only work only; "
                f"refused kinds: {sorted(set(unsafe))}")
    stamp = _now()
    run = AutomationRun(
        run_id=generate_run_id(), goal=cleaned_goal[:500],
        mission_id=cleaned_mission,
        template_id=str(template_id or "")[:80],
        steps=checked, bounds=check_bounds(bounds),
        state="running", overnight=bool(overnight),
        provenance=Provenance(
            source_type="user-created",
            creator_id=str(actor or "web")[:80],
            human_verified=False,
            notes="automation run; explicit drive calls only, "
                  "no background execution"),
        created_at=stamp, started_at=stamp)
    save_run(run)
    _bus("automation.started",
         f"Automation {run.run_id} opened: {run.goal[:120]}",
         mission_id=run.mission_id)
    _notify_nodes(
        "mission_waiting", f"Automation started: {run.goal[:100]}",
        f"Run {run.run_id} with {len(checked)} safe step(s). "
        "It stops at the first human gate.",
        related_mission=run.mission_id)
    return run


def cancel_run(run_id: str, *, reason: str = "") -> AutomationRun:
    run = load_run(run_id)
    if run is None:
        raise AutomationRefusedError("automation run not found")
    if run.state in ("completed", "failed", "cancelled"):
        raise AutomationRefusedError(
            f"run is {run.state}; terminal runs stay put")
    run.state = "cancelled"
    run.completed_at = _now()
    save_run(run)
    _bus("automation.failed",
         f"Automation {run.run_id} cancelled: "
         f"{reason[:200] or 'operator stop'}",
         mission_id=run.mission_id)
    return run


def overnight_eligible(run_id: str) -> dict:
    """Could this run arm for overnight? Read-only answer."""
    run = load_run(run_id)
    if run is None:
        raise AutomationRefusedError("automation run not found")
    unsafe = sorted({step.kind for step in run.steps
                     if step.kind not in OVERNIGHT_SAFE_KINDS})
    return {"run_id": run.run_id, "eligible": not unsafe,
            "unsafe_kinds": unsafe,
            "honesty": "Eligible means read-only steps only. "
                       "Arming still needs an explicit call; "
                       "nothing self-starts at night."}


def run_to_json(run: AutomationRun) -> dict:
    data = run.model_dump(mode="json")
    data["steps_done"] = sum(
        1 for step in run.steps if step.status == "done")
    data["steps_total"] = len(run.steps)
    return data


# -- gates: re-read live stores, never cached verdicts ------------------------

def check_gate_live(gate: dict) -> dict:
    """Evaluate one gate against current store state.

    Returns {"met": bool, "detail": str, "approval_url": str}.
    A met gate means the human decision observably happened;
    anything else keeps the run waiting. Never raises for
    missing records — missing means unmet.
    """
    kind = str((gate or {}).get("type", ""))
    ref = str((gate or {}).get("ref", ""))
    if kind not in GATE_TYPES:
        return {"met": False, "detail": "unknown gate type",
                "approval_url": ""}
    try:
        if kind == "mission_approved":
            from .missions import load_mission
            mission = load_mission(ref)
            if mission is None:
                return {"met": False,
                        "detail": "mission not found",
                        "approval_url": f"/missions/{ref}"}
            if mission.status in ("approved", "running"):
                return {"met": True,
                        "detail": f"mission {mission.status} "
                                  f"by {mission.approved_by or '?'}",
                        "approval_url": f"/missions/{ref}"}
            return {"met": False,
                    "detail": f"mission is {mission.status}; "
                              "plan YES still required",
                    "approval_url": f"/missions/{ref}"}
        if kind == "write_approved":
            from . import main as _main
            record = _main._write_load(ref)
            if not record:
                return {"met": False,
                        "detail": "proposal not found",
                        "approval_url": "/writes"}
            status = str(record.get("status", ""))
            approval = record.get("approval") or {}
            decided_by = str(approval.get("decided_by", ""))
            # Any recorded decision counts: automation itself can
            # never write one (no approval path exists in this
            # module), so an approved status always came through
            # the real human flow. Automation-tagged deciders
            # are still refused, belt and braces.
            if status == "approved" and decided_by and \
                    not decided_by.startswith("automation:"):
                return {"met": True,
                        "detail": f"proposal approved by "
                                  f"{decided_by}; execution stays "
                                  "a separate step",
                        "approval_url": "/writes"}
            return {"met": False,
                    "detail": f"proposal is {status}; exact YES "
                              "still required",
                    "approval_url": "/writes"}
        if kind == "desktop_decided":
            from . import main as _main
            try:
                record = _main._desktop_load(ref)
            except Exception:
                return {"met": False,
                        "detail": "desktop action not found",
                        "approval_url": "/agents"}
            status = str(getattr(record, "status", ""))
            decided_by = str(getattr(record, "decided_by", ""))
            if status in ("approved", "completed") and decided_by:
                return {"met": True,
                        "detail": f"action {status} by {decided_by}",
                        "approval_url": "/agents"}
            return {"met": False,
                    "detail": f"action is {status}; exact YES "
                              "still required",
                    "approval_url": "/agents"}
        if kind == "candidate_advanced":
            from .knowledge import get_candidate
            entry = get_candidate(ref)
            if entry is None:
                return {"met": False,
                        "detail": "candidate not found",
                        "approval_url": "/knowledge"}
            if entry.state in ("supported", "promoted"):
                return {"met": True,
                        "detail": f"candidate {entry.state}",
                        "approval_url": "/knowledge"}
            return {"met": False,
                    "detail": f"candidate is {entry.state}; "
                              "support or promote still required",
                    "approval_url": "/knowledge"}
        if kind == "research_completed":
            from .research_engine import dossier_for_run, load_run
            run = load_run(ref)
            if run is None:
                return {"met": False,
                        "detail": "research run not found",
                        "approval_url": "/research"}
            dossier = dossier_for_run(ref)
            if dossier is not None or run.status == "completed":
                return {"met": True,
                        "detail": "research has a dossier",
                        "approval_url": "/research"}
            return {"met": False,
                    "detail": f"research is {run.status}",
                    "approval_url": "/research"}
        if kind == "time_elapsed":
            until = str((gate or {}).get("until", ""))
            from datetime import datetime, timezone
            try:
                moment = datetime.fromisoformat(until)
            except (ValueError, TypeError):
                return {"met": False,
                        "detail": "unreadable wait timestamp",
                        "approval_url": ""}
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= moment:
                return {"met": True,
                        "detail": "wait time elapsed",
                        "approval_url": ""}
            return {"met": False,
                    "detail": f"waiting until {until[:19]}",
                    "approval_url": ""}
    except Exception as error:
        return {"met": False,
                "detail": f"gate check failed safely: {error}"[:200],
                "approval_url": ""}
    return {"met": False, "detail": "gate unmet", "approval_url": ""}


# -- step executors (existing functions only) ----------------------------------

async def _execute_step(run: AutomationRun,
                        step: AutomationStep) -> dict:
    """Run one safe step. Returns a result dict. Raises on failure.
    Re-validates kind (default-deny) even though creation did."""
    kind = str(step.kind or "")
    if kind not in SAFE_STEP_KINDS:
        raise AutomationRefusedError(
            f"Step kind '{kind}' is not automatable")
    params = dict(step.params or {})
    if kind == "observe":
        return _exec_observe(params)
    if kind == "readout":
        return _exec_readout(params)
    if kind == "search":
        return await _exec_search(params)
    if kind == "research_queue":
        return _exec_research_queue(params, run)
    if kind == "research_execute":
        return await _exec_research_execute(params)
    if kind == "conversation_analyze":
        return _exec_conversation_analyze(params)
    if kind == "intel_analyze":
        return _exec_intel_analyze(params)
    if kind == "knowledge_candidate":
        return _exec_knowledge_candidate(params, run)
    if kind == "symbiosis_propose":
        return _exec_symbiosis_propose(params, run)
    if kind == "craft_update":
        return await _exec_craft_update(params)
    if kind == "context_packet":
        return _exec_context_packet(params)
    if kind == "notify":
        return _exec_notify(params, run)
    if kind == "mission_tick":
        return await _exec_mission_tick(params)
    if kind == "mission_propose":
        return _exec_mission_propose(params, run)
    if kind == "write_propose":
        return _exec_write_propose(params, run)
    if kind == "fab_prepare":
        return _exec_fab_prepare(params)
    if kind == "node_prepare":
        return _exec_node_prepare(params)
    if kind == "camera_session":
        return _exec_camera_session(params)
    if kind == "wait":
        gate = dict(step.gate or {})
        if gate:
            verdict = check_gate_live(gate)
            if verdict["met"]:
                return {"waited": True,
                        "gate": gate.get("type", ""),
                        "detail": verdict["detail"][:200]}
        raise _WaitGate(str(params.get("reason", "explicit wait")),
                        gate=gate)
    raise AutomationRefusedError(f"Unhandled step kind '{kind}'")


class _WaitGate(Exception):
    """A step explicitly waits. Carries the gate to re-check."""

    def __init__(self, reason: str, gate: dict | None = None):
        super().__init__(reason)
        self.gate = gate or {}


def _exec_observe(params: dict) -> dict:
    source = str(params.get("source", "")).strip()[:40]
    if source not in ("missions", "candidates", "research",
                      "nodes", "inbox", "events"):
        raise AutomationRefusedError(
            "observe source must be missions, candidates, "
            "research, nodes, inbox or events")
    if source == "missions":
        from .missions import list_missions
        items = list_missions(limit=20)
        return {"observed": len(items),
                "items": [f"{m.goal[:80]} [{m.status}]"
                          for m in items[:10]]}
    if source == "candidates":
        from .knowledge import list_candidates
        items = list_candidates(limit=50)
        return {"observed": len(items),
                "items": [f"{c.title[:80]} [{c.state}]"
                          for c in items[:10]]}
    if source == "research":
        from .research_engine import list_runs
        items = list_runs(limit=20)
        return {"observed": len(items),
                "items": [f"{r.question[:80]} [{r.status}]"
                          for r in items[:10]]}
    if source == "nodes":
        from . import main as _main
        rows = _main.list_nodes()
        return {"observed": len(rows),
                "items": [f"{r.get('node_id')} "
                          f"[{r.get('derived_status')}]"
                          for r in rows[:10]]}
    if source == "inbox":
        from .vision_ingest import list_inbox_files
        items = list_inbox_files(limit=20)
        return {"observed": len(items),
                "items": [str(i.get("filename", ""))[:80]
                          for i in items[:10]]}
    from .events import list_events
    items = list_events(limit=20)
    return {"observed": len(items),
            "items": [f"{e.event_type}: {e.summary[:80]}"
                      for e in items[:10]]}


def _exec_readout(params: dict) -> dict:
    source = str(params.get("source", "")).strip()[:40]
    if source == "project":
        from .project_context import default_context
        context = default_context()
        return {"source": "project",
                "summary": f"{context.name} "
                           f"({context.project_id})"[:200]}
    if source == "inventory":
        query = str(params.get("q", "")).strip()[:200]
        if not query:
            raise AutomationRefusedError(
                "inventory readout needs q")
        from . import main as _main
        import anyio as _anyio

        async def _browse() -> dict:
            reader = _main._world_reader()
            found = await reader.search(query)
            results = found.results or []
            return {"source": "inventory", "query": query,
                    "matches": len(results),
                    "items": [str(r.entity_id) for r in results[:10]]}

        try:
            return _anyio.run(_browse)
        except Exception as error:
            raise AutomationRefusedError(
                f"inventory readout failed safely: {error}"[:200])
    raise AutomationRefusedError(
        "readout source must be project or inventory")


async def _exec_search(params: dict) -> dict:
    query = str(params.get("q", "")).strip()[:200]
    if not query:
        raise AutomationRefusedError("search needs q")
    from . import main as _main
    try:
        reader = _main._world_reader()
        found = await reader.search(query)
        results = found.results or []
    except Exception as error:
        raise AutomationRefusedError(
            f"search failed safely: {error}"[:200])
    return {"query": query, "matches": len(results),
            "items": [str(r.entity_id) for r in results[:10]]}


def _exec_research_queue(params: dict, run: AutomationRun) -> dict:
    from .research_engine import EngineRefusedError, new_run, save_run
    question = str(params.get("question", "")).strip()
    if not question:
        raise AutomationRefusedError(
            "research_queue needs a question")
    priority = str(params.get("priority", "MEDIUM")).strip().upper()
    if priority not in ("HIGH", "MEDIUM", "LOW"):
        raise AutomationRefusedError(
            "priority must be HIGH, MEDIUM or LOW")
    try:
        record = new_run(
            question[:500],
            objective=str(params.get("objective", ""))[:500],
            project_ref=str(params.get("project_ref", ""))[:100],
            mission_id=run.mission_id,
            requested_by=f"automation:{run.run_id}",
            metadata={"priority": priority,
                      "provider": "wikipedia",
                      "max_sources": max(1, min(int(params.get(
                          "max_sources", 6)), 10)),
                      "route": "local"})
        save_run(record)
    except (ValueError, TypeError) as error:
        raise AutomationRefusedError(str(error)) from error
    _bus("research.queued",
         f"Automation {run.run_id} queued {record.run_id}: "
         f"{question[:120]}", mission_id=run.mission_id)
    return {"run_id": record.run_id, "status": record.status}


async def _exec_research_execute(params: dict) -> dict:
    from . import main as _main
    run_id = str(params.get("run_id", "")).strip()[:80]
    if not run_id:
        raise AutomationRefusedError(
            "research_execute needs a run_id (queue first, "
            "execute explicitly)")
    from .research_engine import load_run
    record = load_run(run_id)
    if record is None:
        raise AutomationRefusedError("research run not found")
    if record.status not in ("draft", "queued"):
        raise AutomationRefusedError(
            f"run is {record.status}; automation only executes "
            "fresh drafts")
    metadata = record.metadata or {}
    try:
        provider = _main._research_provider(
            str(metadata.get("provider", "wikipedia")), None)
    except Exception as error:
        raise AutomationRefusedError(
            f"research provider refused: {error}"[:200])
    try:
        finished = await _main._execute_research_run(
            run_id, provider,
            max(1, min(int(metadata.get("max_sources", 6)), 10)))
    except Exception as error:
        raise AutomationRefusedError(
            f"research execution failed safely: {error}"[:300])
    dossier_id = ""
    try:
        dossier_id = str(finished.get("dossier_id", ""))
    except (AttributeError, TypeError):
        dossier_id = ""
    return {"run_id": run_id, "dossier_id": dossier_id,
            "state": "REAL"}


def _exec_conversation_analyze(params: dict) -> dict:
    from .conversation_bridge import BridgeRefusedError, analyze_import
    conversation_id = str(
        params.get("conversation_id", "")).strip()[:80]
    if not conversation_id:
        raise AutomationRefusedError(
            "conversation_analyze needs a conversation_id")
    try:
        record = analyze_import(conversation_id)
    except (BridgeRefusedError, ValueError) as error:
        raise AutomationRefusedError(str(error)) from error
    findings = record.get("findings", [])
    return {"conversation_id": conversation_id,
            "findings": len(findings)}


def _exec_intel_analyze(params: dict) -> dict:
    from .conversation_intel import IntelRefusedError, analyze_conversation
    conversation_id = str(
        params.get("conversation_id", "")).strip()[:80]
    if not conversation_id:
        raise AutomationRefusedError(
            "intel_analyze needs a conversation_id")
    try:
        record = analyze_conversation(conversation_id)
    except (IntelRefusedError, ValueError) as error:
        raise AutomationRefusedError(str(error)) from error
    counts = record.get("counts", {})
    return {"conversation_id": conversation_id,
            "counts": counts}


def _exec_knowledge_candidate(params: dict,
                              run: AutomationRun) -> dict:
    from .conversation_bridge import _HEALTH_RE as HEALTH_RE
    from .knowledge import (CandidateRefusedError, new_candidate,
                            save_candidate)
    from .inventory_read import Provenance
    title = str(params.get("title", "")).strip()
    kind = str(params.get("kind", "note")).strip()[:40]
    text = str(params.get("text", "")).strip()
    if not title or not text:
        raise AutomationRefusedError(
            "knowledge_candidate needs title and text")
    if HEALTH_RE.search(title) or HEALTH_RE.search(text):
        raise AutomationRefusedError(
            "health-related text never becomes a candidate")
    entity_refs = params.get("entity_refs", []) or []
    if not isinstance(entity_refs, list):
        raise AutomationRefusedError("entity_refs must be a list")
    cleaned_refs: list[str] = []
    if entity_refs:
        from .symbiosis import clean_entity
        for ref in entity_refs[:10]:
            try:
                cleaned_refs.append(clean_entity(ref))
            except ValueError as error:
                raise AutomationRefusedError(
                    f"bad entity ref '{ref}': {error}") from error
    try:
        entry = new_candidate(
            title[:200], kind,
            summary=text[:2000], state="candidate",
            provenance=Provenance(
                source_type="ai-generated",
                creator_id=f"automation:{run.run_id}",
                human_verified=False,
                notes="automation proposal; support/promote "
                      "stay human"),
            evidence=[{"text": text[:500],
                       "source": run.run_id}],
            entity_refs=cleaned_refs,
            project_ref=str(params.get("project_ref", ""))[:100])
        save_candidate(entry)
    except (CandidateRefusedError, ValueError) as error:
        raise AutomationRefusedError(str(error)) from error
    _bus("candidate.observed",
         f"Automation {run.run_id} proposed candidate "
         f"{entry.candidate_id}", mission_id=run.mission_id)
    return {"candidate_id": entry.candidate_id,
            "candidate_type": entry.candidate_type}


def _exec_symbiosis_propose(params: dict,
                            run: AutomationRun) -> dict:
    from .camera_ecosystem import LINK_PREDICATES
    from .inventory_read import Provenance
    from .knowledge import (CandidateRefusedError, new_candidate,
                            save_candidate)
    from .symbiosis import clean_entity
    from_id = str(params.get("from_id", "")).strip()[:100]
    to_id = str(params.get("to_id", "")).strip()[:100]
    predicate = str(params.get("predicate", "")).strip()[:40]
    if predicate not in LINK_PREDICATES:
        raise AutomationRefusedError(
            f"predicate must be one of "
            f"{sorted(LINK_PREDICATES)}")
    try:
        source = clean_entity(from_id)
        target = clean_entity(to_id)
    except ValueError as error:
        raise AutomationRefusedError(str(error)) from error
    if source == target:
        raise AutomationRefusedError(
            "symbiosis needs two different entities")
    try:
        entry = new_candidate(
            f"{source} {predicate} {target}"[:200], "connection",
            summary=f"Automation-proposed relation ({predicate}); "
                    "PROPOSED until a human supports it.",
            state="candidate",
            provenance=Provenance(
                source_type="ai-generated",
                creator_id=f"automation:{run.run_id}",
                human_verified=False,
                notes="symbiosis proposal; never merged silently"),
            entity_refs=[source, target])
        save_candidate(entry)
    except (CandidateRefusedError, ValueError) as error:
        raise AutomationRefusedError(str(error)) from error
    _bus("relation.proposed",
         f"Automation {run.run_id} proposed {source} "
         f"{predicate} {target}", mission_id=run.mission_id)
    return {"candidate_id": entry.candidate_id,
            "predicate": predicate, "state": "PROPOSED"}


async def _exec_craft_update(params: dict) -> dict:
    from .craft import craft_tree
    from .symbiosis import clean_entity
    try:
        entity_id = clean_entity(params.get("entity_id", ""))
    except ValueError as error:
        raise AutomationRefusedError(str(error)) from error
    try:
        tree = await craft_tree(entity_id, depth=1)
    except (ValueError, RuntimeError) as error:
        raise AutomationRefusedError(str(error)) from error
    stages = tree.get("stages", [])
    return {"entity_id": entity_id,
            "stages_present": tree.get("stages_present", 0),
            "stages_total": len(stages),
            "gaps": [gap.get("missing", "?") for gap in
                     tree.get("gaps", [])][:8]}


def _exec_context_packet(params: dict) -> dict:
    from .context_packet import build_packet_v2
    try:
        packet = build_packet_v2(
            task=str(params.get("task", ""))[:500],
            intent=str(params.get("intent", ""))[:200],
            project_id=str(params.get("project_id", ""))[:80],
            conversation_id=str(
                params.get("conversation_id", ""))[:80])
    except (ValueError, TypeError) as error:
        raise AutomationRefusedError(str(error)) from error
    return {"packet": str(packet.get("packet", ""))[:80],
            "sections": len(packet.get("sections", []) or [])}


def _exec_notify(params: dict, run: AutomationRun) -> dict:
    kind = str(params.get("kind", "")).strip()[:40]
    title = str(params.get("title", "")).strip()
    if not title:
        raise AutomationRefusedError("notify needs a title")
    body = str(params.get("body", ""))[:1000]
    _notify_nodes(kind, title, body,
                  related_mission=run.mission_id)
    return {"notified": True, "kind": kind}


async def _exec_mission_tick(params: dict) -> dict:
    from . import main as _main
    mission_id = str(params.get("mission_id", "")).strip()[:80]
    if not mission_id:
        raise AutomationRefusedError(
            "mission_tick needs a mission_id")
    from .missions import load_mission
    try:
        mission = load_mission(mission_id)
    except ValueError as error:
        raise AutomationRefusedError(str(error)) from error
    if mission is None:
        raise AutomationRefusedError("mission not found")
    if mission.status not in ("approved", "running"):
        raise AutomationRefusedError(
            f"mission is {mission.status}; ticks run inside "
            "approved plans only")
    try:
        tick = await _main._executor().tick(mission_id)
    except Exception as error:
        raise AutomationRefusedError(
            f"mission tick failed safely: {error}"[:300])
    return {"mission_id": mission_id,
            "tick_status": str(tick.get("status", "")),
            "tick": {key: str(value)[:200]
                     for key, value in tick.items()}}


def _exec_mission_propose(params: dict,
                          run: AutomationRun) -> dict:
    from . import main as _main
    goal = str(params.get("goal", "")).strip()
    if not goal:
        raise AutomationRefusedError(
            "mission_propose needs a goal")
    conversation_id = str(
        params.get("conversation_id", "")).strip()[:80]
    if conversation_id:
        from .database import chat_connection, init_chat_database
        init_chat_database()
        with chat_connection() as db:
            row = db.execute(
                "SELECT conversation_id FROM conversations "
                "WHERE conversation_id=?",
                (conversation_id,)).fetchone()
        if row is None:
            raise AutomationRefusedError(
                "conversation not found; missions belong to "
                "real conversations")
    else:
        conversation_id = f"conv-auto-{run.run_id[:12]}"
        from .database import chat_connection, init_chat_database
        init_chat_database()
        with chat_connection() as db:
            db.execute(
                """INSERT INTO conversations
                (conversation_id, title, project_ref, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO NOTHING""",
                (conversation_id,
                 f"Automation: {goal[:80]}", "",
                 _now()))
    steps = params.get("steps", []) or []
    if not isinstance(steps, list):
        raise AutomationRefusedError("steps must be a list")
    cleaned_steps: list[dict] = []
    for raw in steps[:10]:
        if not isinstance(raw, dict):
            raise AutomationRefusedError(
                "each step must be an object")
        kind = str(raw.get("kind", "readout")).strip()[:40]
        if kind not in ("readout", "analysis", "research"):
            raise AutomationRefusedError(
                "automation may only propose read-only mission "
                "steps (readout, analysis, research)")
        cleaned_steps.append({
            "kind": kind,
            "description": str(raw.get("description", goal))[:300],
            "parameters": {"source": "project"}
            if kind == "readout" else
            ({"question": str(raw.get("question", goal))[:500]}
             if kind == "research" else {})})
    try:
        mission = _main._executor().create(
            conversation_id, goal[:500], cleaned_steps,
            max_steps=10)
    except Exception as error:
        raise AutomationRefusedError(
            f"mission draft failed safely: {error}"[:300])
    return {"mission_id": mission.mission_id,
            "status": mission.status,
            "note": "draft created; plan YES still required"}


def _exec_write_propose(params: dict,
                        run: AutomationRun) -> dict:
    from . import main as _main
    from .controlled_writes import propose_write
    mutation_type = str(
        params.get("mutation_type", "")).strip()[:40]
    target = str(params.get("target", "")).strip()[:200]
    payload = params.get("payload", {})
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise AutomationRefusedError("payload must be an object")
    if len(payload) > 12:
        raise AutomationRefusedError("payload too large (12 keys)")
    lowered = _json_dump(payload).lower()
    for hint in _SECRET_HINTS:
        if hint in lowered:
            raise AutomationRefusedError(
                "payload must not carry secrets")
    import secrets as _secrets
    proposal_id = f"wrt-{_secrets.token_hex(4)}"
    try:
        proposal = propose_write(
            proposal_id, mutation_type, target, payload,
            actor=f"automation:{run.run_id}")
        _main._write_save(proposal, "proposed")
    except ValueError as error:
        raise AutomationRefusedError(str(error)) from error
    return {"proposal_id": proposal_id,
            "mutation_type": mutation_type,
            "note": "inert proposal stored; exact YES still "
                    "required in /writes"}


def _exec_fab_prepare(params: dict) -> dict:
    from .workshop3d import (prepare_job, propose_job_print,
                             slice_job)
    job_id = str(params.get("job_id", "")).strip()[:80]
    op = str(params.get("op", "prepare")).strip()[:20]
    if not job_id:
        raise AutomationRefusedError("fab_prepare needs a job_id")
    if op == "prepare":
        try:
            record = prepare_job(job_id)
        except (ValueError, RuntimeError) as error:
            raise AutomationRefusedError(str(error)) from error
        return {"job_id": job_id, "stage": record.get("stage", ""),
                "op": op}
    if op == "slice":
        try:
            record = slice_job(job_id, slicer="test-slicer")
        except (ValueError, RuntimeError) as error:
            raise AutomationRefusedError(str(error)) from error
        return {"job_id": job_id, "stage": record.get("stage", ""),
                "op": op, "slicer": "test-slicer"}
    if op == "propose":
        try:
            record = propose_job_print(job_id, actor="automation")
        except (ValueError, RuntimeError) as error:
            raise AutomationRefusedError(str(error)) from error
        return {"job_id": job_id, "stage": record.get("stage", ""),
                "op": op, "note": "inert print proposal; physical "
                                  "YES still required"}
    raise AutomationRefusedError(
        "fab_prepare op must be prepare, slice or propose")


def _exec_node_prepare(params: dict) -> dict:
    from .nodemesh import validate_delegation
    try:
        checked = validate_delegation(
            str(params.get("requesting_node", "")),
            str(params.get("task_kind", "")),
            str(params.get("capability", "")),
            params.get("payload") if isinstance(
                params.get("payload"), dict) else {})
    except ValueError as error:
        raise AutomationRefusedError(str(error)) from error
    return {"validated": True,
            "task_kind": checked["task_kind"],
            "capability": checked["capability"],
            "note": "routing validated only; dispatch stays a "
                    "separate pull by the node (FUTURE)"}


def _exec_camera_session(params: dict) -> dict:
    from .camera_ecosystem import (describe_observation,
                                   propose_candidates, run_session)
    session_id = str(params.get("session_id", "")).strip()[:80]
    op = str(params.get("op", "run")).strip()[:20]
    observation_id = str(params.get("observation_id", "")) \
        .strip()[:80]
    if op == "run":
        if not session_id:
            raise AutomationRefusedError(
                "camera_session run needs a session_id")
        try:
            session = run_session(session_id)
        except (ValueError, RuntimeError) as error:
            raise AutomationRefusedError(str(error)) from error
        data = session.model_dump(mode="json") \
            if hasattr(session, "model_dump") else dict(session)
        return {"op": op, "session_id": session_id,
                "observations": len(data.get("observations", []))}
    if op in ("describe", "propose"):
        if not observation_id:
            raise AutomationRefusedError(
                f"camera_session {op} needs an observation_id")
        try:
            if op == "describe":
                result = describe_observation(observation_id)
            else:
                result = {"candidates": propose_candidates(
                    observation_id)}
        except (ValueError, RuntimeError) as error:
            raise AutomationRefusedError(str(error)) from error
        return {"op": op, "observation_id": observation_id,
                "result": str(result)[:1000]}
    raise AutomationRefusedError(
        "camera_session op must be run, describe or propose")


# -- drive loop ------------------------------------------------------------------

async def drive_run(run_id: str, budget_steps: int = 10) -> dict:
    """Drive one run through safe steps until a gate, bound or
    completion. Explicit call only — never a background thread."""
    run = load_run(run_id)
    if run is None:
        raise AutomationRefusedError("automation run not found")
    if run.state in ("completed", "failed", "cancelled"):
        return run_to_json(run) | {"drove": 0,
                                   "note": "run already terminal"}
    if run.state not in ("running",):
        raise AutomationRefusedError(
            f"run is {run.state}; resume it first")
    try:
        budget = max(1, min(int(budget_steps or 10), 25))
    except (TypeError, ValueError):
        raise AutomationRefusedError("budget_steps must be an integer")
    bounds = run.bounds or _default_bounds()
    started = time.monotonic()
    drove = 0
    consecutive_failures = 0
    _bus("automation.progress",
         f"Automation {run.run_id} driving ({budget} step budget)",
         mission_id=run.mission_id)
    while drove < budget:
        if time.monotonic() - started > bounds["max_runtime_seconds"]:
            return _finish_blocked(
                run, "runtime budget reached; re-drive explicitly")
        pending = [step for step in run.steps
                   if step.status in ("pending", "running")]
        if not pending:
            return _finish_completed(run, drove)
        if drove >= bounds["max_steps"]:
            return _finish_blocked(
                run, "step budget reached; re-drive explicitly")
        step = pending[0]
        _resolve_step_refs(run, step)
        if step.kind == "mission_tick" and not str(
                step.params.get("mission_id", "")).strip():
            return _finish_waiting(
                run, step,
                "No draft mission to tick yet; propose one first "
                "or approve the plan, then resume.",
                {}, _approval_url_for(run))
        if step.gate:
            verdict = check_gate_live(step.gate)
            if not verdict["met"]:
                own_reason = ""
                if step.kind == "wait":
                    own_reason = str(step.params.get(
                        "reason", "")).strip()[:200]
                prefix = f"{own_reason} — " if own_reason else ""
                return _finish_waiting(
                    run, step,
                    f"{prefix}Gate unmet before step "
                    f"{step.step_id}: {verdict['detail']}",
                    step.gate, verdict["approval_url"])
        step.status = "running"
        save_run(run)
        try:
            result = await _execute_step(run, step)
        except _WaitGate as waiting:
            return _finish_waiting(
                run, step, str(waiting)[:300],
                waiting.gate or dict(step.gate or {}), "")
        except AutomationRefusedError as error:
            return _finish_failed(
                run, step, f"refused: {error}"[:300])
        except Exception as error:
            step.attempts += 1
            step.error = str(error)[:500]
            consecutive_failures += 1
            if (step.attempts <= bounds["max_retries"]
                    and consecutive_failures
                    < bounds["max_consecutive_failures"]):
                step.status = "pending"
                save_run(run)
                drove += 1
                continue
            return _finish_failed(
                run, step,
                f"failed after {step.attempts} attempt(s): "
                f"{error}"[:300])
        step.status = "done"
        step.result = result if isinstance(result, dict) else {
            "result": str(result)[:1000]}
        step.error = ""
        consecutive_failures = 0
        drove += 1
        save_run(run)
        _bus("automation.progress",
             f"Automation {run.run_id} step {step.step_id} "
             f"({step.kind}) done", mission_id=run.mission_id)
    save_run(run)
    return run_to_json(run) | {"drove": drove,
                               "note": "drive budget spent; "
                                       "re-drive explicitly"}


def _resolve_step_refs(run: AutomationRun,
                       step: AutomationStep) -> None:
    """Fill wait-gate and mission_tick refs from an earlier
    mission_propose result in the same run. The draft mission
    cannot exist at creation time, so the reference resolves
    at drive time from stored results — never guessed."""
    if step.kind not in ("wait", "mission_tick"):
        return
    known = ""
    for prior in run.steps:
        if prior.status != "done":
            continue
        result = prior.result or {}
        if isinstance(result, dict) and result.get("mission_id"):
            known = str(result["mission_id"])[:80]
    if known:
        if step.kind == "mission_tick" and not step.params.get(
                "mission_id"):
            step.params["mission_id"] = known
        if step.kind == "wait" and not step.gate:
            step.gate = {"type": "mission_approved", "ref": known}
    if step.kind == "wait" and not step.gate:
        for prior in run.steps:
            if prior.status != "done":
                continue
            result = prior.result or {}
            if isinstance(result, dict) and result.get(
                    "proposal_id"):
                step.gate = {"type": "write_approved",
                             "ref": str(result["proposal_id"])[:80]}
                break
    save_run(run)


def _finish_waiting(run: AutomationRun, step: AutomationStep,
                    reason: str, gate: dict,
                    approval_url: str) -> dict:
    from .decisions import Decision, StepOutcome, decide
    outcome = StepOutcome(
        kind=step.kind, step_status="pending", ok=False,
        attempts=step.attempts,
        waiting_detail=reason[:200],
        mission_status="running")
    decision = decide(outcome)
    step.status = "waiting"
    run.state = ("waiting_for_agent"
                 if decision.state == "WAITING_FOR_AGENT"
                 else "waiting_for_human")
    run.waiting = {
        "reason": reason[:500],
        "action": f"step {step.step_id} ({step.kind})",
        "scope": _json_dump(step.params)[:1000],
        "source": f"automation:{run.run_id}",
        "fingerprint": "",
        "approval_url": approval_url or _approval_url_for(run),
        "mission_id": run.mission_id,
        "step_id": step.step_id,
        "gate": dict(gate or {}),
        "decision": decision.state,
    }
    save_run(run)
    _bus("automation.waiting",
         f"Automation {run.run_id} waits: {reason[:200]}",
         mission_id=run.mission_id)
    _notify_nodes(
        "approval_required",
        f"Automation waits: {run.goal[:100]}",
        f"{reason[:400]} Open {run.waiting['approval_url']} "
        "to decide; the run resumes after your YES.",
        related_mission=run.mission_id)
    return run_to_json(run) | {"drove": 0, "decision": decision.state}


def _finish_blocked(run: AutomationRun, reason: str) -> dict:
    run.state = "blocked"
    run.completed_at = _now()
    save_run(run)
    _bus("automation.failed",
         f"Automation {run.run_id} blocked: {reason[:200]}",
         mission_id=run.mission_id)
    _notify_nodes(
        "system_attention",
        f"Automation blocked: {run.goal[:100]}",
        reason[:400], related_mission=run.mission_id)
    return run_to_json(run) | {"drove": 0}


def _finish_failed(run: AutomationRun, step: AutomationStep,
                   reason: str) -> dict:
    step.status = "failed"
    run.state = "failed"
    run.completed_at = _now()
    save_run(run)
    _bus("automation.failed",
         f"Automation {run.run_id} failed at {step.step_id}: "
         f"{reason[:200]}", mission_id=run.mission_id)
    _notify_nodes(
        "system_attention",
        f"Automation failed: {run.goal[:100]}",
        reason[:400], related_mission=run.mission_id)
    return run_to_json(run) | {"drove": 0}


def _finish_completed(run: AutomationRun, drove: int) -> dict:
    run.state = "completed"
    run.completed_at = _now()
    memory_id = _remember_run(run)
    save_run(run)
    _bus("automation.completed",
         f"Automation {run.run_id} completed: {run.goal[:120]}",
         mission_id=run.mission_id)
    _notify_nodes(
        "task_completed",
        f"Automation completed: {run.goal[:100]}",
        "All safe steps done; consequential work waited for "
        "your YES along the way.",
        related_mission=run.mission_id)
    return run_to_json(run) | {"drove": drove,
                               "memory_id": memory_id}


def _approval_url_for(run: AutomationRun) -> str:
    if run.mission_id:
        return f"/missions/{run.mission_id}"
    return "/activity"


def _remember_run(run: AutomationRun) -> str:
    """One episodic memory for a completed run. Observed
    outcome, never a fact tier, never verified."""
    try:
        from .inventory_read import Provenance
        from .memory import list_memories, new_memory, save_memory
        for entry in list_memories(limit=200):
            if run.run_id in (entry.entity_refs or []):
                return entry.memory_id
        content = (f"Automation '{run.goal[:200]}' completed. "
                   f"Steps: " + "; ".join(
                       f"{step.kind}={step.status}"
                       for step in run.steps)[:1500])
        entry = new_memory(
            "episodic", f"Automation ended: {run.goal[:120]}",
            truth="observed", content=content,
            source=f"automation:{run.run_id}",
            provenance=Provenance(
                source_type="sensor-observed",
                creator_id="living-automation", human_verified=False,
                notes="automation terminal-state record; observed "
                      "system outcome, never a fact"),
            project_ref="",
            entity_refs=[run.run_id] + (
                [run.mission_id] if run.mission_id else []),
            event_refs=[])
        save_memory(entry)
        return entry.memory_id
    except Exception:
        return ""


async def resume_run(run_id: str, budget_steps: int = 10) -> dict:
    """Resume a waiting run. Re-checks the waiting gate against
    live stores first: unmet stays waiting, met keeps driving.
    Stale approvals can never wake a run."""
    run = load_run(run_id)
    if run is None:
        raise AutomationRefusedError("automation run not found")
    if run.state not in ("waiting_for_human", "waiting_for_agent"):
        raise AutomationRefusedError(
            f"run is {run.state}; only waiting runs resume")
    waiting = run.waiting or {}
    gate = waiting.get("gate") or {}
    step_id = str(waiting.get("step_id", ""))
    if gate:
        verdict = check_gate_live(gate)
        if not verdict["met"]:
            run.waiting["reason"] = (
                f"Still waiting: {verdict['detail']}"[:500])
            save_run(run)
            return run_to_json(run) | {
                "resumed": False,
                "note": "gate still unmet; nothing advanced"}
    for step in run.steps:
        if step.step_id == step_id and step.status == "waiting":
            step.status = "pending"
    run.state = "running"
    run.waiting = {}
    save_run(run)
    _bus("automation.progress",
         f"Automation {run.run_id} resumed after verified gate",
         mission_id=run.mission_id)
    report = await drive_run(run_id, budget_steps=budget_steps)
    report["resumed"] = True
    return report


# -- templates: named safe chains ------------------------------------------------

AUTOMATION_TEMPLATES = [
    {
        "template_id": "intel_to_research",
        "title": "Conversation → research → candidate",
        "description": "Analyze one import, queue its research "
                       "questions, propose candidates, notify. "
                       "Read-only plus candidates; research "
                       "execution stays a separate explicit step.",
        "steps": [
            {"kind": "intel_analyze",
             "params": {"conversation_id": "{conversation_id}"}},
            {"kind": "research_queue",
             "params": {"question": "{goal}",
                        "priority": "MEDIUM"}},
            {"kind": "knowledge_candidate",
             "params": {"title": "Follow-up: {goal}",
                        "kind": "note",
                        "text": "{goal}"}},
            {"kind": "notify",
             "params": {"kind": "research_finding",
                        "title": "Intel chain ready: {goal}"}},
        ],
    },
    {
        "template_id": "observation_to_symbiosis",
        "title": "Observation → candidate → symbiosis",
        "description": "Describe one camera observation, propose "
                       "candidates, suggest a link, notify. The "
                       "link stays PROPOSED until a human YES.",
        "steps": [
            {"kind": "camera_session",
             "params": {"op": "describe",
                        "observation_id": "{observation_id}"}},
            {"kind": "camera_session",
             "params": {"op": "propose",
                        "observation_id": "{observation_id}"}},
            {"kind": "symbiosis_propose",
             "params": {"from_id": "{observation_id}",
                        "to_id": "{entity_id}",
                        "predicate": "related_to"}},
            {"kind": "notify",
             "params": {"kind": "new_connection",
                        "title": "Symbiosis proposed: {goal}"}},
        ],
    },
    {
        "template_id": "missed_to_mission",
        "title": "Missed item → draft mission → wait → tick",
        "description": "Analyze one import, draft a read-only "
                       "mission, WAIT for the plan YES, then tick "
                       "inside the approved plan. Never self-starts.",
        "steps": [
            {"kind": "intel_analyze",
             "params": {"conversation_id": "{conversation_id}"}},
            {"kind": "mission_propose",
             "params": {"goal": "{goal}",
                        "conversation_id": "{conversation_id}"}},
            {"kind": "wait",
             "params": {"reason": "plan YES required before "
                                  "any tick"},
             "gate": {"type": "mission_approved",
                      "ref": "{mission_id}"}},
            {"kind": "mission_tick",
             "params": {"mission_id": "{mission_id}"}},
        ],
    },
]


def list_templates() -> list[dict]:
    return [{key: template[key] for key in
             ("template_id", "title", "description")}
            | {"steps": len(template["steps"])}
            for template in AUTOMATION_TEMPLATES]


def get_template(template_id: str) -> dict | None:
    for template in AUTOMATION_TEMPLATES:
        if template["template_id"] == template_id:
            return template
    return None


def create_from_template(template_id: str, args: dict | None = None,
                         *, mission_id: str = "",
                         bounds: dict | None = None,
                         overnight: bool = False,
                         actor: str = "web") -> AutomationRun:
    """Instantiate a template. {placeholders} come from operator
    args (plain substitution, never code). Unresolved
    placeholders refuse — the run never guesses its inputs."""
    template = get_template(template_id)
    if template is None:
        raise AutomationRefusedError(
            f"Unknown automation template '{template_id}'")
    args = dict(args or {})

    def _render(value: str) -> str:
        text = str(value or "")
        for key, item in args.items():
            text = text.replace("{" + str(key) + "}",
                                str(item or ""))
        if "{" in text and "}" in text:
            raise AutomationRefusedError(
                "template placeholders left unresolved; pass "
                "every input explicitly")
        return text

    steps: list[dict] = []
    for raw in template["steps"]:
        params = {}
        for key, value in (raw.get("params", {}) or {}).items():
            if raw.get("kind") == "mission_tick" and \
                    value == "{mission_id}":
                # Resolves at drive time from the draft mission
                # proposed earlier in the same run.
                params[key] = ""
                continue
            params[key] = _render(value) if isinstance(
                value, str) else value
        gate = {}
        for key, value in (raw.get("gate", {}) or {}).items():
            gate[key] = _render(value) if isinstance(
                value, str) else value
        # wait-gates referencing a draft mission resolve at drive
        # time from the run itself, not from creation args.
        if raw.get("kind") == "wait" and \
                gate.get("ref", "").startswith("{"):
            gate = {}
        steps.append({"kind": raw["kind"], "params": params,
                      "gate": gate})
    goal = str(args.get("goal", template["title"]))[:500]
    return create_run(goal, steps, mission_id=mission_id,
                      template_id=template_id, bounds=bounds,
                      overnight=overnight, actor=actor)
