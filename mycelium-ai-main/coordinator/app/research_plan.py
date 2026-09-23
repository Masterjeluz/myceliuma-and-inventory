"""Research Plan Bridge: research dossier -> proposed mission plan (V1).

Bridges completed research (ResearchDossier / ResearchRun) to the existing
mission execution plane (BIG #3 / H1 / H3).

Rules & Safety Boundaries:
- Every proposed mission begins strictly as 'pending_approval'.
- Research NEVER approves itself: approval requires an exact human 'YES'.
- Safe kinds only: research (with optional H1 dispatch) and analysis.
- Absolutely forbidden in generated missions: desktop, write, physical_print,
  fabricate, slice, camera_observe, or other physical/writing actions.
- dispatch=True stages only existing research.fetch_url tasks onto the queue.
- Idempotent: repeated calls for the same research return the existing active
  mission without creating duplicate missions.
- Provenance: source_type='external-source', human_verified=False,
  creator_id='research:{dossier_id}'.
- Source URLs: strictly HTTP/HTTPS from the dossier, capped at 6.
  Analysis-only fallback if no usable URLs exist.
"""

import logging
from typing import Any

from .conversations import generate_conversation_id
from .inventory_read import Provenance
from .missions import (
    Mission,
    TERMINAL_MISSION_STATUSES,
    generate_mission_id,
    list_missions,
    new_event,
    new_mission,
    save_event,
    save_mission,
)
from .research_engine import (
    ResearchDossier,
    ResearchRun,
    dossier_for_run,
    load_dossier,
    load_run,
)

logger = logging.getLogger("mycelium.research_plan")

MAX_DISPATCH_URLS = 6
FORBIDDEN_STEP_KINDS = frozenset({
    "desktop", "write", "physical_print", "fabricate", "slice",
    "camera_observe",
})


def resolve_dossier_and_run(research_id: str) -> tuple[ResearchDossier, ResearchRun]:
    """Resolve (dossier, run) from either a res_ run_id or dos_ dossier_id.

    Raises LookupError if the entity cannot be found at all.
    Raises ValueError if a run exists but has no completed dossier yet.
    """
    clean_id = (research_id or "").strip()
    if not clean_id:
        raise ValueError("research_id must be non-empty text")

    dossier: ResearchDossier | None = None
    run: ResearchRun | None = None

    if clean_id.startswith("dos_"):
        dossier = load_dossier(clean_id)
        if dossier is not None:
            run = load_run(dossier.run_id)
            if run is None:
                # Fallback minimal run record if run was not stored separately
                run = ResearchRun(
                    run_id=dossier.run_id,
                    question=dossier.question,
                    status="completed",
                    execution_state=dossier.execution_state,
                    dossier_id=dossier.dossier_id,
                    created_at=dossier.created_at,
                )
    elif clean_id.startswith("res_"):
        run = load_run(clean_id)
        if run is not None:
            if run.dossier_id:
                dossier = load_dossier(run.dossier_id)
            if dossier is None:
                dossier = dossier_for_run(run.run_id)
    else:
        # Try both without prefix assumption
        dossier = load_dossier(clean_id)
        if dossier is not None:
            run = load_run(dossier.run_id)
        else:
            run = load_run(clean_id)
            if run is not None:
                dossier = (
                    load_dossier(run.dossier_id)
                    if run.dossier_id
                    else dossier_for_run(run.run_id)
                )

    if dossier is None and run is None:
        raise LookupError(f"Research entity '{clean_id}' not found")
    if dossier is None:
        raise ValueError(f"Research run '{clean_id}' has no completed dossier")
    if run is None:
        run = ResearchRun(
            run_id=dossier.run_id,
            question=dossier.question,
            status="completed",
            execution_state=dossier.execution_state,
            dossier_id=dossier.dossier_id,
            created_at=dossier.created_at,
        )

    return dossier, run


def extract_dispatchable_urls(dossier: ResearchDossier | dict[str, Any]) -> list[str]:
    """Extract valid HTTP/HTTPS URLs present in the dossier sources (max 6).

    Excludes non-http schemes, whitespace-containing strings, and duplicates.
    Never invents URLs.
    """
    sources = (
        dossier.sources
        if hasattr(dossier, "sources")
        else dossier.get("sources", [])
    )
    if not isinstance(sources, list):
        return []

    seen: set[str] = set()
    valid_urls: list[str] = []

    for item in sources:
        if len(valid_urls) >= MAX_DISPATCH_URLS:
            break
        raw_url = ""
        if isinstance(item, dict):
            raw_url = str(item.get("url", "") or "")
        elif hasattr(item, "url"):
            raw_url = str(getattr(item, "url", "") or "")

        candidate = raw_url.strip()
        if not candidate or candidate in seen:
            continue
        lowered = candidate.lower()
        if not (lowered.startswith("http://") or lowered.startswith("https://")):
            continue
        if any(c.isspace() for c in candidate):
            continue
        if len(candidate) > 2000:
            continue

        seen.add(candidate)
        valid_urls.append(candidate)

    return valid_urls


def generate_mission_steps_from_dossier(
    dossier: ResearchDossier | dict[str, Any],
    run: ResearchRun | dict[str, Any] | None = None,
    *,
    dispatch: bool = True,
    source_urls: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Generate safe mission steps for a research dossier.

    When dispatchable URLs exist and dispatch=True:
      Step 1: research step with dispatch=True & source_urls (H1 dispatchable)
      Step 2: analysis step evaluating findings (safe subsequent step)

    Fallback (no URLs or dispatch=False):
      Step 1: safe analysis-only step over existing dossier findings.

    Never generates forbidden kinds (desktop, write, physical_print, fabricate,
    slice, camera_observe).
    """
    question = ""
    if hasattr(dossier, "question"):
        question = dossier.question
    elif isinstance(dossier, dict):
        question = str(dossier.get("question", "") or "")
    if not question and run is not None:
        if hasattr(run, "question"):
            question = run.question
        elif isinstance(run, dict):
            question = str(run.get("question", "") or "")

    question = (question or "Onderzoeksvraag").strip()[:500]

    # Resolve URLs: if caller explicitly supplied source_urls, filter against dossier URLs
    dossier_urls = extract_dispatchable_urls(dossier)
    if source_urls is not None:
        dossier_url_set = set(dossier_urls)
        urls = [u.strip() for u in source_urls if u.strip() in dossier_url_set][:MAX_DISPATCH_URLS]
    else:
        urls = dossier_urls

    steps: list[dict[str, Any]] = []

    if dispatch and urls:
        research_step = {
            "kind": "research",
            "description": f"Onderzoek bronnen ophalen via nodes ({len(urls)} URL{'s' if len(urls) > 1 else ''})",
            "parameters": {
                "question": question[:500],
                "source_urls": urls,
                "dispatch": True,
            },
            "required_capabilities": ["research.fetch"],
            "requires_approval": False,
        }
        analysis_step = {
            "kind": "analysis",
            "description": f"Analyseer bevindingen en synthese voor: {question[:80]}",
            "parameters": {
                "question": f"Beoordeel de opgehaalde bronnen en synthese voor de onderzoeksvraag: {question[:200]}",
            },
            "required_capabilities": [],
            "requires_approval": False,
        }
        steps = [research_step, analysis_step]
    else:
        # Safe analysis-only fallback
        analysis_step = {
            "kind": "analysis",
            "description": f"Analyseer dossierbevindingen en open vragen voor: {question[:80]}",
            "parameters": {
                "question": f"Analyseer het onderzoeksdossier en openstaande vragen voor: {question[:200]}",
            },
            "required_capabilities": [],
            "requires_approval": False,
        }
        steps = [analysis_step]

    # Safety assertion: verify no forbidden kind is ever emitted
    for step in steps:
        if step["kind"] in FORBIDDEN_STEP_KINDS:
            raise ValueError(f"Forbidden step kind '{step['kind']}' generated")

    return steps


def find_active_mission_for_research(
    dossier_id: str, run_id: str = ""
) -> Mission | None:
    """Find any currently active mission linked to this dossier or run."""
    clean_dossier = (dossier_id or "").strip()
    clean_run = (run_id or "").strip()

    for mission in list_missions(limit=100):
        if mission.status in TERMINAL_MISSION_STATUSES:
            continue
        meta = mission.metadata or {}
        if clean_dossier and (
            meta.get("research_dossier_id") == clean_dossier
            or mission.provenance.creator_id == f"research:{clean_dossier}"
        ):
            return mission
        if clean_run and meta.get("research_run_id") == clean_run:
            return mission
    return None


def propose_research_mission(
    research_id: str,
    *,
    conversation_id: str | None = None,
    goal: str | None = None,
    dispatch: bool = True,
    max_steps: int = 10,
    source_urls: list[str] | None = None,
) -> tuple[Mission, bool]:
    """Propose an inert mission plan from a research dossier or run.

    Returns:
        tuple[Mission, bool]: (mission, is_new) where is_new is False if an
        existing active mission was returned (idempotency).

    Safety:
        - Mission begins in 'pending_approval'.
        - Requires an explicit human YES to approve.
        - Provenance is marked external-source, human_verified=False.
    """
    dossier, run = resolve_dossier_and_run(research_id)

    # 1. Idempotency check: return active existing mission if one exists
    existing = find_active_mission_for_research(dossier.dossier_id, run.run_id)
    if existing is not None:
        logger.info(
            "propose_research_mission: returning existing active mission %s for %s",
            existing.mission_id,
            dossier.dossier_id,
        )
        return existing, False

    # 2. Build steps
    steps = generate_mission_steps_from_dossier(
        dossier, run, dispatch=dispatch, source_urls=source_urls
    )

    # 3. Determine goal and conversation
    resolved_goal = (goal or "").strip()
    if not resolved_goal:
        resolved_goal = f"Onderzoek opvolging: {dossier.question}"
    resolved_goal = resolved_goal[:500]

    conv_id = (conversation_id or "").strip()
    if not conv_id:
        conv_id = generate_conversation_id()

    # 4. Construct mission in pending_approval state
    mission_id = generate_mission_id()
    mission = new_mission(
        mission_id=mission_id,
        conversation_id=conv_id,
        goal=resolved_goal,
        steps_data=steps,
        max_steps=max(1, min(int(max_steps or 10), 20)),
        status="pending_approval",
    )

    # 5. Attach external-source provenance & research metadata
    provenance = Provenance(
        source_type="external-source",
        creator_id=f"research:{dossier.dossier_id}",
        human_verified=False,
        notes=f"Proposed mission from research dossier {dossier.dossier_id}",
    )
    mission = mission.model_copy(
        update={
            "provenance": provenance,
            "metadata": {
                **mission.metadata,
                "research_dossier_id": dossier.dossier_id,
                "research_run_id": run.run_id,
                "research_id": research_id.strip(),
                "source_urls": extract_dispatchable_urls(dossier),
            },
        }
    )

    save_mission(mission)
    save_event(
        new_event(
            mission.conversation_id,
            "mission_created",
            f"Onderzoeksmissie voorgesteld voor dossier {dossier.dossier_id} "
            f"met {len(mission.steps)} stap(pen). Goedkeuring vereist.",
            mission_id=mission.mission_id,
        )
    )

    logger.info(
        "propose_research_mission: created mission %s for dossier %s (pending_approval)",
        mission.mission_id,
        dossier.dossier_id,
    )
    return mission, True
