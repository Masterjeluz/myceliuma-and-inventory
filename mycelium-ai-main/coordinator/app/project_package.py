"""Project-aware context packages (BIG #5).

One bounded question — "what are we building?" — answered from
live sources without dumping anything:

    Project
    +-- directly related INVENTory entities (bounded retrieval)
    +-- relevant missions (Mycelium-owned, bounded)
    +-- recent events (bounded)
    +-- git context (read-only status/branch, no diff contents)
    +-- provenance (every record keeps its source/verification)

INVENTory stays source of truth for world entities; Mycelium
stays owner of missions/agent/coordinator/conversational state.
This module never merges them into a new store — it projects a
compact, read-only package for reasoning, and the package is
never a permission for anything.

Bounds (tested):

- entities <= 10, missions <= 5, events <= 10, files listed by
  name only (never contents);
- no secrets: values whose keys look like credentials are
  dropped, absolute paths are redacted to $PROJECT;
- retrieval reuses hybrid_retrieve() with automatic lexical
  fallback — a missing embedding model never fails packaging.
"""

import os
import re
from typing import Any

SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|token|secret|password|passwd|credential|"
    r"private[_-]?key|auth)",
    re.IGNORECASE,
)

MAX_ENTITIES = 10
MAX_MISSIONS = 5
MAX_EVENTS = 10
MAX_FILES = 10
MAX_TEXT_CHARS = 500


def redact_path(text: str, repo_root: str = "") -> str:
    """Replace absolute local paths with $PROJECT. No sensitive
    absolute paths ever reach model context."""
    if not isinstance(text, str) or not text:
        return text
    redacted = text
    home = os.path.expanduser("~")
    if home and home in redacted:
        redacted = redacted.replace(home, "$HOME")
    if repo_root and repo_root in redacted:
        redacted = redacted.replace(repo_root, "$PROJECT")
    return redacted


def _clean_text(value, repo_root: str = "") -> str:
    text = str(value or "")[:MAX_TEXT_CHARS]
    return redact_path(text, repo_root)


def _clean_record(record: dict, repo_root: str = "") -> dict:
    """One entity summary: identity + snippet + provenance only."""
    provenance = record.get("provenance", {})
    if hasattr(provenance, "model_dump"):
        provenance = provenance.model_dump(mode="json")
    if not isinstance(provenance, dict):
        provenance = {}
    return {
        "entity_type": str(record.get("entity_type", "unknown")),
        "entity_id": str(record.get("entity_id", "")),
        "title": _clean_text(record.get("title", ""), repo_root),
        "snippet": _clean_text(record.get("snippet", ""), repo_root),
        "match_type": str(record.get("match_type", "lexical")),
        "provenance": {
            "source_type": str(provenance.get("source_type", "unknown")),
            "human_verified": bool(provenance.get(
                "human_verified", False)),
        },
    }


def _clean_mission(mission, repo_root: str = "") -> dict:
    status = mission.get("status", "") if isinstance(mission, dict) \
        else getattr(mission, "status", "")
    goal = mission.get("goal", "") if isinstance(mission, dict) \
        else getattr(mission, "goal", "")
    mission_id = mission.get("mission_id", "") \
        if isinstance(mission, dict) \
        else getattr(mission, "mission_id", "")
    steps: list[dict] = []
    raw_steps = mission.get("steps", []) if isinstance(mission, dict) \
        else getattr(mission, "steps", [])
    for step in list(raw_steps)[:10]:
        if isinstance(step, dict):
            steps.append({
                "description": _clean_text(
                    step.get("description", ""), repo_root),
                "kind": str(step.get("kind", "")),
                "status": str(step.get("status", "")),
            })
        else:
            steps.append({
                "description": _clean_text(
                    getattr(step, "description", ""), repo_root),
                "kind": str(getattr(step, "kind", "")),
                "status": str(getattr(step, "status", "")),
            })
    return {"mission_id": str(mission_id),
            "goal": _clean_text(goal, repo_root),
            "status": str(status), "steps": steps}


def _clean_event(event: dict, repo_root: str = "") -> dict:
    return {
        "event_type": str(event.get("event_type", "")),
        "message": _clean_text(event.get("message", ""), repo_root),
        "mission_id": str(event.get("mission_id", "")),
        "created_at": str(event.get("created_at", "")),
    }


def _clean_git(git: dict, repo_root: str = "") -> dict:
    if not isinstance(git, dict):
        return {}
    lines = [redact_path(str(line), repo_root)
             for line in list(git.get("lines", []))[:20]]
    return {
        "branch": str(git.get("branch", ""))[:120],
        "changed_files": len(lines),
        "clean": not lines,
    }


def _drop_secrets(mapping: dict) -> dict:
    """Remove anything whose key smells like a credential."""
    return {key: value for key, value in mapping.items()
            if not SECRET_KEY_PATTERN.search(str(key))}


def build_project_package(project, *, entities: list[dict] | None = None,
                          missions: list | None = None,
                          events: list[dict] | None = None,
                          git: dict | None = None,
                          files: list[dict] | None = None,
                          retrieval_mode: str = "lexical") -> dict:
    """Assemble one bounded, read-only project package (pure)."""
    if hasattr(project, "model_dump"):
        project_data = project.model_dump(mode="json")
    elif isinstance(project, dict):
        project_data = _drop_secrets(dict(project))
    else:
        raise ValueError("Project package needs a project context")
    repo_root = str(project_data.get("repository", ""))
    package = {
        "project_id": str(project_data.get("project_id", "")),
        "name": str(project_data.get("name", ""))[:120],
        "repository": redact_path(repo_root, repo_root),
        "retrieval_mode": retrieval_mode,
        "entities": [_clean_record(record, repo_root)
                     for record in list(entities or [])[:MAX_ENTITIES]],
        "missions": [_clean_mission(mission, repo_root)
                     for mission in list(missions or [])[:MAX_MISSIONS]],
        "events": [_clean_event(event, repo_root)
                   for event in list(events or [])[:MAX_EVENTS]],
        "git": _clean_git(git or {}, repo_root),
        "files": [{"name": str(item.get("name", ""))[:200]}
                  for item in list(files or [])[:MAX_FILES]],
        "provenance": {
            "source_type": "user-created",
            "human_verified": False,
            "notes": "bounded read-only projection; "
                     "not a permission for anything",
        },
    }
    return package


def summarize_for_chat(package: dict) -> str:
    """Two-to-five-line preamble answering 'what are we building?'."""
    lines = [f"Actief project: {package.get('name', '?')}"]
    entities = package.get("entities", [])
    if entities:
        lines.append(f"Gerelateerd uit INVENTory ({len(entities)}):")
        for entity in entities[:5]:
            verified = "✓" if entity.get("provenance", {}).get(
                "human_verified") else "○"
            lines.append(f"{verified} [{entity.get('entity_type')}] "
                         f"{entity.get('title')} "
                         f"({entity.get('entity_id')})")
    missions = [mission for mission in package.get("missions", [])
                if mission.get("status") not in ("completed", "cancelled")]
    if missions:
        lines.append("Open missies:")
        for mission in missions[:3]:
            lines.append(f"- {mission.get('goal', '')} "
                         f"[{mission.get('status', '')}]")
    git = package.get("git", {})
    if git:
        state = "schoon" if git.get("clean") else (
            f"{git.get('changed_files', 0)} gewijzigde bestanden")
        lines.append(f"Git ({git.get('branch', '?')}): {state}.")
    lines.append("Details staan in INVENTory; dit is context, "
                 "geen toestemming.")
    return "\n".join(lines)


async def assemble_project_package(project, reader, *,
                                   query: str = "",
                                   missions: list | None = None,
                                   events: list[dict] | None = None,
                                   git: dict | None = None,
                                   embedder=None,
                                   mode: str = "hybrid",
                                   limit: int = 10) -> dict:
    """Live assembly: project + retrieval + overlays, all bounded.

    Retrieval failures degrade to an empty entity list (lexical
    fallback lives inside hybrid_retrieve); packaging never raises
    for missing world data.
    """
    from .retrieval import hybrid_retrieve
    entities: list[dict] = []
    used_mode = "lexical"
    needle = (query or "").strip()
    if needle:
        try:
            found = await hybrid_retrieve(
                needle[:200], reader, embedder, mode=mode,
                limit=max(1, min(limit, MAX_ENTITIES)))
            entities = found.get("results", [])
            used_mode = found.get("mode_used", mode)
        except (ValueError, RuntimeError):
            entities = []
    return build_project_package(
        project, entities=entities, missions=missions, events=events,
        git=git, retrieval_mode=used_mode)
