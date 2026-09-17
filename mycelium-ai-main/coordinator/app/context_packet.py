"""Universal context packet (BIG #30): model-agnostic context bridge.

Jelles can carry a Mycelium context to ChatGPT / Codex / OpenCode /
Ollama / Claude / Gemini / Antigravity / Google AI Studio — and bring
answers back via the conversation bridge. This module builds the packet:

- current goal / project, relevant entities (entity IDs, not just text)
- relevant memories (health explicitly scoped out unless requested)
- recent decisions, open tasks/missions, research dossiers
- conversation context (import or live chat), files, constraints
- provenance + current system state (nodes, approvals, capabilities)

Format: human-readable Markdown + JSON metadata. No external calls,
no secrets, bounded sizes. External AI advice never gains authority:
the advisor loop (advice -> candidate plan -> approval -> execution ->
verification) is documented, not executed here.
"""

from __future__ import annotations

import json as _json

PACKET_VERSION = "mycelium-context-packet/1"
MAX_SECTION_ITEMS = 15
MAX_TEXT_CHARS = 6000

ENTITY_ID_PREFIXES = (
    "obj_", "proj_", "idea_", "rel_", "evt_", "hw_", "sns_", "cam_",
    "loc_", "mod_", "task_", "act_", "file_", "mem_", "mission_",
    "conv_", "conv-",
)


def _clip(text: str, limit: int = 280) -> str:
    cleaned = " ".join(str(text or "").split())
    return cleaned[:limit]


def _is_entity_id(value: str) -> bool:
    text = str(value or "")
    return text.startswith(ENTITY_ID_PREFIXES) and 4 <= len(text) <= 100


def build_context_packet(*, goal: str = "", project_id: str = "",
                         conversation_id: str = "",
                         include_health: bool = False,
                         max_items: int = 10) -> dict:
    """Assemble a bounded, redacted context packet from live stores."""
    from . import conversation_bridge as _bridge
    limit = max(1, min(int(max_items or 10), MAX_SECTION_ITEMS))
    packet: dict = {
        "packet": PACKET_VERSION,
        "goal": _clip(goal, 500),
        "project_id": str(project_id or "")[:80],
        "conversation_id": str(conversation_id or "")[:80],
        "entities": [], "memories": [], "decisions": [],
        "open_missions": [], "research": [], "files": [],
        "constraints": [], "provenance": {},
        "system_state": {}, "warnings": [],
    }
    entity_ids: list[str] = []
    if project_id and _is_entity_id(project_id):
        entity_ids.append(project_id)
    memories: list[dict] = []
    try:
        from .memory import list_memories
        for entry in list_memories(limit=limit * 2):
            if entry.memory_type == "health" and not include_health:
                continue
            memories.append({
                "id": entry.memory_id, "type": entry.memory_type,
                "truth": entry.truth, "title": entry.title[:120],
                "project": entry.project_ref or "",
                "importance": round(float(entry.importance), 2)})
            for ref in (entry.entity_refs or [])[:5]:
                if _is_entity_id(str(ref)) and str(ref) not in entity_ids:
                    entity_ids.append(str(ref))
            if len(memories) >= limit:
                break
    except Exception:
        packet["warnings"].append("memories unavailable")
    if not include_health:
        packet["warnings"].append(
            "health explicitly scoped out of this packet")
    try:
        from .missions import list_missions
        for mission in list_missions(limit=limit):
            packet["open_missions"].append({
                "id": mission.mission_id, "goal": mission.goal[:200],
                "status": mission.status,
                "step": f"{mission.current_step}/{len(mission.steps)}"})
            for record in (mission.context_records or [])[:5]:
                ident = str(record.get("entity_id", ""))
                if _is_entity_id(ident) and ident not in entity_ids:
                    entity_ids.append(ident)
    except Exception:
        packet["warnings"].append("missions unavailable")
    try:
        from .research_engine import list_dossiers
        for dossier in list_dossiers(limit=limit):
            packet["research"].append({
                "id": dossier.dossier_id, "title": dossier.title[:140],
                "state": dossier.execution_state,
                "claims": len(dossier.claims),
                "open_questions": len(dossier.open_questions)})
    except Exception:
        packet["warnings"].append("research unavailable")
    if conversation_id:
        try:
            if conversation_id.startswith("conv_"):
                meta = _bridge.get_import(conversation_id)
                analysis = _bridge.load_analysis(conversation_id)
                if meta is not None:
                    packet["conversation"] = {
                        "id": conversation_id,
                        "title": meta.get("title", "")[:120],
                        "platform": meta.get("source_platform", ""),
                        "messages": meta.get("message_count", 0),
                        "findings": len((analysis or {}).get(
                            "findings", [])),
                    }
            else:
                from .database import chat_connection, init_chat_database
                init_chat_database()
                with chat_connection() as db:
                    rows = db.execute(
                        "SELECT role, content FROM messages WHERE "
                        "conversation_id=? ORDER BY created_at ASC "
                        "LIMIT ?", (conversation_id, limit)).fetchall()
                packet["conversation"] = {
                    "id": conversation_id, "turns": len(rows),
                    "excerpt": [_clip(f"{row['role']}: "
                                      f"{row['content']}", 200)
                                for row in rows[:6]],
                }
        except Exception:
            packet["warnings"].append("conversation context unavailable")
    packet["entities"] = [{"id": ident} for ident in entity_ids[:limit]]
    packet["constraints"] = [
        "human approves every mutation with exact YES",
        "advice is not truth; verification is separate",
        "no shell/RCE; nodes are pull-only",
        "INVENTory is read-only from here except gated writes",
        "health stays scoped; no diagnosis engine",
    ]
    packet["provenance"] = {
        "packet": PACKET_VERSION,
        "source_types": ["user-created", "verified", "observed",
                         "external-source", "ai-generated"],
        "note": "Entity IDs let any model refer to the same "
                "object/project/file. Text may drift; IDs persist.",
    }
    try:
        from . import main as _main
        status = _main.coordinator_status()
        packet["system_state"] = {
            "nodes_online": status["nodes"]["online"],
            "nodes_stale": status["nodes"]["stale"],
            "pending_approvals": status["pending_approvals"],
        }
    except Exception:
        packet["system_state"] = {}
    return packet


def render_markdown(packet: dict) -> str:
    """Human-readable packet with JSON metadata appended."""
    memories = packet.get("memories", [])[:10]
    missions = packet.get("open_missions", [])[:10]
    research = packet.get("research", [])[:10]
    lines = [
        "# MYCELIUM CONTEXT PACKET",
        "",
        f"version: {packet.get('packet', PACKET_VERSION)}",
        f"goal: {packet.get('goal') or '-'}",
        f"project: {packet.get('project_id') or '-'}",
        "",
        "## Entities (IDs persist across models)",
        ", ".join(item["id"] for item in packet.get("entities", []))
        or "-",
        "",
        "## Memories",
    ]
    lines.extend(
        f"- [{item['truth']}] {item['title']} ({item['id']})"
        for item in memories) or lines.append("-")
    lines.append("")
    lines.append("## Open missions")
    lines.extend(
        f"- {item['id']}: {item['goal']} [{item['status']}]"
        for item in missions) or lines.append("-")
    lines.append("")
    lines.append("## Research")
    lines.extend(
        f"- {item['id']}: {item['title']} [{item['state']}]"
        for item in research) or lines.append("-")
    lines.extend([
        "",
        "## Constraints",
    ])
    lines.extend(f"- {item}" for item in packet.get("constraints", []))
    lines.extend([
        "",
        "## Provenance",
        _clip(str(packet.get("provenance", {}).get(
            "note", "")), 400),
        "",
        "## System state",
        _json.dumps(packet.get("system_state", {}), indent=1)[:1000],
        "",
        "<!-- MYCELIUM-PACKET-JSON",
        _json.dumps(packet, indent=1)[:MAX_TEXT_CHARS],
        "-->",
    ])
    return "\n".join(lines)[: MAX_TEXT_CHARS + 2000]


def build_continuation(*, goal: str = "", project_id: str = "",
                       conversation_id: str = "",
                       next_step: str = "") -> dict:
    """'Continue this work' handoff: state/done/in-progress/remaining."""
    from . import conversation_bridge as _bridge
    packet = build_context_packet(
        goal=goal, project_id=project_id,
        conversation_id=conversation_id)
    done: list[str] = []
    in_progress: list[str] = []
    remaining: list[str] = []
    decisions: list[str] = []
    try:
        from .missions import list_missions
        for mission in list_missions(limit=10):
            steps = mission.steps or []
            finished = [step for step in steps
                        if str(getattr(step, "status", "")) == "done"]
            open_steps = [step for step in steps
                          if str(getattr(step, "status", "")) not in
                          ("done", "cancelled")]
            if mission.status in ("completed",):
                done.append(f"{mission.mission_id}: {mission.goal[:120]}")
            elif mission.status in ("running", "approved",
                                    "pending_approval", "paused"):
                in_progress.append(
                    f"{mission.mission_id}: {mission.goal[:120]} "
                    f"({len(finished)}/{len(steps)} steps done)")
                for step in open_steps[:5]:
                    remaining.append(
                        f"{mission.mission_id}: "
                        f"{str(getattr(step, 'description', ''))[:140]}")
    except Exception:
        pass
    if conversation_id.startswith("conv_"):
        try:
            for item in _bridge.missed_items(conversation_id)[:8]:
                remaining.append(f"missed: {item.get('text', '')[:140]} "
                                 f"(evidence: "
                                 f"{str(item.get('evidence', ''))[:80]})")
        except Exception:
            pass
    continuation = {
        "packet": "mycelium-continuation/1",
        "current_state": _clip(goal or "ongoing work", 300),
        "what_has_been_done": done[:10],
        "what_is_in_progress": in_progress[:10],
        "what_remains": remaining[:12],
        "important_decisions": decisions[:10],
        "relevant_entities": packet.get("entities", []),
        "relevant_files": packet.get("files", []),
        "next_step": _clip(next_step, 300),
        "context_packet": packet,
    }
    return continuation


def render_continuation_markdown(continuation: dict) -> str:
    lines = [
        "# MYCELIUM CONTINUATION",
        "",
        "## CURRENT STATE",
        continuation.get("current_state") or "-",
        "",
        "## WHAT HAS BEEN DONE",
    ]
    lines.extend(
        f"- {item}" for item in
        continuation.get("what_has_been_done", [])) or lines.append("-")
    lines.append("")
    lines.append("## WHAT IS IN PROGRESS")
    lines.extend(
        f"- {item}" for item in
        continuation.get("what_is_in_progress", [])) or lines.append("-")
    lines.append("")
    lines.append("## WHAT REMAINS")
    lines.extend(
        f"- {item}" for item in
        continuation.get("what_remains", [])) or lines.append("-")
    lines.append("")
    lines.append("## IMPORTANT DECISIONS")
    lines.extend(
        f"- {item}" for item in
        continuation.get("important_decisions", [])) or lines.append("-")
    lines.append("")
    lines.append("## RELEVANT ENTITIES")
    lines.append(", ".join(item.get("id", "")
                           for item in continuation.get(
                               "relevant_entities", [])) or "-")
    lines.append("")
    lines.append("## CURRENT NEXT STEP")
    lines.append(continuation.get("next_step") or "-")
    lines.extend([
        "",
        "---",
        "",
        "## USER MESSAGE",
        "(Jelles plakt hieronder zijn vraag aan het andere model.)",
        "",
        "<!-- MYCELIUM-CONTINUATION-JSON",
        _json.dumps(continuation, indent=1)[:MAX_TEXT_CHARS],
        "-->",
    ])
    return "\n".join(lines)[: MAX_TEXT_CHARS + 3000]
