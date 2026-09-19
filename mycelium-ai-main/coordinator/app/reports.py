"""Deterministic report blocks (BIG #10, deel 12).

Generic assembly for personalized reports (morning reports
later): bounded sections composed from caller-supplied data.
No Garmin, no health engine here — the engine only combines
whatever bounded blocks the caller provides, deterministically
(same inputs, same report).

A block: {title, items[]} with items as short capped strings.
A report: {report_id, generated_at, sections[], provenance}.
"""

import secrets
import time
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MAX_BLOCKS = 24
MAX_ITEMS_PER_BLOCK = 15
MAX_ITEM_CHARS = 300
MAX_TITLE_CHARS = 120


class ReportRefusedError(ValueError):
    """Local validation refused; nothing was assembled."""


class ReportBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    items: list[str] = Field(default_factory=list,
                             max_length=MAX_ITEMS_PER_BLOCK)


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=3, max_length=80)
    generated_at: str = ""
    sections: list[ReportBlock] = Field(default_factory=list,
                                        max_length=MAX_BLOCKS)
    provenance: dict[str, Any] = Field(default_factory=dict)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_block(title: str, items) -> ReportBlock:
    """One bounded block from raw items (anything stringable)."""
    if not isinstance(title, str) or not title.strip():
        raise ReportRefusedError("Block needs a title")
    cleaned: list[str] = []
    for item in (items or [])[:MAX_ITEMS_PER_BLOCK]:
        if isinstance(item, dict):
            text = str(item.get("title",
                                item.get("summary",
                                         item.get("label", ""))))
        else:
            text = str(item or "")
        text = text.strip()
        if text:
            cleaned.append(text[:MAX_ITEM_CHARS])
    return ReportBlock(title=title.strip()[:MAX_TITLE_CHARS],
                       items=cleaned)


def assemble_report(blocks: list[tuple[str, Any]]) -> Report:
    """Deterministic assembly: same blocks in, same report out."""
    if not isinstance(blocks, (list, tuple)):
        raise ReportRefusedError("Report needs a block list")
    if len(blocks) > MAX_BLOCKS:
        raise ReportRefusedError(
            f"at most {MAX_BLOCKS} sections")
    sections = []
    for entry in blocks:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise ReportRefusedError(
                "Each section must be (title, items)")
        sections.append(make_block(entry[0], entry[1]))
    return Report(
        report_id=f"rpt_{int(time.time() * 1000):x}"
                  f"{secrets.token_hex(3)}",
        generated_at=now(), sections=sections,
        provenance={"source_type": "sensor-observed",
                    "creator_id": "report-engine",
                    "human_verified": False})


def morning_report(sections: dict) -> Report:
    """Morning-report template over named bounded sources.
    V1 adds waiting + agenda; BIG #42 adds hardware, quests,
    energy, finance (projects already existed). Each loads on
    its own, none dumps context. Unknown keys refuse (no
    silent scope creep)."""
    allowed = ("today", "health", "recovery", "projects",
               "tasks", "missions", "waiting", "agenda", "skills",
               "inventory", "workshop", "research", "fabrication",
               "devices", "findings", "suggestions", "fun",
               "automation", "presence_needs",
               "presence_overnight", "presence_discoveries",
               "presence_resources", "presence_blocked",
               "presence_offline", "presence_next",
               "hardware", "quests", "energy", "finance",
               # BIG #43 living game layer (additive).
               "campaigns")
    if not isinstance(sections, dict):
        raise ReportRefusedError("Morning report needs an object")
    unknown = set(sections) - set(allowed)
    if unknown:
        raise ReportRefusedError(
            f"Unknown report sections: {sorted(unknown)}")
    titles = {"today": "Today", "health": "Health",
              "recovery": "Recovery", "projects": "Projects",
              "tasks": "Tasks", "missions": "Missions",
              "waiting": "Waiting for you", "agenda": "Agenda",
              "skills": "Skills", "inventory": "Inventory",
              "workshop": "Workshop", "research": "Research",
              "fabrication": "Fabrication", "devices": "Devices",
               "findings": "Watcher findings",
                "suggestions": "Suggestions", "fun": "Fun",
                "automation": "Automation",
                "presence_needs": "Needs you",
                "presence_overnight": "Overnight changes",
                "presence_discoveries": "Discoveries",
                "presence_resources": "Available resources",
                "presence_blocked": "Blocked work",
                "presence_offline": "Offline and stale hardware",
                "presence_next": "Suggested next actions",
                "hardware": "Hardware verification",
                "quests": "Quest trails",
                "energy": "Energy",
                "finance": "Finance",
                "campaigns": "Current campaign"}
    return assemble_report([(titles[key], sections[key])
                            for key in allowed
                            if key in sections])
