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


# -- foundation seeds (data-only, idempotent) ---------------------------
#
# First real product loop: "Documenteer één object".
# Quests reference REAL work only and claim no progress: every
# step starts unlinked (MISSING/WAITING) until a real record
# exists. Completion derives live via quests.quest_detail /
# campaign_detail — no stored progress, no XP.
#
# Quest 1 uses a task-kind step as completion source (never an
# entity-step: those stay WAITING by design). The obj_/file_
# records are evidence, not a forced entity-completion.

FOUNDATION_QUEST_TITLES = (
    "Documenteer één object",
    "Repareer/hergebruik iets + foto-bewijs",
    "Inbox legen via poll",
    "Observatie beschrijven",
    "Kandidaat reviewen",
    "Mycelium D: documenteer",
    "Mycelium E: verifieer",
    "Mycelium F: kweek",
    "Mycelium G: oogst",
    "Mycelium H: deel",
)

FOUNDATION_CAMPAIGN_TITLES = (
    "🌱 Solar Punk Foundation",
    "👁 Observation Inbox",
    "🧠 Improve Mycelium D–H",
)


def _find_quest_by_title(title: str):
    from .quests import list_quests
    for quest in list_quests(limit=100):
        if quest.title == title:
            return quest
    return None


def _find_campaign_by_title(title: str):
    for campaign in list_campaigns(limit=100):
        if campaign.title == title:
            return campaign
    return None


def ensure_foundation_seeds() -> dict:
    """Create (or reuse) the foundation quests + campaigns.

    Idempotent by title: re-runs return the existing defs.
    Every quest holds task-kind steps with empty refs — no
    fake progress. Callers link a step to a real completed
    task (via quests.get_quest/save_quest) to derive
    COMPLETE honestly.
    """
    from .quests import new_quest, save_quest
    quest_ids: dict[str, str] = {}
    for title in FOUNDATION_QUEST_TITLES:
        existing = _find_quest_by_title(title)
        if existing is not None:
            quest_ids[title] = existing.quest_id
            continue
        key = title.lower().replace(" ", "-")[:40]
        quest = new_quest(title, [{
            "key": key or "stap",
            "label": title,
            "kind": "task",
            "ref": "",
        }])
        save_quest(quest)
        quest_ids[title] = quest.quest_id
    campaign_ids: dict[str, str] = {}
    groups = {
        FOUNDATION_CAMPAIGN_TITLES[0]: [
            "Documenteer één object",
            "Repareer/hergebruik iets + foto-bewijs",
        ],
        FOUNDATION_CAMPAIGN_TITLES[1]: [
            "Inbox legen via poll",
            "Observatie beschrijven",
            "Kandidaat reviewen",
        ],
        FOUNDATION_CAMPAIGN_TITLES[2]: [
            "Mycelium D: documenteer",
            "Mycelium E: verifieer",
            "Mycelium F: kweek",
            "Mycelium G: oogst",
            "Mycelium H: deel",
        ],
    }
    for title, quest_titles in groups.items():
        existing = _find_campaign_by_title(title)
        if existing is not None:
            campaign_ids[title] = existing.campaign_id
            continue
        campaign = new_campaign(
            title, [quest_ids[name] for name in quest_titles],
            description=f"Foundation seed: {title}")
        save_campaign(campaign)
        campaign_ids[title] = campaign.campaign_id
    return {"quests": quest_ids, "campaigns": campaign_ids}


# -- mission seeds (data-only, idempotent) ----------------------------
#
# Beschikbare game-content als draft-missies + koppelende quests:
# geen voortgang, geen uitvoering, geen approval. Draft = AVAILABLE.
# Quest-stappen verwijzen naar echte mission_id's en blijven WAITING
# tot een missie echt loopt. Toekomstige capabilities staan expliciet
# als [FUTURE] in goal + context — nooit als werkende functie.

MISSION_SEEDS = (
    ("Documenteer één object",
     "analyze_problem",
     "Fotografeer een echt object en documenteer het via de "
     "bestaande vision/inventory-pipeline (poll → VLM → review → "
     "YES → execute → verify). Start via de bestaande flows; "
     "niets loopt automatisch.",
     "READY"),
    ("Maak je eerste werkplaats",
     "investigate_inventory",
     "Onderzoek met bestaande INVENTory/hardware/projectdata welke "
     "fysieke middelen beschikbaar zijn als voorbereiding op een "
     "toekomstige workshop/forge. Voorlopig research/planning.",
     "READY"),
    ("Bouw een kaartscanner",
     "prepare_build_plan",
     "Onderzoek en ontwerp een machine die trading cards invoert, "
     "positioneert, fotografeert en herkent. Eindigt voorlopig in "
     "research-dossier, ontwerp, componenten, 3D-model en prototype; "
     "YOLO/OCR/hardware worden nu niet gebouwd.",
     "READY"),
    ("Laat Luma je video begrijpen [FUTURE]",
     "research_topic",
     "Concept: rally/service/punt-detectie en montagevoorstellen uit "
     "bijv. Insta360-volleybalbeelden. VIDEO/360°-processing bestaat "
     "nog niet — alleen het concept is zichtbaar, geen werkende functie.",
     "FUTURE"),
    ("Start een levende kwekerij",
     "research_topic",
     "Inventariseer met bestaande research/project-systemen wat nodig "
     "is voor vocht/voeding/licht/temperatuur-monitoring en latere "
     "sensor→analyse→approval→actuator→verificatie. Geen fake "
     "sensorwaarden.",
     "READY"),
    ("Geef je computer werk",
     "investigate_inventory",
     "Onderzoek welke lokale compute beschikbaar is (nodes, modellen) "
     "als voorbereiding op veilige bounded taken "
     "(research/code/test/documentatie). Geen autonome shell-acties.",
     "READY"),
)

MISSION_SEED_CAMPAIGN = "🧭 Beschikbare missies"


def ensure_mission_seeds() -> dict:
    """Create (or reuse) draft-missies + koppelquests + campaign.

    Idempotent op exact goal/titel. Draft-missies claimen geen
    voortgang; quests derivieren WAITING tot echt werk loopt.
    """
    from .missions import (generate_mission_id, list_missions,
                           new_mission, save_mission)
    from .mission_templates import instantiate
    from .quests import get_quest, new_quest, save_quest
    try:
        existing = {str(m.goal): str(m.mission_id)
                    for m in list_missions(limit=200) or []}
    except Exception:
        existing = {}
    mission_ids: dict[str, str] = {}
    for title, template_id, context, _state in MISSION_SEEDS:
        if title in existing:
            mission_ids[title] = existing[title]
            continue
        steps, max_steps = instantiate(template_id, title)
        mission = new_mission(
            generate_mission_id(), "seed-content", title,
            steps, max_steps=max_steps,
            context_records=[{"note": context[:500]}],
            status="draft")
        save_mission(mission)
        mission_ids[title] = mission.mission_id
    quest_ids: dict[str, str] = {}
    for title, _template_id, _context, _state in MISSION_SEEDS:
        quest_title = f"Missie: {title}"
        found = _find_quest_by_title(quest_title)
        if found is not None:
            quest_ids[title] = found.quest_id
            continue
        quest = new_quest(quest_title, [{
            "key": "missie",
            "label": quest_title,
            "kind": "mission",
            "ref": mission_ids[title],
        }])
        save_quest(quest)
        quest_ids[title] = quest.quest_id
    campaign_title = MISSION_SEED_CAMPAIGN
    campaign_ids: dict[str, str] = {}
    found_camp = _find_campaign_by_title(campaign_title)
    if found_camp is not None:
        campaign_ids[campaign_title] = found_camp.campaign_id
    else:
        campaign = new_campaign(
            campaign_title,
            [quest_ids[title] for title, _t, _c, _s in
             MISSION_SEEDS],
            description="Beschikbare missies als speelbare content; "
                        "draft = beschikbaar, geen voortgang.")
        save_campaign(campaign)
        campaign_ids[campaign_title] = campaign.campaign_id
    return {"missions": mission_ids, "quests": quest_ids,
            "campaigns": campaign_ids}


# -- fabrication seeds (data-only, idempotent) ------------------------
#
# Zelfde contract als mission-seeds: draft = AVAILABLE, quests WAITING,
# FUTURE/HARDWARE-gates expliciet in goal + context. De prototype-missie
# gebruikt alleen validerende stapkinds (readout/analysis/proposal/
# research); uitvoerbare stappen (fabricate/slice/print) ontstaan pas
# via bestaande flows met hun eigen gates.

FABRICATION_SEEDS = (
    ("Maak je eerste digitale prototype",
     None,
     "Kies een bestaand 3D-model, controleer het bestand, analyseer "
     "printbaarheid, maak een fabrication-plan. Menselijke goedkeuring, "
     "printjob-voorbereiding, hardwarestatus en verificatie volgen via "
     "bestaande flows met eigen gates — niets print automatisch.",
     "READY"),
    ("Onderzoek: wat kunnen we met onze A1 Mini maken?",
     "research_topic",
     "Verken welke objecten, materialen en profielen haalbaar zijn op "
     "een Bambu Lab A1 Mini. Printer is nog niet verbonden; status "
     "blijft eerlijk NOT CONNECTED tot een adapter bestaat.",
     "READY"),
    ("Maak een klein onderdeel voor een toekomstige solarpunk-machine",
     "prepare_build_plan",
     "Van idee naar bouwplan met bestaande project/materiaal-data. "
     "Uitvoering vereist aparte approvals per stap.",
     "READY"),
    ("Ontwerp een onderdeel voor de hydroponics-workshop",
     "research_topic",
     "Onderzoek welke onderdelen een toekomstige kweekopstelling nodig "
     "heeft (behuizing, goten, houders). Ontwerp-only; geen hardware.",
     "READY"),
)

FABRICATION_SEED_CAMPAIGN = "🔧 Fabrication"


def _prototype_steps() -> list[dict]:
    return [
        {"kind": "readout",
         "description": "Kies een bestaand 3D-model uit de workbench",
         "parameters": {"source": "inventory", "q": "3d model"}},
        {"kind": "readout",
         "description": "Controleer bestand (grootte, hash, formaat)",
         "parameters": {"source": "inventory", "q": "model file"}},
        {"kind": "analysis",
         "description": "Analyseer printbaarheid (mesh-verdict, formaat)",
         "parameters": {}},
        {"kind": "proposal",
         "description": "Stel fabrication-plan op",
         "parameters": {"proposal": "fabrication-plan"}},
        {"kind": "research",
         "description": "Onderzoek vereiste menselijke goedkeuring",
         "parameters": {"question": "welke approvals vereist een "
                                    "printjob", "max_sources": "3"}},
    ]


def ensure_fabrication_seeds() -> dict:
    """Create (or reuse) draft-fabricatiemissies + quests + campaign.

    Idempotent op exact goal/titel. Zelfde eerlijkheidscontract als
    ensure_mission_seeds.
    """
    from .missions import (generate_mission_id, list_missions,
                           new_mission, save_mission)
    from .mission_templates import instantiate
    from .quests import new_quest, save_quest
    try:
        existing = {str(m.goal): str(m.mission_id)
                    for m in list_missions(limit=200) or []}
    except Exception:
        existing = {}
    mission_ids: dict[str, str] = {}
    for title, template_id, context, _state in FABRICATION_SEEDS:
        if title in existing:
            mission_ids[title] = existing[title]
            continue
        if template_id is None:
            steps, max_steps = _prototype_steps(), 8
        else:
            steps, max_steps = instantiate(template_id, title)
        mission = new_mission(
            generate_mission_id(), "seed-content", title,
            steps, max_steps=max_steps,
            context_records=[{"note": context[:500]}],
            status="draft")
        save_mission(mission)
        mission_ids[title] = mission.mission_id
    quest_ids: dict[str, str] = {}
    for title, _template_id, _context, _state in FABRICATION_SEEDS:
        quest_title = f"Missie: {title}"
        found = _find_quest_by_title(quest_title)
        if found is not None:
            quest_ids[title] = found.quest_id
            continue
        quest = new_quest(quest_title, [{
            "key": "missie",
            "label": quest_title,
            "kind": "mission",
            "ref": mission_ids[title],
        }])
        save_quest(quest)
        quest_ids[title] = quest.quest_id
    campaign_title = FABRICATION_SEED_CAMPAIGN
    campaign_ids: dict[str, str] = {}
    found_camp = _find_campaign_by_title(campaign_title)
    if found_camp is not None:
        campaign_ids[campaign_title] = found_camp.campaign_id
    else:
        campaign = new_campaign(
            campaign_title,
            [quest_ids[title] for title, _t, _c, _s in
             FABRICATION_SEEDS],
            description="Fabrication-missies als speelbare content; "
                        "draft = beschikbaar, fysiek achter gates.")
        save_campaign(campaign)
        campaign_ids[campaign_title] = campaign.campaign_id
    return {"missions": mission_ids, "quests": quest_ids,
            "campaigns": campaign_ids}


def _audit(event_type: str, summary: str, *,
           payload: dict | None = None) -> None:
    try:
        from .events import new_event, save_event
        save_event(new_event(event_type, summary,
                             payload=payload or {}))
    except Exception:
        pass
