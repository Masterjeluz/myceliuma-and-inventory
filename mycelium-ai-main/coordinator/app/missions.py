"""Server-side mission/plan model (BIG #3).

A Mission is the persistent, server-owned wrapper around an approved
plan: a goal plus an ordered, bounded list of steps. Autonomy exists
exclusively inside these steps — the executor may only perform what
the approved mission describes, and every desktop input still passes
through the existing desktop-action approval gate.

Persistence lives in the chat/agent database (tables ``missions``,
``conversation_events``, ``action_bindings``); the nodes/tasks queue
is untouched except through the existing bridges.

IDs: ``mission_`` / ``step_`` / ``mev_`` (no collision with the
``xxx_`` world-model prefixes or the ``conv-``/``dact-`` loop IDs).

Mission statuses: draft, pending_approval, approved, running,
paused, completed, failed, cancelled, blocked. Creation lands on
pending_approval (draft is reserved for advisor-suggested missions
that an operator has not adopted yet).

Step kinds (closed): readout (server-side read-only), desktop
(one existing ComputerAction via the dact gate), analysis
(provider advice, artifact only), proposal (AdapterProposal
artifact, approval happens outside the mission through the
existing gate — never automatic), write (one bound controlled
write proposal: executes only with its own exact human YES plus
fingerprint revalidation, then records result + independent
verification — never automatic, never a bypass), camera_observe
(one bound camera device: captures through the injected observe
capability into a stored observation; metadata result only,
never pixels, never an automatic write), fabricate (one bounded
test-geometry generation + validation through the injected
fabricate capability; artifact metadata only), slice (one
bounded slicing run through the injected slice capability;
G-code metadata only), physical_print (one bound print
proposal: executes only with its own exact human YES plus
full revalidation — mission YES never starts the machine),
research (one bounded read-only web-research run through the
injected research runner: question or existing run id,
REAL/TEST/UNAVAILABLE labelled, dossier + research memory
on completion).

Rules (tested, all fail-closed):

- steps are 1..20, sequences 0..n-1 unique and dense.
- desktop steps pin action_type + validated parameters at creation;
  requires_approval must equal the existing per-type policy
  (input True, screenshot/wait False) — the mission cannot relax it.
- readout sources come from a closed allow-list; unknown sources,
  kinds, actions or parameters are refused before storage.
- non-desktop steps run under plan approval only
  (requires_approval must be False); step-level YES/NO exists
  exclusively through the desktop-action gate.
- transitions validate current status; races use conditional
  updates (MissionConflictError, HTTP 409); semantic violations
  are ValueError (HTTP 422).
"""

import secrets
import time
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .computer_actions import (
    KNOWN_ACTION_TYPES,
    approval_required_for,
    validate_parameters,
)
from .database import chat_connection, dump, init_chat_database, load
from .inventory_read import Provenance

MissionStatus = Literal[
    "draft", "pending_approval", "approved", "running", "paused",
    "completed", "failed", "cancelled", "blocked",
]
VALID_MISSION_STATUSES = frozenset({
    "draft", "pending_approval", "approved", "running", "paused",
    "completed", "failed", "cancelled", "blocked",
})
TERMINAL_MISSION_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "blocked"})

StepKind = Literal["readout", "desktop", "analysis", "proposal",
                   "write", "camera_observe", "fabricate", "slice",
                   "physical_print", "research"]
VALID_STEP_KINDS = frozenset({"readout", "desktop", "analysis",
                              "proposal", "write", "camera_observe",
                              "fabricate", "slice", "physical_print",
                              "research"})

StepStatus = Literal[
    "pending", "waiting_approval", "dispatched", "completed",
    "failed", "blocked", "skipped",
]
VALID_STEP_STATUSES = frozenset({
    "pending", "waiting_approval", "dispatched", "completed",
    "failed", "blocked", "skipped",
})
TERMINAL_STEP_STATUSES = frozenset(
    {"completed", "failed", "blocked", "skipped"})

READOUT_SOURCES = frozenset({
    "git-status", "git-branch", "git-diff", "project", "inventory",
})

#: Step kinds that may ever auto-dispatch onto the node task queue
#: (H1). Closed on purpose: only kinds whose queue counterpart has
#: a live, read-only auto-executor in the claim loop
#: (research.fetch_url, code.review). Desktop/input, writes, camera,
#: fabrication, slice, physical print and readout never dispatch —
#: they keep their existing inline runners and gates.
DISPATCHABLE_KINDS = frozenset({"research", "analysis"})

#: Default capability for dispatched analysis tasks. Mirrors the
#: proven code_worker loop (code.* only); steps may pin their own
#: validated required_capabilities instead. Only code.review ever
#: dispatches from analysis — patch/test stay operator-queued.
DISPATCH_CODE_CAPABILITY = "code.review"

#: Default capability advertised work for dispatched research tasks.
#: Mirrors the proven research worker loop (PASS 3); steps may pin
#: their own validated required_capabilities instead.
DISPATCH_FETCH_CAPABILITY = "research.fetch"

#: Payload budget for one dispatched fetch (matches the proven
#: research worker loop; the executor caps reads server-side too).
DISPATCH_FETCH_MAX_CHARS = 4096

VALID_EVENT_TYPES = frozenset({
    "mission_created", "mission_approved", "mission_paused",
    "mission_resumed", "mission_cancelled", "mission_completed",
    "mission_failed", "mission_blocked",
    "step_started", "step_completed", "step_failed", "step_blocked",
    "task_dispatched",
    "action_proposed", "action_result", "observation", "note",
    "write_proposed", "write_approved", "write_executed",
    "write_result", "verification_started", "verification_passed",
    "verification_failed", "camera_observed", "vision_analyzed",
    "print_started", "print_completed", "print_failed",
    "print_cancelled",
})

MAX_STEPS = 20
MAX_GOAL_CHARS = 500
MAX_DESC_CHARS = 500
MAX_RESULT_CHARS = 4000
MAX_MISSION_STEPS = 20
APPROVE_TEXT = "YES"


class MissionConflictError(RuntimeError):
    """Conditional mission update lost a race; caller retries or stops."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_mission_id() -> str:
    return f"mission_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def generate_step_id() -> str:
    return f"step_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def generate_event_id() -> str:
    return f"mev_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


class MissionStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=3, max_length=80)
    sequence: int = Field(ge=0, le=MAX_STEPS)
    description: str = Field(min_length=1, max_length=MAX_DESC_CHARS)
    kind: str = Field(min_length=1, max_length=20)
    action_type: str = Field(default="", max_length=40)
    parameters: dict[str, Any] = Field(default_factory=dict)
    required_capabilities: list[str] = Field(default_factory=list,
                                             max_length=10)
    requires_approval: bool = False
    status: str = "pending"
    desktop_action_id: str = Field(default="", max_length=80)
    observation_reference: str = Field(default="", max_length=80)
    result_text: str = Field(default="", max_length=MAX_RESULT_CHARS)
    proposal_id: str = Field(default="", max_length=80)
    error: str = Field(default="", max_length=2000)
    started_at: str = ""
    completed_at: str = ""


class Mission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str = Field(min_length=3, max_length=80)
    conversation_id: str = Field(min_length=3, max_length=80)
    goal: str = Field(min_length=1, max_length=MAX_GOAL_CHARS)
    status: str = "pending_approval"
    current_step: int = Field(default=0, ge=0)
    max_steps: int = Field(default=10, ge=1, le=MAX_MISSION_STEPS)
    steps: list[MissionStep] = Field(min_length=1, max_length=MAX_STEPS)
    approved_by: str = ""
    approved_at: str = ""
    created_at: str = ""
    provenance: Provenance = Field(default_factory=Provenance)
    context_records: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MissionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=3, max_length=80)
    conversation_id: str = Field(min_length=3, max_length=80)
    event_type: str = Field(min_length=1, max_length=40)
    mission_id: str = Field(default="", max_length=80)
    step_id: str = Field(default="", max_length=80)
    message: str = Field(default="", max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


def _check_step_definition(index: int, data: dict) -> MissionStep:
    if not isinstance(data, dict):
        raise ValueError(f"Step {index} must be an object")
    kind = str(data.get("kind", ""))
    if kind not in VALID_STEP_KINDS:
        raise ValueError(f"Step {index} has unknown kind '{kind}'")
    description = data.get("description", "")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"Step {index} needs a description")
    if len(description) > MAX_DESC_CHARS:
        raise ValueError(f"Step {index} description too long")
    requires_approval = data.get("requires_approval", False)
    action_type = str(data.get("action_type", "") or "")
    parameters = data.get("parameters", {})
    if not isinstance(parameters, dict):
        raise ValueError(f"Step {index} parameters must be an object")
    capabilities = list(data.get("required_capabilities", []) or [])
    if len(capabilities) > 10 or any(
            not isinstance(cap, str) or not cap.strip()
            for cap in capabilities):
        raise ValueError(f"Step {index} has invalid capabilities")
    if kind == "desktop":
        if action_type not in KNOWN_ACTION_TYPES:
            raise ValueError(
                f"Step {index} has unknown action '{action_type}'")
        checked = validate_parameters(action_type, parameters)
        policy = approval_required_for(action_type)
        if bool(requires_approval) is not policy:
            raise ValueError(
                f"Step {index} approval flag must match policy "
                f"({action_type}: {policy})")
        parameters = checked
    else:
        if action_type:
            raise ValueError(
                f"Step {index}: only desktop steps carry an action")
        if bool(requires_approval):
            raise ValueError(
                f"Step {index}: step-level approval exists only for "
                "desktop steps through the action gate")
        if kind == "write":
            proposal_id = parameters.get("proposal_id", "")
            if (not isinstance(proposal_id, str)
                    or not 3 <= len(proposal_id) <= 80):
                raise ValueError(
                    f"Step {index}: write steps bind to one write "
                    "proposal_id (3..80 chars)")
            unknown = set(parameters) - {"proposal_id"}
            if unknown:
                raise ValueError(
                    f"Step {index}: write steps carry only proposal_id; "
                    f"unexpected: {sorted(unknown)}")
        elif kind == "camera_observe":
            device_id = parameters.get("device_id", "")
            if (not isinstance(device_id, str)
                    or not 3 <= len(device_id) <= 80):
                raise ValueError(
                    f"Step {index}: camera_observe steps bind to one "
                    "device_id (3..80 chars)")
            unknown = set(parameters) - {"device_id"}
            if unknown:
                raise ValueError(
                    f"Step {index}: camera_observe steps carry only "
                    f"device_id; unexpected: {sorted(unknown)}")
        elif kind == "fabricate":
            description = parameters.get("description", "")
            if (not isinstance(description, str)
                    or not description.strip()
                    or len(description) > 500):
                raise ValueError(
                    f"Step {index}: fabricate steps need a description "
                    "(1..500 chars)")
            method = str(parameters.get("method",
                                        "procedural-test"))
            if method != "procedural-test":
                raise ValueError(
                    f"Step {index}: unknown fabrication method "
                    f"'{method}'")
            unknown = set(parameters) - {"description", "method"}
            if unknown:
                raise ValueError(
                    f"Step {index}: fabricate steps carry only "
                    f"description/method; unexpected: {sorted(unknown)}")
        elif kind == "slice":
            for field in ("artifact_ref", "profile", "printer_id"):
                value = parameters.get(field, "")
                if (not isinstance(value, str) or not value.strip()
                        or len(value) > 200):
                    raise ValueError(
                        f"Step {index}: slice steps need '{field}' "
                        "(non-empty text)")
            unknown = set(parameters) - {"artifact_ref", "profile",
                                         "printer_id"}
            if unknown:
                raise ValueError(
                    f"Step {index}: slice steps carry only "
                    f"artifact_ref/profile/printer_id; unexpected: "
                    f"{sorted(unknown)}")
        elif kind == "physical_print":
            proposal_id = parameters.get("proposal_id", "")
            if (not isinstance(proposal_id, str)
                    or not 3 <= len(proposal_id) <= 80):
                raise ValueError(
                    f"Step {index}: physical_print steps bind to one "
                    "print proposal_id (3..80 chars)")
            unknown = set(parameters) - {"proposal_id"}
            if unknown:
                raise ValueError(
                    f"Step {index}: physical_print steps carry only "
                    f"proposal_id; unexpected: {sorted(unknown)}")
        elif kind == "readout":
            source = str(parameters.get("source", ""))
            if source not in READOUT_SOURCES:
                raise ValueError(
                    f"Step {index} has unknown readout source '{source}'")
        elif kind == "research":
            question = parameters.get("question", "")
            run_id = parameters.get("research_run_id", "")
            has_question = (isinstance(question, str)
                            and question.strip()
                            and len(question) <= 500)
            has_run = (isinstance(run_id, str)
                       and 3 <= len(run_id) <= 80)
            if has_question == has_run:
                raise ValueError(
                    f"Step {index}: research steps carry exactly one "
                    "of question / research_run_id")
            unknown = set(parameters) - {"question",
                                          "research_run_id",
                                          "max_sources", "project_ref",
                                          "source_urls", "dispatch"}
            if unknown:
                raise ValueError(
                    f"Step {index}: research steps carry only "
                    f"question/research_run_id/max_sources/project_ref/source_urls/dispatch; "
                    f"unexpected: {sorted(unknown)}")
            if "dispatch" in parameters and not isinstance(
                    parameters["dispatch"], bool):
                raise ValueError(
                    f"Step {index}: research 'dispatch' must be "
                    "true or false")
            for key in ("max_sources", "project_ref"):
                value = parameters.get(key, "")
                if value and (not isinstance(value, str)
                              or len(value) > 100):
                    raise ValueError(
                        f"Step {index}: research '{key}' must be "
                        "short text")
            seed_urls = parameters.get("source_urls", [])
            if seed_urls:
                if not isinstance(seed_urls, list) or len(
                        seed_urls) > 6 or any(
                        not isinstance(item, str) or not item.strip()
                        or len(item) > 2000 for item in seed_urls):
                    raise ValueError(
                        f"Step {index}: research source_urls must be "
                        "0..6 URL strings")
    return MissionStep(
        step_id=str(data.get("step_id", "") or generate_step_id()),
        sequence=index,
        description=description.strip(),
        kind=kind,
        action_type=action_type,
        parameters=parameters,
        required_capabilities=[cap.strip() for cap in capabilities],
        requires_approval=bool(requires_approval),
    )


def dispatchable_task(step: MissionStep,
                      url: str | None = None) -> dict | None:
    """Pure: one queue-task spec for a dispatchable step, else None.

    No I/O, reads only the step. Research steps with explicit
    source URLs map onto the live research.fetch_url claim-loop
    executor; analysis steps with an explicit goal map onto the
    live code_worker claim loop as code.review (bounded review
    only — patch/test never auto-dispatch). Every other kind
    returns None so callers keep the existing inline runner. The
    optional url selects which source URL a research spec covers
    (default: the first); payload always carries mission_step_id
    for idempotent re-dispatch.
    """
    if step.kind == "analysis":
        goal = str(step.parameters.get("goal", "") or "").strip()
        if not goal:
            return None
        capabilities = [str(cap or "").strip()
                        for cap in (step.required_capabilities or [])
                        if str(cap or "").strip()][:10]
        question = str(step.parameters.get("question", "")
                       or "")[:500]
        return {
            "kind": "code.review",
            "required_capabilities": capabilities or [
                DISPATCH_CODE_CAPABILITY],
            "payload": {
                "goal": goal[:500],
                "mission_step_id": step.step_id,
                "question": question,
            },
        }
    if step.kind not in DISPATCHABLE_KINDS:
        return None
    urls = [str(item or "").strip()
            for item in (step.parameters.get("source_urls", "") or [])
            if str(item or "").strip()][:6]
    if not urls:
        return None
    target = str(url if url is not None else urls[0]).strip()
    if not target or target not in urls:
        return None
    capabilities = [str(cap or "").strip()
                    for cap in (step.required_capabilities or [])
                    if str(cap or "").strip()][:10]
    question = str(step.parameters.get("question", "") or "")[:500]
    return {
        "kind": "research.fetch_url",
        "required_capabilities": capabilities or [
            DISPATCH_FETCH_CAPABILITY],
        "payload": {
            "url": target[:2000],
            "max_chars": DISPATCH_FETCH_MAX_CHARS,
            "mission_step_id": step.step_id,
            "question": question,
        },
    }


def dispatch_source_urls(step: MissionStep) -> list[str]:
    """Pure: validated source URLs of a research step (max 6)."""
    if step.kind not in DISPATCHABLE_KINDS:
        return []
    return [str(item or "").strip()
            for item in (step.parameters.get("source_urls", "") or [])
            if str(item or "").strip()][:6]


def new_mission(mission_id: str, conversation_id: str, goal: str,
                steps_data: list[dict], *,
                max_steps: int = 10,
                context_records: list[dict] | None = None,
                status: str = "pending_approval") -> Mission:
    """Build a validated mission. Fail-closed on every defect."""
    if status not in ("draft", "pending_approval"):
        raise ValueError("New missions start as draft or pending_approval")
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("Mission goal must be non-empty text")
    if len(goal) > MAX_GOAL_CHARS:
        raise ValueError("Mission goal too long")
    if not isinstance(steps_data, list) or not 1 <= len(steps_data) <= MAX_STEPS:
        raise ValueError(f"Mission needs 1..{MAX_STEPS} steps")
    steps = [_check_step_definition(index, data)
             for index, data in enumerate(steps_data)]
    try:
        resolved_max = int(max_steps)
    except (TypeError, ValueError):
        raise ValueError("max_steps must be an integer")
    if not 1 <= resolved_max <= MAX_MISSION_STEPS:
        raise ValueError(f"max_steps must be 1..{MAX_MISSION_STEPS}")
    records = list(context_records or [])[:10]
    return Mission(
        mission_id=mission_id,
        conversation_id=conversation_id,
        goal=goal.strip(),
        status=status,
        current_step=0,
        max_steps=resolved_max,
        steps=steps,
        created_at=now(),
        provenance=Provenance(
            source_type="user-created", creator_id="mission-control",
            human_verified=True,
            notes="operator-defined plan; AI advice never decides "
                  "permissions or execution"),
        context_records=records,
    )


def approve_mission(mission: Mission, response: str,
                    decided_by: str = "human") -> Mission:
    """Plan approval: exact YES moves pending_approval -> approved.

    This authorizes executing the described steps — never anything
    the executor invents along the way, and never the desktop inputs
    themselves (those keep their own gate).
    """
    if mission.status != "pending_approval":
        raise ValueError(
            f"Mission is {mission.status}; only pending missions approve")
    if not isinstance(decided_by, str) or not decided_by.strip():
        raise ValueError("decided_by must be non-empty text")
    if response != APPROVE_TEXT:
        raise ValueError(
            "Mission approval needs an exact YES; anything else refuses")
    return mission.model_copy(update={
        "status": "approved", "approved_by": decided_by.strip(),
        "approved_at": now()})


def pause_mission(mission: Mission) -> Mission:
    if mission.status != "running":
        raise ValueError(
            f"Mission is {mission.status}; only running missions pause")
    return mission.model_copy(update={"status": "paused"})


def resume_mission(mission: Mission) -> Mission:
    if mission.status != "paused":
        raise ValueError(
            f"Mission is {mission.status}; only paused missions resume")
    return mission.model_copy(update={"status": "running"})


def cancel_mission(mission: Mission) -> Mission:
    if mission.status in TERMINAL_MISSION_STATUSES:
        raise ValueError(
            f"Mission is {mission.status}; terminal missions never cancel")
    if mission.status not in ("pending_approval", "approved", "running",
                              "paused"):
        raise ValueError(
            f"Mission is {mission.status}; cannot cancel from here")
    return mission.model_copy(update={"status": "cancelled"})


def current_step_of(mission: Mission) -> MissionStep | None:
    if mission.current_step >= len(mission.steps):
        return None
    return mission.steps[mission.current_step]


def set_step(mission: Mission, step_id: str, **updates) -> Mission:
    """Replace one step that belongs to this mission (scope-checked)."""
    for index, step in enumerate(mission.steps):
        if step.step_id == step_id:
            updated = step.model_copy(update=updates)
            steps = list(mission.steps)
            steps[index] = updated
            return mission.model_copy(update={"steps": steps})
    raise ValueError(f"Step '{step_id}' is not part of this mission")


def check_binding(mission: Mission, step_id: str, action_id: str,
                  bindings: dict[str, tuple[str, str]]) -> MissionStep:
    """Prove an action belongs to this plan. Fail-closed on any gap."""
    step = next((entry for entry in mission.steps
                 if entry.step_id == step_id), None)
    if step is None:
        raise ValueError(
            f"Step '{step_id}' is not part of mission "
            f"'{mission.mission_id}'")
    if step.desktop_action_id != action_id:
        raise ValueError(
            f"Action '{action_id}' is not linked to step '{step_id}'")
    bound = bindings.get(action_id)
    if bound != (mission.mission_id, step_id):
        raise ValueError(
            f"Action '{action_id}' has no valid binding to this plan")
    return step


def new_event(conversation_id: str, event_type: str, message: str, *,
              mission_id: str = "", step_id: str = "",
              metadata: dict | None = None) -> MissionEvent:
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Unknown event type '{event_type}'")
    return MissionEvent(
        event_id=generate_event_id(),
        conversation_id=conversation_id,
        event_type=event_type,
        mission_id=mission_id,
        step_id=step_id,
        message=str(message or "")[:2000],
        metadata=dict(metadata or {}),
        created_at=now(),
    )


# -- storage (chat/agent database; queue database untouched) -----------

def save_mission(mission: Mission,
                 expected: tuple[str, int] | None = None) -> None:
    """Store a mission, optionally only when status+step still match."""
    init_chat_database()
    with chat_connection() as db:
        if expected is None:
            db.execute("""INSERT INTO missions
            (mission_id, conversation_id, record, status, current_step,
             created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(mission_id) DO UPDATE SET conversation_id=excluded.conversation_id,
            record=excluded.record, status=excluded.status,
            current_step=excluded.current_step, updated_at=excluded.updated_at""",
                       (mission.mission_id, mission.conversation_id,
                        dump(mission.model_dump(mode="json")),
                        mission.status, mission.current_step,
                        mission.created_at, now()))
            return
        changed = db.execute(
            """UPDATE missions SET conversation_id=?, record=?, status=?,
            current_step=?, updated_at=? WHERE mission_id=?
            AND status=? AND current_step=?""",
            (mission.conversation_id,
             dump(mission.model_dump(mode="json")), mission.status,
             mission.current_step, now(), mission.mission_id,
             expected[0], expected[1])).rowcount
        if not changed:
            raise MissionConflictError(
                f"Mission '{mission.mission_id}' changed state; refusing")


def load_mission(mission_id: str):
    """Load a mission or None. No exception for unknown ids."""
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT record FROM missions WHERE mission_id=?",
                         (mission_id,)).fetchone()
    if row is None:
        return None
    return Mission.model_validate(load(row["record"]))


def list_missions(conversation_id: str | None = None,
                  limit: int = 50) -> list[Mission]:
    init_chat_database()
    with chat_connection() as db:
        if conversation_id:
            rows = db.execute(
                """SELECT record FROM missions WHERE conversation_id=?
                ORDER BY created_at DESC LIMIT ?""",
                (conversation_id, max(1, min(limit, 100)))).fetchall()
        else:
            rows = db.execute(
                """SELECT record FROM missions ORDER BY created_at DESC
                LIMIT ?""",
                (max(1, min(limit, 100)),)).fetchall()
    return [Mission.model_validate(load(row["record"])) for row in rows]


def save_event(event: MissionEvent) -> None:
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO conversation_events
        (event_id, conversation_id, event_type, mission_id, step_id,
         message, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                   (event.event_id, event.conversation_id,
                    event.event_type, event.mission_id, event.step_id,
                    event.message, dump(event.metadata),
                    event.created_at))


def list_events(conversation_id: str = "", mission_id: str = "",
                limit: int = 100) -> list[MissionEvent]:
    init_chat_database()
    with chat_connection() as db:
        if mission_id:
            rows = db.execute(
                """SELECT * FROM conversation_events WHERE mission_id=?
                ORDER BY created_at ASC LIMIT ?""",
                (mission_id, max(1, min(limit, 200)))).fetchall()
        elif conversation_id:
            rows = db.execute(
                """SELECT * FROM conversation_events
                WHERE conversation_id=? ORDER BY created_at ASC LIMIT ?""",
                (conversation_id, max(1, min(limit, 200)))).fetchall()
        else:
            return []
    return [MissionEvent(**{**dict(row),
                            "metadata": load(row["metadata"])})
            for row in rows]


def bind_action(action_id: str, mission_id: str, step_id: str) -> None:
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO action_bindings
        (action_id, mission_id, step_id, bound_at) VALUES (?, ?, ?, ?)
        ON CONFLICT(action_id) DO NOTHING""",
                   (action_id, mission_id, step_id, now()))


def get_binding(action_id: str) -> tuple[str, str] | None:
    init_chat_database()
    with chat_connection() as db:
        row = db.execute(
            "SELECT mission_id, step_id FROM action_bindings "
            "WHERE action_id=?", (action_id,)).fetchone()
    if row is None:
        return None
    return (row["mission_id"], row["step_id"])


def bindings_for_mission(mission_id: str) -> dict[str, tuple[str, str]]:
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute(
            "SELECT action_id, mission_id, step_id FROM action_bindings "
            "WHERE mission_id=?", (mission_id,)).fetchall()
    return {row["action_id"]: (row["mission_id"], row["step_id"])
            for row in rows}
