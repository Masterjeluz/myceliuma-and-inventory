"""Quest campaigns (BIG #43).

A campaign groups existing quests into one meaningful
progression — e.g. "Solar Workshop" chains energy audit →
hardware inspection → research → materials → fabrication →
observation → verification → improvement.

A campaign stores ONLY its def (title, description, ordered
quest ids). Everything else derives live from the quest
trails layer (which itself derives from missions, tasks,
finance, energy, hardware links):

- per-quest state via quests.quest_detail
- completed / total / blocked / waiting counts
- current quest (first non-completed)
- next actionable item (first WAITING/MISSING/BLOCKED step
  across the chain, with its real href)
- evidence links (quest + step hrefs)

No XP. No fictional rewards. No independent game truth.
Creating a campaign with an unknown quest id refuses (fake
quests cannot enter). Deleting a quest leaves a MISSING
marker in the chain — never silently dropped, never
invented.
"""

from __future__ import annotations

import re as _re
import secrets
import time
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MAX_QUESTS_PER_CAMPAIGN = 12

_QUEST_ID_RE = _re.compile(r"^qst_[0-9a-f]+$")


class CampaignRefusedError(ValueError):
    """Local validation refused; nothing was stored."""


class Campaign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: str = Field(min_length=4, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    quest_ids: list[str] = Field(default_factory=list,
                                 max_length=MAX_QUESTS_PER_CAMPAIGN)
    created_at: str = ""
    updated_at: str = ""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_campaign_id() -> str:
    return f"cmp_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def init_campaign_tables(db) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            campaign_id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            quest_ids TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)


def _ensure(db) -> None:
    init_campaign_tables(db)


def _check_quest_id(value: str) -> str:
    cleaned = str(value or "").strip()[:80]
    if not _QUEST_ID_RE.match(cleaned):
        raise CampaignRefusedError(
            f"Malformed quest id '{str(value)[:40]}'")
    return cleaned


def new_campaign(title: str, quest_ids: list,
                 description: str = "") -> Campaign:
    cleaned_title = str(title or "").strip()
    if not cleaned_title:
        raise CampaignRefusedError("Campaign needs a title")
    if len(cleaned_title) > 200:
        raise CampaignRefusedError("Campaign title is too long")
    if not isinstance(quest_ids, list) or not quest_ids:
        raise CampaignRefusedError(
            "Campaign needs at least one quest")
    if len(quest_ids) > MAX_QUESTS_PER_CAMPAIGN:
        raise CampaignRefusedError(
            f"Campaign has at most {MAX_QUESTS_PER_CAMPAIGN} "
            "quests")
    cleaned_ids: list[str] = []
    for raw in quest_ids:
        cleaned = _check_quest_id(raw)
        if cleaned in cleaned_ids:
            raise CampaignRefusedError(
                f"Duplicate quest '{cleaned}'")
        cleaned_ids.append(cleaned)
    # Every quest must really exist — fake quests refuse.
    from .quests import get_quest
    for quest_id in cleaned_ids:
        try:
            quest = get_quest(quest_id)
        except Exception:
            quest = None
        if quest is None:
            raise CampaignRefusedError(
                f"Unknown quest '{quest_id}'")
    stamp = now()
    return Campaign(
        campaign_id=generate_campaign_id(),
        title=cleaned_title[:200],
        description=str(description or "").strip()[:1000],
        quest_ids=cleaned_ids,
        created_at=stamp, updated_at=stamp)


def save_campaign(campaign: Campaign) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        _ensure(db)
        db.execute(
            """INSERT INTO campaigns
            (campaign_id, title, description, quest_ids,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(campaign_id) DO UPDATE SET
             title=excluded.title,
             description=excluded.description,
             quest_ids=excluded.quest_ids,
             updated_at=excluded.updated_at""",
            (campaign.campaign_id, campaign.title,
             campaign.description,
             dump(campaign.quest_ids),
             campaign.created_at, campaign.updated_at))
    _audit("campaign.created",
           f"Campaign '{campaign.title}' defined",
           payload={"campaign_id": campaign.campaign_id,
                    "quests": len(campaign.quest_ids)})


def _row_to_campaign(row) -> Campaign:
    from .database import load
    try:
        quest_ids = load(row["quest_ids"])
    except Exception:
        quest_ids = []
    if not isinstance(quest_ids, list):
        quest_ids = []
    return Campaign(
        campaign_id=row["campaign_id"],
        title=row["title"] or "",
        description=row["description"] or "",
        quest_ids=[str(entry) for entry in quest_ids
                   if isinstance(entry, str)][
            :MAX_QUESTS_PER_CAMPAIGN],
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "")


def get_campaign(campaign_id: str) -> Campaign | None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    cleaned = str(campaign_id or "").strip()[:80]
    if not cleaned:
        return None
    with chat_connection() as db:
        _ensure(db)
        row = db.execute(
            "SELECT * FROM campaigns WHERE campaign_id=?",
            (cleaned,)).fetchone()
    if row is None:
        return None
    return _row_to_campaign(row)


def list_campaigns(limit: int = 50) -> list[Campaign]:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    count = max(1, min(int(limit or 50), 100))
    with chat_connection() as db:
        _ensure(db)
        rows = db.execute(
            "SELECT * FROM campaigns ORDER BY updated_at DESC "
            "LIMIT ?", (count,)).fetchall()
    return [_row_to_campaign(row) for row in rows]


def delete_campaign(campaign_id: str) -> bool:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        _ensure(db)
        changed = db.execute(
            "DELETE FROM campaigns WHERE campaign_id=?",
            (str(campaign_id or "").strip()[:80],)).rowcount
    return bool(changed)


# -- live derivation (view only, no stored game truth) ------------------

def campaign_detail(campaign: Campaign) -> dict:
    """Full derived campaign view: per-quest states, counts,
    current quest, next actionable item, evidence links."""
    from .quests import get_quest, quest_detail
    quest_views: list[dict] = []
    for quest_id in campaign.quest_ids:
        try:
            quest = get_quest(quest_id)
        except Exception:
            quest = None
        if quest is None:
            quest_views.append({
                "quest_id": quest_id, "title": "(quest removed)",
                "state": "MISSING", "done": 0, "total": 0,
                "progress": "0/0", "steps": [],
                "href": "/quests"})
            continue
        try:
            detail = quest_detail(quest)
        except Exception:
            detail = {"quest_id": quest_id,
                      "title": quest.title, "state": "WAITING",
                      "done": 0, "total": len(quest.steps),
                      "progress": f"0/{len(quest.steps)}",
                      "steps": []}
        detail["href"] = f"/quests#{quest_id}"
        quest_views.append(detail)
    completed = sum(1 for view in quest_views
                    if view.get("state") == "COMPLETED")
    blocked = sum(1 for view in quest_views
                  if view.get("state") in ("BLOCKED", "FAILED"))
    waiting = sum(1 for view in quest_views
                  if view.get("state") in ("WAITING", "MISSING"))
    current = next((view for view in quest_views
                    if view.get("state") not in
                    ("COMPLETED",)), {})
    next_action: dict = {}
    for view in quest_views:
        if view.get("state") in ("COMPLETED",):
            continue
        for step in view.get("steps", []):
            if step.get("state") in (
                    "WAITING", "MISSING", "BLOCKED", "FAILED",
                    "ACTIVE"):
                next_action = {
                    "quest_id": view.get("quest_id", ""),
                    "quest_title": view.get("title", "")[:120],
                    "step": step.get("label", "")[:120],
                    "href": step.get("href", "/quests"),
                    "readiness": step.get("readiness", ""),
                    "readiness_reason": step.get(
                        "readiness_reason", "")[:200],
                }
                break
        if next_action:
            break
    if completed and completed == len(quest_views):
        level = "COMPLETED"
    elif blocked:
        level = "BLOCKED"
    elif any(view.get("state") == "ACTIVE"
             for view in quest_views):
        level = "ACTIVE"
    elif waiting or not quest_views:
        level = "WAITING"
    else:
        level = "READY"
    return {
        "campaign_id": campaign.campaign_id,
        "title": campaign.title,
        "description": campaign.description,
        "state": level,
        "quests": quest_views,
        "current_quest": {
            "quest_id": current.get("quest_id", ""),
            "title": current.get("title", "")[:120],
            "state": current.get("state", ""),
            "progress": current.get("progress", "0/0"),
            "href": current.get("href", "/quests"),
        } if current else {},
        "completed_count": completed,
        "total_count": len(quest_views),
        "blocked_count": blocked,
        "waiting_count": waiting,
        "next_action": next_action,
        "evidence": [
            {"label": f"{view.get('title', '')[:80]} "
                      f"({view.get('progress', '0/0')})",
             "href": view.get("href", "/quests")}
            for view in quest_views],
        "provenance": {"source_type": "derived",
                       "creator_id": "quest-campaigns",
                       "human_verified": False},
    }


def list_campaign_details(limit: int = 50) -> list[dict]:
    return [campaign_detail(campaign)
            for campaign in list_campaigns(limit=limit)]


def _audit(event_type: str, summary: str, *,
           payload: dict | None = None) -> None:
    try:
        from .events import new_event, save_event
        save_event(new_event(event_type, summary,
                             payload=payload or {}))
    except Exception:
        pass
