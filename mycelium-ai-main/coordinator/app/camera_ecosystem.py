"""Camera ecosystem (BIG #34): files become living world input.

The full chain, reusing every existing safety layer:

    FILE → INGEST SESSION → OBSERVATION → VLM (or honest
    fallback) → CANDIDATE → POSSIBLE MATCH → LINK PROPOSAL
    (YES) → SYMBIOSIS → CRAFT → GUIDE → MEMORY (if allowed)

Rules (fail-closed, tested):

- The camera is never authority. Observations and VLM output
  are OBSERVATION/CANDIDATE until the existing truth flow
  (support → promote, human YES) says otherwise.
- Multi-file sessions are bounded (≤8 files, each through the
  existing FileIngestAdapter validation: plain filename,
  inside the camera dir, known suffix, capped size).
- Dedupe by sha256: the same bytes never create a second
  observation in any session. Replays are reported as
  duplicates, never re-ingested.
- VLM honesty: Ollama loopback provider when reachable
  (vlm_state REAL, analysis stored); otherwise an explicit
  extractive fallback (vlm_state UNAVAILABLE, no labels, no
  confidences, no invented description). Fallback never
  claims a VLM ran.
- Candidate proposals come only from REAL VLM labels, one
  per label, idempotent per (observation, label). No
  auto-promotion, no auto-merge, no auto-relation: links are
  connection candidates (PROPOSED in the symbiosis layer)
  until Jelles decides via the existing knowledge flow.
- Entity matching is substring evidence over a bounded
  inventory browse — POSSIBLE MATCH, never a merge.
- No new event types (observation.created,
  candidate.observed, relation.proposed reused). IN_APP
  notifications go to registered nodes only (bounded).
- No shell, no subprocess, no eval, no URLs, no credentials.
"""

from __future__ import annotations

import secrets as _secrets
import time as _time

from pydantic import BaseModel, ConfigDict, Field

#: Hard cap per ingest session. Large videos are never
#: processed whole: the operator extracts stills first.
MAX_SESSION_FILES = 8

LINK_PREDICATES = (
    "used_in",
    "component_of",
    "related_to",
    "stored_at",
    "supports",
    "evidence_for",
    "part_of",
)

VLM_STATES = ("REAL", "UNAVAILABLE")


class EcosystemRefusedError(ValueError):
    """Camera ecosystem validation refused; nothing was stored."""


class SessionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=200)
    state: str = Field(default="queued", max_length=20)
    observation_id: str = Field(default="", max_length=80)
    sha256: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=300)


class IngestSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=3, max_length=80)
    device_id: str = Field(min_length=3, max_length=80)
    state: str = Field(default="open", max_length=20)
    items: list[SessionItem] = Field(default_factory=list,
                                     max_length=MAX_SESSION_FILES)
    created_at: str = ""
    updated_at: str = ""


def generate_session_id() -> str:
    return f"cing_{int(_time.time() * 1000):x}{_secrets.token_hex(3)}"


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def init_ecosystem_tables() -> None:
    """Additive session table in the chat DB. Idempotent."""
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS camera_ingest_sessions (
            session_id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            record TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cing_device
            ON camera_ingest_sessions(device_id, created_at);
        """)


def check_session_id(value: str) -> str:
    cleaned = str(value or "").strip()[:80]
    if not cleaned.startswith("cing_") or len(cleaned) < 8:
        raise EcosystemRefusedError(
            "session_id must be a cing_ ingest session id")
    if any(char not in
           "abcdefghijklmnopqrstuvwxyz0123456789_"
           for char in cleaned):
        raise EcosystemRefusedError("session_id has illegal characters")
    return cleaned


def check_filenames(values) -> list[str]:
    """Filenames only: the existing check_image_ref decides."""
    from .observations import check_image_ref
    if not isinstance(values, (list, tuple)) or not values:
        raise EcosystemRefusedError(
            "ingest needs 1..8 inbox filenames")
    if len(values) > MAX_SESSION_FILES:
        raise EcosystemRefusedError(
            f"ingest takes at most {MAX_SESSION_FILES} files per "
            "session; extract stills first")
    cleaned: list[str] = []
    for entry in values:
        try:
            reference = check_image_ref(entry)
        except ValueError as error:
            raise EcosystemRefusedError(str(error)) from error
        if not reference:
            raise EcosystemRefusedError(
                "empty filename refused")
        if reference in cleaned:
            raise EcosystemRefusedError(
                f"duplicate filename in request: {reference}")
        cleaned.append(reference)
    return cleaned


def save_session(session: IngestSession) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_ecosystem_tables()
    init_chat_database()
    with chat_connection() as db:
        db.execute(
            """INSERT INTO camera_ingest_sessions
            (session_id, device_id, record, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
            record=excluded.record""",
            (session.session_id, session.device_id,
             dump(session.model_dump(mode="json")),
             session.created_at or _now()))


def load_session(session_id: str) -> IngestSession | None:
    from .database import chat_connection, init_chat_database, load
    init_ecosystem_tables()
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT record FROM camera_ingest_sessions "
                         "WHERE session_id=?",
                         (check_session_id(session_id),)).fetchone()
    if row is None:
        return None
    return IngestSession.model_validate(load(row["record"]))


def list_sessions(device_id: str = "", limit: int = 20
                  ) -> list[IngestSession]:
    from .database import chat_connection, init_chat_database, load
    init_ecosystem_tables()
    init_chat_database()
    count = max(1, min(int(limit or 20), 50))
    with chat_connection() as db:
        if device_id:
            rows = db.execute(
                """SELECT record FROM camera_ingest_sessions
                WHERE device_id=? ORDER BY created_at DESC LIMIT ?""",
                (str(device_id)[:80], count)).fetchall()
        else:
            rows = db.execute(
                """SELECT record FROM camera_ingest_sessions
                ORDER BY created_at DESC LIMIT ?""",
                (count,)).fetchall()
    return [IngestSession.model_validate(load(row["record"]))
            for row in rows]


def known_shas(limit_sessions: int = 20) -> set[str]:
    """sha256 digests already ingested (any recent session)."""
    known: set[str] = set()
    for session in list_sessions(limit=limit_sessions):
        for item in session.items:
            if item.sha256:
                known.add(item.sha256)
    return known


def create_session(device_id: str, filenames) -> IngestSession:
    """Validate and store one open multi-file ingest session."""
    from .cameras import get_device
    cleaned_device = str(device_id or "").strip()[:80]
    if get_device(cleaned_device) is None:
        raise EcosystemRefusedError("Camera not found")
    files = check_filenames(filenames)
    stamp = _now()
    session = IngestSession(
        session_id=generate_session_id(),
        device_id=cleaned_device, state="open",
        items=[SessionItem(filename=name) for name in files],
        created_at=stamp, updated_at=stamp)
    save_session(session)
    return session


def _notify_nodes(kind: str, title: str, body: str = "",
                  related_entity: str = "") -> None:
    """Best-effort IN_APP fan-out to registered nodes (bounded).
    Notification failure never breaks ingest."""
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
                  related_entity=related_entity[:100])
        except Exception:
            continue


def run_session(session_id: str) -> IngestSession:
    """Ingest every queued file: dedupe → observation → events.

    Idempotent: already-observed items are skipped, duplicates
    across sessions refuse with a duplicate mark. No VLM here;
    describe_observation() is the explicit next step per item.
    """
    from .cameras import get_device, save_observation
    from .events import new_event as _bus_new
    from .events import save_event as _bus_save
    from .vision_ingest import (FileIngestAdapter, IngestRefusedError,
                                ingest_snapshot, media_facts)
    session = load_session(check_session_id(session_id))
    if session is None:
        raise EcosystemRefusedError("ingest session not found")
    device = get_device(session.device_id)
    if device is None:
        raise EcosystemRefusedError(
            "camera for this session no longer exists")
    seen = known_shas()
    changed = False
    observed = 0
    for item in session.items:
        if item.state in ("observed", "duplicate"):
            continue
        try:
            media = media_facts(item.filename)
        except IngestRefusedError as error:
            item.state = "refused"
            item.note = str(error)[:300]
            changed = True
            continue
        if media.sha256 in seen:
            item.state = "duplicate"
            item.sha256 = media.sha256
            item.note = ("same bytes already ingested; replay "
                         "refused, no second observation")
            changed = True
            continue
        try:
            adapter = FileIngestAdapter(item.filename)
            result = ingest_snapshot(device, adapter)
        except IngestRefusedError as error:
            item.state = "refused"
            item.note = str(error)[:300]
            changed = True
            continue
        save_observation(result.observation)
        item.state = "observed"
        item.observation_id = result.observation.observation_id
        item.sha256 = media.sha256
        item.note = ""
        seen.add(media.sha256)
        observed += 1
        changed = True
        try:
            _bus_save(_bus_new(
                "observation.created",
                f"Session {session.session_id}: observation "
                f"{item.observation_id} from {item.filename} "
                f"via {session.device_id}",
                node_id=session.device_id))
        except Exception:
            pass
    if changed:
        session.updated_at = _now()
        session.state = ("complete"
                         if all(item.state in ("observed", "duplicate",
                                               "refused")
                                for item in session.items)
                         else "open")
        save_session(session)
    if observed:
        _notify_nodes(
            "new_observation",
            f"Session {session.session_id}: {observed} new "
            "observation(s)",
            "Files became observations. VLM description and "
            "candidates are explicit next steps.",
            related_entity=session.device_id)
    return session


def session_observations(session_id: str) -> list[dict]:
    """Stored observations for one session (metadata only)."""
    from .cameras import list_observations
    session = load_session(check_session_id(session_id))
    if session is None:
        raise EcosystemRefusedError("ingest session not found")
    wanted = {item.observation_id for item in session.items
              if item.observation_id}
    out = []
    try:
        for observation in list_observations(session.device_id,
                                             limit=50):
            if observation.observation_id in wanted:
                out.append(observation.model_dump(mode="json"))
    except Exception:
        pass
    return out


# -- VLM layer ---------------------------------------------------------------

def describe_observation(observation_id: str, *,
                         question: str = "",
                         provider: str = "auto") -> dict:
    """Run VLM over one stored observation — or an honest fallback.

    REAL: Ollama loopback analysis stored via save_analysis,
    labels + confidences + description + uncertainty.
    UNAVAILABLE: extractive fallback (filename, size, sha,
    device, timestamp) with empty labels and an explicit
    uncertainty note. The fallback is stored with model=""
    so callers can tell them apart; it never invents pixels.
    """
    from .cameras import list_observations
    from .vision_flow import save_analysis, VisionAnalysisRecord
    from .vision_ingest import media_facts
    from .vision_provider import (VisionRefusedError, VisionRequest,
                                  VisionResult, VisionUnavailable)
    cleaned = str(observation_id or "").strip()[:80]
    if not cleaned:
        raise EcosystemRefusedError("observation_id is required")
    observation = None
    try:
        from . import main as _main
        observation = _main._observation_load(cleaned)
    except Exception:
        observation = None
    if observation is None:
        # Fall back to a device scan (bounded).
        try:
            from .cameras import list_devices
            for device in list_devices()[:20]:
                for candidate in list_observations(
                        device.device_id, limit=50):
                    if candidate.observation_id == cleaned:
                        observation = candidate
                        break
                if observation is not None:
                    break
        except Exception:
            observation = None
    if observation is None:
        raise EcosystemRefusedError("observation not found")
    if not observation.media_ref:
        raise EcosystemRefusedError(
            "observation carries no local media; refusing")
    asked = str(question or "Wat zie je op deze foto?")[:500]
    if str(provider or "auto") != "auto":
        raise EcosystemRefusedError(
            "only the automatic local provider chain is supported")
    try:
        from . import main as _main
        vision_provider = _main.get_vision_provider("ollama")
        request = VisionRequest(
            observation_id=observation.observation_id,
            device_id=observation.device_id,
            media_ref=observation.media_ref, question=asked)
        import anyio as _anyio
        result = _anyio.run(vision_provider.analyze, request)
        record = VisionAnalysisRecord(
            analysis_id=result.analysis_id,
            observation_id=observation.observation_id,
            device_id=observation.device_id,
            result=result.model_dump(mode="json"),
            created_at=result.observed_at)
        save_analysis(record)
        _notify_nodes(
            "camera_ready",
            f"VLM analysis ready for {observation.observation_id}",
            f"{len(result.labels)} label(s), "
            f"{len(result.detected_objects)} detected object(s). "
            "Advice only — review decides.",
            related_entity=observation.device_id)
        return {"vlm_state": "REAL",
                "analysis": result.model_dump(mode="json")}
    except (VisionUnavailable, VisionRefusedError,
            Exception) as error:
        try:
            media = media_facts(
                observation.media_ref, width=observation.width,
                height=observation.height)
            media_note = (f"{media.mime_type}, {media.size_bytes} "
                          f"bytes, sha256 {media.sha256[:16]}…")
        except Exception:
            media_note = "media facts unavailable"
        fallback = VisionResult(
            analysis_id=f"vlm-fallback-{observation.observation_id[:40]}",
            observation_id=observation.observation_id,
            device_id=observation.device_id,
            labels=[], detected_objects=[],
            description=(f"No VLM ran for {observation.media_ref} "
                         f"({media_note}). File facts only."),
            ocr_text="",
            uncertainty=("VLM UNAVAILABLE: "
                         + (str(error)[:300] if not isinstance(
                             error, Exception) or "Vision" in type(
                             error).__name__ else str(error)[:300])),
            raw_text="", model="",
            observed_at=_now())
        try:
            record = VisionAnalysisRecord(
                analysis_id=fallback.analysis_id,
                observation_id=observation.observation_id,
                device_id=observation.device_id,
                result=fallback.model_dump(mode="json"),
                created_at=fallback.observed_at)
            save_analysis(record)
        except Exception:
            pass
        return {"vlm_state": "UNAVAILABLE",
                "analysis": fallback.model_dump(mode="json"),
                "reason": str(error)[:300]}


# -- observation → candidate ---------------------------------------------------

def propose_candidates(observation_id: str) -> list[dict]:
    """One candidate per REAL VLM label. Idempotent per
    (observation, label); fallback analyses yield nothing."""
    from .events import new_event as _bus_new
    from .events import save_event as _bus_save
    from .inventory_read import Provenance
    from .knowledge import (CandidateRefusedError, list_candidates,
                            new_candidate, save_candidate)
    from .vision_flow import VisionAnalysisRecord, list_analyses
    cleaned = str(observation_id or "").strip()[:80]
    if not cleaned:
        raise EcosystemRefusedError("observation_id is required")
    try:
        analyses = list_analyses(cleaned, limit=5)
    except Exception:
        analyses = []
    latest_real = None
    for entry in analyses:
        result = entry.result if isinstance(entry.result, dict) \
            else {}
        if result.get("model"):
            latest_real = entry
            break
    if latest_real is None:
        return []
    result = latest_real.result
    seen_labels: list[tuple[str, float]] = []
    for detected in result.get("detected_objects", [])[:10]:
        if not isinstance(detected, dict):
            continue
        label = str(detected.get("label", "")).strip()[:120]
        if not label:
            continue
        try:
            score = max(0.0, min(1.0, float(
                detected.get("confidence", 0.0))))
        except (TypeError, ValueError):
            score = 0.0
        if label not in [seen[0] for seen in seen_labels]:
            seen_labels.append((label, score))
    for label in result.get("labels", [])[:10]:
        text = str(label or "").strip()[:120]
        if text and text not in [seen[0] for seen in seen_labels]:
            seen_labels.append((text, 0.0))
    try:
        existing = list_candidates(limit=200)
    except Exception:
        existing = []
    have = set()
    for entry in existing:
        try:
            data = entry.model_dump(mode="json")
        except Exception:
            continue
        refs = data.get("source_refs") or []
        labels = [str(ref.get("id", "")) for ref in refs
                  if isinstance(ref, dict)
                  and ref.get("kind") == "camera-label"]
        for text in labels:
            have.add(text)
    created: list[dict] = []
    for label, score in seen_labels[:8]:
        marker = f"{cleaned}::{label}"
        if marker in have:
            continue
        summary = (f"Camera observation {cleaned}: the VLM suggests "
                   f"this may show '{label}' (model confidence "
                   f"{score:.2f}). OBSERVATION, not a fact — needs "
                   "your review before it becomes anything.")
        try:
            entry = new_candidate(
                f"mogelijk {label} ({cleaned[:24]})",
                "observation", summary=summary,
                state="observation",
                provenance=Provenance(
                    source_type="ai-generated",
                    creator_id="camera-vlm", human_verified=False,
                    notes="VLM label; pictured identity unconfirmed"),
                source_refs=[{"kind": "camera-observation",
                              "id": cleaned,
                              "label": f"observation {cleaned}"},
                             {"kind": "camera-label", "id": marker,
                              "label": label}],
                evidence=[{"text": f"VLM label '{label}' "
                                   f"(confidence {score:.2f})",
                           "source": cleaned}])
            save_candidate(entry)
        except CandidateRefusedError:
            continue
        try:
            _bus_save(_bus_new(
                "candidate.observed",
                f"Camera candidate {entry.candidate_id}: mogelijk "
                f"{label[:80]}"))
        except Exception:
            pass
        created.append({"candidate_id": entry.candidate_id,
                        "label": label, "confidence": score})
    if created:
        _notify_nodes(
            "candidate_waiting",
            f"{len(created)} camera candidate(s) wait for review",
            "VLM labels became candidates. Nothing promotes "
            "itself — support, research or reject.",
            related_entity=cleaned)
    return created


# -- entity matching (POSSIBLE MATCH, never merge) ------------------------------

def possible_matches(label: str, limit: int = 5) -> list[dict]:
    """Substring evidence over a bounded inventory browse."""
    from . import main as _main
    words = [word.lower() for word in str(label or "").split()
             if len(word) >= 3][:6]
    if not words:
        raise EcosystemRefusedError(
            "matching needs a label with real words")
    count = max(1, min(int(limit or 5), 10))
    reader = _main._world_reader()
    import anyio as _anyio

    async def _browse(kind: str) -> list:
        try:
            found = await reader.browse(kind)
            return found.results or []
        except Exception:
            return []

    async def _all() -> list:
        out = []
        for kind in ("objects", "projects", "ideas"):
            out.extend(await _browse(kind))
        return out

    try:
        records = _anyio.run(_all)
    except Exception:
        return []
    matches: list[dict] = []
    for record in records[:120]:
        entity_id = str(record.entity_id)
        details = record.details \
            if isinstance(record.details, dict) else {}
        haystack = " ".join(
            str(details.get(key, "")) for key in
            ("name", "title", "goal", "description")).lower()
        hits = [word for word in words if word in haystack]
        if not hits:
            continue
        title = entity_id
        for key in ("name", "title", "goal"):
            if details.get(key):
                title = str(details[key])[:80]
                break
        matches.append({"entity_id": entity_id, "title": title,
                        "matched_words": hits[:4],
                        "why": f"label words {hits[:4]} appear in "
                               "this record; confirm visually before "
                               "linking"})
        if len(matches) >= count:
            break
    return matches


# -- symbiosis proposals (PROPOSED until YES) ------------------------------------

def suggest_link(observation_id: str, entity_id: str,
                 predicate: str) -> dict:
    """Propose observation → entity as a connection candidate.

    Surfaces as PROPOSED in the symbiosis layer. YES/NO/REVIEW
    run through the existing knowledge support/promote/reject
    flow — this function only proposes."""
    from .events import new_event as _bus_new
    from .events import save_event as _bus_save
    from .inventory_read import Provenance
    from .knowledge import (CandidateRefusedError, new_candidate,
                            save_candidate)
    from .symbiosis import clean_entity
    cleaned_obs = str(observation_id or "").strip()[:80]
    if not cleaned_obs:
        raise EcosystemRefusedError("observation_id is required")
    try:
        target = clean_entity(entity_id)
    except ValueError as error:
        raise EcosystemRefusedError(str(error)) from error
    verb = str(predicate or "").strip()[:20]
    if verb not in LINK_PREDICATES:
        raise EcosystemRefusedError(
            f"predicate must be one of {list(LINK_PREDICATES)}")
    try:
        entry = new_candidate(
            f"camera {cleaned_obs[:24]} {verb} {target[:40]}",
            "connection",
            summary=(f"Possible relation: camera observation "
                     f"{cleaned_obs} {verb} {target}. PROPOSED — "
                     "needs your YES before it means anything."),
            state="candidate",
            provenance=Provenance(
                source_type="sensor-observed",
                creator_id="camera-ecosystem", human_verified=False,
                notes="operator/VLM-suggested link; unconfirmed"),
            source_refs=[{"kind": "camera-observation",
                          "id": cleaned_obs,
                          "label": f"observation {cleaned_obs}"}],
            entity_refs=[cleaned_obs, target])
        save_candidate(entry)
    except CandidateRefusedError as error:
        raise EcosystemRefusedError(str(error)) from error
    try:
        _bus_save(_bus_new(
            "relation.proposed",
            f"Camera link proposed: {cleaned_obs} {verb} {target}"))
    except Exception:
        pass
    _notify_nodes(
        "new_connection",
        f"Possible link: camera observation → {target[:60]}",
        f"Predicate {verb}. Review in /knowledge, decide with YES.",
        related_entity=target)
    return {"candidate_id": entry.candidate_id,
            "observation_id": cleaned_obs, "entity_id": target,
            "predicate": verb, "state": "PROPOSED"}


# -- timeline (existing bus + notifications, no second system) --------------------

def timeline(device_id: str = "", observation_id: str = "",
             limit: int = 30) -> list[dict]:
    """Camera timeline from the shared event bus + notifications."""
    from . import main as _main
    needles = [part for part in
               (str(device_id or "").strip(),
                str(observation_id or "").strip()) if part]
    if not needles:
        raise EcosystemRefusedError(
            "timeline needs a device_id or observation_id")
    count = max(1, min(int(limit or 30), 60))
    items: list[dict] = []
    try:
        events = _main.bus_events(limit=200)
    except Exception:
        events = []
    for event in events:
        blob = (f"{getattr(event, 'summary', '')} "
                f"{getattr(event, 'node_id', '')} "
                f"{getattr(event, 'mission_id', '')}")
        if not any(needle in blob for needle in needles):
            continue
        items.append({
            "at": getattr(event, "created_at", ""),
            "kind": "event",
            "type": getattr(event, "event_type", ""),
            "text": getattr(event, "summary", "")[:200],
        })
        if len(items) >= count:
            break
    try:
        notes = _main.list_notifications_for_report(limit=50)
        for note in notes:
            blob = (f"{getattr(note, 'title', '')} "
                    f"{getattr(note, 'body', '')} "
                    f"{getattr(note, 'related_entity', '')}")
            if not any(needle in blob for needle in needles):
                continue
            items.append({
                "at": getattr(note, "created_at", ""),
                "kind": "notification",
                "type": getattr(note, "type", ""),
                "text": getattr(note, "title", "")[:200],
            })
            if len(items) >= count:
                break
    except Exception:
        pass
    items.sort(key=lambda entry: entry.get("at", ""))
    return items[:count]
