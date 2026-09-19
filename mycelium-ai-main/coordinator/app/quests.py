"""Quest trails (BIG #42).

The first real quest-trail abstraction over existing missions,
craft states, symbiosis and presence. A quest references real
work — it never duplicates state:

- A quest def names ordered steps, each pointing at a REAL record
  (mission_id, task id, finance/energy/hardware-link id, or an
  entity id). Steps carry no state of their own.
- Every read derives step state live from the underlying store:
  ✓ COMPLETE (underlying record reached its done state),
  ● ACTIVE (running/approved/in-flight), ! BLOCKED/FAILED,
  ○ MISSING (empty ref or record gone).
- Progress (done/total) is real progress, no XP.
- Hardware-aware readiness names WHY a step is READY / WAITING /
  BLOCKED / UNAVAILABLE from actual node/device state — offline
  hardware is never pretended available.

Quest-level states (closed): READY | ACTIVE | WAITING | BLOCKED |
COMPLETED | FAILED.

Storage: chat DB table quests holds ONLY the def (title + step
refs). All state derives on read.
"""

from __future__ import annotations

import re as _re
import secrets
import time
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

QUEST_STATES = ("READY", "ACTIVE", "WAITING", "BLOCKED",
                "COMPLETED", "FAILED")
STEP_STATES = ("COMPLETE", "ACTIVE", "WAITING", "BLOCKED",
               "FAILED", "MISSING", "UNAVAILABLE")
STEP_KINDS = ("mission", "task", "entity", "finance", "energy",
              "hardware", "note")

STEP_GLYPHS = {"COMPLETE": "✓", "ACTIVE": "●", "WAITING": "○",
               "BLOCKED": "!", "FAILED": "!", "MISSING": "○",
               "UNAVAILABLE": "✕"}

_REF_RE = _re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,119}$")


class QuestRefusedError(ValueError):
    """Local validation refused; nothing was stored."""


class QuestStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=16)
    ref: str = Field(default="", max_length=120)


class QuestTrail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quest_id: str = Field(min_length=4, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    steps: list[QuestStep] = Field(default_factory=list,
                                   max_length=24)
    created_at: str = ""
    updated_at: str = ""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_quest_id() -> str:
    return f"qst_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def init_quest_tables(db) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS quests (
            quest_id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            steps TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)


def _ensure(db) -> None:
    init_quest_tables(db)


def new_quest(title: str, steps: list[dict]) -> QuestTrail:
    cleaned_title = str(title or "").strip()
    if not cleaned_title:
        raise QuestRefusedError("Quest needs a title")
    if len(cleaned_title) > 200:
        raise QuestRefusedError("Quest title is too long")
    if not isinstance(steps, list) or not steps:
        raise QuestRefusedError("Quest needs at least one step")
    if len(steps) > 24:
        raise QuestRefusedError("Quest has at most 24 steps")
    parsed: list[QuestStep] = []
    seen_keys: set = set()
    for index, raw in enumerate(steps):
        if not isinstance(raw, dict):
            raise QuestRefusedError(f"Step {index} must be an object")
        key = str(raw.get("key", "")).strip()[:60] or f"step-{index}"
        if key in seen_keys:
            raise QuestRefusedError(f"Duplicate step key '{key}'")
        seen_keys.add(key)
        kind = str(raw.get("kind", "")).strip().lower()[:16]
        if kind not in STEP_KINDS:
            raise QuestRefusedError(
                f"Unknown step kind '{kind}'; expected one of "
                f"{list(STEP_KINDS)}")
        ref = str(raw.get("ref", "")).strip()[:120]
        if kind != "note" and ref and not _REF_RE.match(ref):
            raise QuestRefusedError(
                f"Step '{key}' ref is malformed")
        parsed.append(QuestStep(
            key=key,
            label=str(raw.get("label", "")).strip()[:200] or key,
            kind=kind, ref=ref))
    stamp = now()
    return QuestTrail(quest_id=generate_quest_id(),
                      title=cleaned_title[:200], steps=parsed,
                      created_at=stamp, updated_at=stamp)


def save_quest(quest: QuestTrail) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        _ensure(db)
        db.execute(
            """INSERT INTO quests
            (quest_id, title, steps, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(quest_id) DO UPDATE SET
             title=excluded.title, steps=excluded.steps,
             updated_at=excluded.updated_at""",
            (quest.quest_id, quest.title,
             dump([step.model_dump(mode="json")
                   for step in quest.steps]),
             quest.created_at, quest.updated_at))
    _audit("quest.created", f"Quest '{quest.title}' defined",
           payload={"quest_id": quest.quest_id})


def _row_to_quest(row) -> QuestTrail:
    from .database import load
    try:
        raw_steps = load(row["steps"])
    except Exception:
        raw_steps = []
    steps = []
    if isinstance(raw_steps, list):
        for raw in raw_steps[:24]:
            try:
                steps.append(QuestStep(**raw) if isinstance(
                    raw, dict) else None)
            except Exception:
                continue
    steps = [step for step in steps if step is not None]
    return QuestTrail(quest_id=row["quest_id"],
                      title=row["title"] or "",
                      steps=steps,
                      created_at=row["created_at"] or "",
                      updated_at=row["updated_at"] or "")


def get_quest(quest_id: str) -> QuestTrail | None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    cleaned = str(quest_id or "").strip()[:80]
    if not cleaned:
        return None
    with chat_connection() as db:
        _ensure(db)
        row = db.execute(
            "SELECT * FROM quests WHERE quest_id=?",
            (cleaned,)).fetchone()
    if row is None:
        return None
    return _row_to_quest(row)


def list_quests(limit: int = 50) -> list[QuestTrail]:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    count = max(1, min(int(limit or 50), 100))
    with chat_connection() as db:
        _ensure(db)
        rows = db.execute(
            "SELECT * FROM quests ORDER BY updated_at DESC "
            "LIMIT ?", (count,)).fetchall()
    return [_row_to_quest(row) for row in rows]


def delete_quest(quest_id: str) -> bool:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        _ensure(db)
        changed = db.execute(
            "DELETE FROM quests WHERE quest_id=?",
            (str(quest_id or "").strip()[:80],)).rowcount
    return bool(changed)


# -- live derivation ----------------------------------------------------

def _mission_state(ref: str) -> tuple[str, str, str]:
    """(state, detail, href) for a mission step."""
    try:
        from .missions import load_mission
        mission = load_mission(ref)
    except Exception:
        return ("MISSING", "mission record unreadable",
                f"/missions/{ref}")
    if mission is None:
        return ("MISSING", "mission not found", "/missions")
    try:
        status = str(mission.record.get("status", "unknown"))
    except Exception:
        status = "unknown"
    href = f"/missions/{ref}"
    if status == "completed":
        return ("COMPLETE", "mission completed", href)
    if status in ("approved", "running"):
        return ("ACTIVE", f"mission {status}", href)
    if status == "failed":
        return ("FAILED", "mission failed", href)
    if status in ("blocked",):
        return ("BLOCKED", "mission blocked", href)
    if status in ("pending_approval", "paused"):
        return ("WAITING", f"mission {status}", href)
    if status in ("cancelled",):
        return ("MISSING", "mission cancelled", href)
    return ("WAITING", f"mission {status}", href)


def _task_state(ref: str) -> tuple[str, str, str]:
    try:
        task_id = int(str(ref).strip())
    except (TypeError, ValueError):
        return ("MISSING", "task ref is not a task id", "/activity")
    try:
        from . import main as _main
        from .database import connection
        with connection() as db:
            row = db.execute(
                "SELECT id, kind, status, assigned_node_id FROM "
                "tasks WHERE id=?", (task_id,)).fetchone()
    except Exception:
        return ("MISSING", "task record unreadable", "/activity")
    if row is None:
        return ("MISSING", "task not found", "/activity")
    status = str(row["status"])
    href = f"/api/v1/tasks/by-id/{task_id}"
    if status == "completed":
        return ("COMPLETE", f"task #{task_id} completed", href)
    if status in ("assigned", "running"):
        return ("ACTIVE", f"task #{task_id} {status}", href)
    if status == "failed":
        return ("FAILED", f"task #{task_id} failed", href)
    if status in ("blocked", "cancelled"):
        return ("BLOCKED", f"task #{task_id} {status}", href)
    return ("WAITING", f"task #{task_id} {status}", href)


def _finance_state(ref: str) -> tuple[str, str, str]:
    try:
        from .finance import get_record
        record = get_record(ref)
    except Exception:
        return ("MISSING", "finance record unreadable", "/finance")
    if record is None:
        return ("MISSING", "finance record not found", "/finance")
    href = f"/finance?record_id={ref}"
    if record.status == "CONFIRMED":
        return ("COMPLETE", f"finance {record.kind} confirmed", href)
    if record.status == "ARCHIVED":
        return ("COMPLETE", "finance record archived", href)
    return ("WAITING", "finance record draft", href)


def _energy_state(ref: str) -> tuple[str, str, str]:
    try:
        from .energy import get_record
        record = get_record(ref)
    except Exception:
        return ("MISSING", "energy record unreadable", "/energy")
    if record is None:
        return ("MISSING", "energy record not found", "/energy")
    href = f"/energy?record_id={ref}"
    if record.value is None:
        return ("WAITING", "energy value unknown", href)
    return ("COMPLETE", f"energy {record.source} recorded", href)


def _hardware_state(ref: str) -> tuple[str, str, str]:
    try:
        from .hardware_links import get_link
        link = get_link(ref)
    except Exception:
        return ("MISSING", "hardware link unreadable", "/hardware")
    if link is None:
        return ("MISSING", "hardware link not found", "/hardware")
    href = f"/hardware?link_id={ref}"
    if link.status == "VERIFIED":
        return ("COMPLETE", "hardware human-verified", href)
    if link.status == "REVOKED":
        return ("BLOCKED", "hardware link revoked", href)
    return ("WAITING", "hardware link proposed", href)


def derive_step_state(step: QuestStep) -> dict:
    """Live state for one step — no stored state consulted."""
    if not step.ref:
        if step.kind == "note":
            return {"key": step.key, "label": step.label,
                    "kind": step.kind, "ref": "",
                    "state": "MISSING",
                    "glyph": STEP_GLYPHS["MISSING"],
                    "detail": "note without linked record",
                    "href": "/quests", "readiness": "WAITING",
                    "readiness_reason": "no linked record"}
        return {"key": step.key, "label": step.label,
                "kind": step.kind, "ref": "",
                "state": "MISSING",
                "glyph": STEP_GLYPHS["MISSING"],
                "detail": "no linked record yet",
                "href": "/quests", "readiness": "WAITING",
                "readiness_reason": "no linked record"}
    if step.kind == "mission":
        state, detail, href = _mission_state(step.ref)
    elif step.kind == "task":
        state, detail, href = _task_state(step.ref)
    elif step.kind == "finance":
        state, detail, href = _finance_state(step.ref)
    elif step.kind == "energy":
        state, detail, href = _energy_state(step.ref)
    elif step.kind == "hardware":
        state, detail, href = _hardware_state(step.ref)
    elif step.kind == "entity":
        state, detail, href = ("WAITING",
                               "entity link — open in world",
                               f"/world?entity_id={step.ref}")
    else:
        state, detail, href = ("MISSING", "note step",
                               "/quests")
    readiness, readiness_reason = step_readiness(step, state)
    return {"key": step.key, "label": step.label,
            "kind": step.kind, "ref": step.ref, "state": state,
            "glyph": STEP_GLYPHS.get(state, "○"), "detail": detail,
            "href": href, "readiness": readiness,
            "readiness_reason": readiness_reason}


def step_readiness(step: QuestStep,
                   state: str) -> tuple[str, str]:
    """Hardware-aware readiness: READY / WAITING / BLOCKED /
    UNAVAILABLE from actual node/device state. Honest — never
    claims hardware that is offline or missing."""
    if state in ("COMPLETE",):
        return ("READY", "underlying record is done")
    if state in ("FAILED", "BLOCKED"):
        return ("BLOCKED", "underlying record needs attention")
    label = f"{step.label} {step.ref}".lower()
    wants_camera = "camera" in label or "observ" in label
    wants_gpu = "gpu" in label
    wants_printer = ("fabricat" in label or "print" in label)
    wants_research = ("research" in label or step.kind == "mission"
                      and "research" in label)
    try:
        from . import main as _main
        nodes = _main.list_nodes()
    except Exception:
        return ("WAITING", "node state unreadable")
    live = [node for node in nodes
            if str(node.get("derived_status", "")) in
            ("online", "busy")]
    if not live and state == "MISSING":
        return ("WAITING", "no linked record yet")
    if wants_printer:
        return ("UNAVAILABLE", "printer transport is unavailable")
    if wants_camera:
        for node in live:
            hardware = node.get("hardware", []) or []
            for item in hardware:
                if not isinstance(item, dict):
                    continue
                if str(item.get("kind", "")).lower() == "camera" \
                        and str(item.get("status", "")).lower() \
                        == "connected":
                    return ("READY",
                            f"{node.get('node_id')} has a connected "
                            "camera")
        cams = [node.get("node_id") for node in nodes
                if any(str(item.get("kind", "")).lower() == "camera"
                       for item in (node.get("hardware", []) or [])
                       if isinstance(item, dict))]
        if cams:
            return ("WAITING",
                    f"camera node {cams[0]} is offline")
        return ("BLOCKED", "no camera hardware advertised")
    if wants_gpu or wants_research:
        try:
            from .presence import research_readiness
            readiness = research_readiness()
        except Exception:
            readiness = {}
        eligible = readiness.get("eligible", []) or []
        if eligible:
            return ("READY",
                    f"{eligible[0]} can run it now")
        return ("WAITING",
                str(readiness.get("text",
                                  "no eligible node"))[:160])
    if live:
        return ("READY", f"{len(live)} node(s) online")
    return ("WAITING", "no nodes online")


def quest_detail(quest: QuestTrail) -> dict:
    steps = [derive_step_state(step) for step in quest.steps]
    done = sum(1 for step in steps
               if step["state"] == "COMPLETE")
    states = [step["state"] for step in steps]
    if states and all(state == "COMPLETE" for state in states):
        level = "COMPLETED"
    elif "FAILED" in states:
        level = "FAILED"
    elif "BLOCKED" in states:
        level = "BLOCKED"
    elif "ACTIVE" in states:
        level = "ACTIVE"
    elif "WAITING" in states or "MISSING" in states:
        level = "WAITING"
    else:
        level = "READY"
    return {"quest_id": quest.quest_id, "title": quest.title,
            "state": level, "done": done, "total": len(steps),
            "steps": steps,
            "progress": f"{done}/{len(steps)}",
            "provenance": {"source_type": "derived",
                           "creator_id": "quest-trails",
                           "human_verified": False}}


def list_quest_details(limit: int = 50) -> list[dict]:
    return [quest_detail(quest)
            for quest in list_quests(limit=limit)]


def _audit(event_type: str, summary: str, *,
           payload: dict | None = None) -> None:
    try:
        from .events import new_event, save_event
        save_event(new_event(event_type, summary,
                             payload=payload or {}))
    except Exception:
        pass
