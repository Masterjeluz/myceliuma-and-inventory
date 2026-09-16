"""Watcher foundation (BIG #10, deel 11).

A watcher observes, detects and formulates findings — and
optionally proposes. It never silently executes anything
important: every finding is data for a human or an approved
flow, never an action.

Findings (closed kinds):

- stale_task: assigned/queued tasks older than a bound
- unfinished_project: projects stuck in non-terminal states
- forgotten_object: entities untouched for a long time
- inconsistent_relationship: edges pointing at missing nodes
- unverified_ai_info: ai-generated rows never human-verified
- missing_provenance: records without usable provenance
- old_idea: ideas sitting raw for a long time
- maintenance_hint: purely technical follow-ups (retention,
  prune counts)

All detectors are pure functions over caller-supplied rows:
this module never touches a database or the network, so every
read gate of the caller keeps applying. Bounds everywhere;
nothing unbounded; no execution surface of any kind.
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

VALID_FINDING_KINDS = frozenset({
    "stale_task",
    "unfinished_project",
    "forgotten_object",
    "inconsistent_relationship",
    "unverified_ai_info",
    "missing_provenance",
    "old_idea",
    "maintenance_hint",
    "blocked_task",
    "failed_task",
    "orphan_file",
    "duplicate_file",
    "unfinished_design",
    "skill_gap",
    "device_stale",
})

MAX_FINDINGS = 50
MAX_SUMMARY_CHARS = 300


class WatcherRefusedError(ValueError):
    """Local validation refused; nothing was scanned."""


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(min_length=3, max_length=80)
    kind: str = Field(min_length=1, max_length=40)
    summary: str = Field(min_length=1, max_length=MAX_SUMMARY_CHARS)
    entity_refs: list[str] = Field(default_factory=list,
                                   max_length=10)
    observed_at: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _age_hours(value: str, current: datetime) -> float | None:
    moment = _parse_time(value)
    if moment is None:
        return None
    return (current - moment).total_seconds() / 3600.0


def _finding(kind: str, summary: str, refs: list[str],
             current: datetime) -> Finding:
    import secrets
    import time
    if kind not in VALID_FINDING_KINDS:
        raise WatcherRefusedError(f"Unknown finding kind '{kind}'")
    clean_refs = [str(ref)[:100] for ref in (refs or [])[:10]]
    return Finding(
        finding_id=f"wfind_{int(time.time() * 1000):x}"
                   f"{secrets.token_hex(3)}",
        kind=kind, summary=str(summary or "")[:MAX_SUMMARY_CHARS],
        entity_refs=clean_refs, observed_at=current.isoformat(),
        provenance={"source_type": "sensor-observed",
                    "creator_id": "watcher",
                    "human_verified": False})


def scan_stale_tasks(tasks: list[dict], current: datetime,
                     older_than_hours: float = 24.0) -> list[Finding]:
    """Queued/assigned tasks older than the bound."""
    findings = []
    for task in (tasks or [])[:200]:
        if not isinstance(task, dict):
            continue
        if str(task.get("status", "")) not in ("queued",
                                               "assigned"):
            continue
        age = _age_hours(str(task.get("created_at", "")), current)
        if age is None or age < older_than_hours:
            continue
        findings.append(_finding(
            "stale_task",
            f"task {task.get('id', '?')} "
            f"({task.get('status', '?')}) is {age:.1f}h old",
            [str(task.get("id", ""))], current))
        if len(findings) >= MAX_FINDINGS:
            break
    return findings


def scan_projects(projects: list[dict], current: datetime,
                  older_than_hours: float = 24.0 * 14) -> list[Finding]:
    """Projects sitting in idea/planned/paused for a long time."""
    findings = []
    for project in (projects or [])[:200]:
        if not isinstance(project, dict):
            continue
        if str(project.get("status", "")) not in (
                "idea", "planned", "paused"):
            continue
        age = _age_hours(str(project.get("updated_at",
                                         project.get(
                                             "created_at", ""))),
                         current)
        if age is None or age < older_than_hours:
            continue
        findings.append(_finding(
            "unfinished_project",
            f"project {project.get('id', '?')} "
            f"({project.get('status', '?')}) untouched for "
            f"{age / 24:.0f}d",
            [str(project.get("id", ""))], current))
        if len(findings) >= MAX_FINDINGS:
            break
    return findings


def scan_entities(entities: list[dict], current: datetime, *,
                  kind: str, stale_hours: float,
                  id_key: str = "id",
                  time_key: str = "updated_at") -> list[Finding]:
    """Generic staleness scan for objects/ideas (forgotten
    objects, old raw ideas)."""
    if kind not in ("forgotten_object", "old_idea"):
        raise WatcherRefusedError(f"Unknown scan kind '{kind}'")
    findings = []
    for entity in (entities or [])[:200]:
        if not isinstance(entity, dict):
            continue
        if kind == "old_idea" and str(
                entity.get("status", "")) != "raw":
            continue
        age = _age_hours(str(entity.get(time_key, "")), current)
        if age is None or age < stale_hours:
            continue
        findings.append(_finding(
            kind,
            f"{entity.get(id_key, '?')} untouched for "
            f"{age / 24:.1f}d",
            [str(entity.get(id_key, ""))], current))
        if len(findings) >= MAX_FINDINGS:
            break
    return findings


def scan_relationships(edges: list[dict], known_ids: set[str],
                       current: datetime) -> list[Finding]:
    """Edges pointing at unknown nodes (dangling references)."""
    findings = []
    for edge in (edges or [])[:500]:
        if not isinstance(edge, dict):
            continue
        missing = [key for key in ("from_id", "to_id")
                   if str(edge.get(key, ""))
                   and str(edge.get(key, "")) not in known_ids]
        if not missing:
            continue
        findings.append(_finding(
            "inconsistent_relationship",
            f"edge {edge.get('id', '?')} references unknown "
            f"{'/'.join(missing)}",
            [str(edge.get("id", ""))], current))
        if len(findings) >= MAX_FINDINGS:
            break
    return findings


def scan_provenance(records: list[dict], current: datetime
                    ) -> list[Finding]:
    """AI-generated rows never verified + rows without usable
    provenance. Observation only."""
    findings = []
    for record in (records or [])[:200]:
        if not isinstance(record, dict):
            continue
        provenance = record.get("provenance", {})
        if hasattr(provenance, "model_dump"):
            provenance = provenance.model_dump(mode="json")
        if not isinstance(provenance, dict) or not provenance.get(
                "source_type"):
            findings.append(_finding(
                "missing_provenance",
                f"{record.get('entity_id', record.get('id', '?'))} "
                "has no usable provenance",
                [str(record.get("entity_id",
                                record.get("id", "")))], current))
        elif provenance.get("source_type") == "ai-generated" \
                and not provenance.get("human_verified"):
            findings.append(_finding(
                "unverified_ai_info",
                f"{record.get('entity_id', record.get('id', '?'))} "
                "is AI-generated and unverified",
                [str(record.get("entity_id",
                                record.get("id", "")))], current))
        if len(findings) >= MAX_FINDINGS:
            break
    return findings


def _bounded(rows, cap: int = 200) -> list[dict]:
    return [row for row in (rows or [])[:cap]
            if isinstance(row, dict)]


def scan_blocked_tasks(tasks: list[dict], current: datetime
                       ) -> list[Finding]:
    """Tasks in blocked status. Reason shown: status + age."""
    findings = []
    for task in _bounded(tasks):
        if str(task.get("status", "")) != "blocked":
            continue
        age = _age_hours(str(task.get("updated_at",
                                      task.get("created_at",
                                               ""))), current)
        age_text = f", blocked for {age:.1f}h" \
            if age is not None else ""
        findings.append(_finding(
            "blocked_task",
            f"task {task.get('id', '?')} is blocked{age_text}; "
            "needs a human decision or unblocked dependency",
            [str(task.get("id", ""))], current))
        if len(findings) >= MAX_FINDINGS:
            break
    return findings


def scan_failed_tasks(tasks: list[dict], current: datetime
                      ) -> list[Finding]:
    """Failed tasks + repeatedly failing (attempts/maxed).
    Reason shown: status and attempt counts, never a retry."""
    findings = []
    for task in _bounded(tasks):
        status = str(task.get("status", ""))
        attempts = task.get("attempts", task.get("attempt_count",
                                                 0))
        try:
            attempts = int(attempts or 0)
        except (TypeError, ValueError):
            attempts = 0
        if status == "failed":
            findings.append(_finding(
                "failed_task",
                f"task {task.get('id', '?')} failed after "
                f"{attempts} attempt(s); inspect before retrying",
                [str(task.get("id", ""))], current))
        elif status in ("queued", "assigned") and attempts >= 3:
            findings.append(_finding(
                "failed_task",
                f"task {task.get('id', '?')} failed repeatedly "
                f"({attempts} attempts); do not retry blindly",
                [str(task.get("id", ""))], current))
        if len(findings) >= MAX_FINDINGS:
            break
    return findings


def scan_orphan_files(files: list[dict], edges: list[dict],
                      current: datetime) -> list[Finding]:
    """Files with no relationship edge at all. Reason shown:
    zero edges in the bounded edge set."""
    linked: set[str] = set()
    for edge in _bounded(edges, 500):
        for key in ("from_id", "to_id"):
            value = str(edge.get(key, ""))
            if value:
                linked.add(value)
    findings = []
    for record in _bounded(files):
        file_id = str(record.get("id", record.get("file_id",
                                                  "")))
        if not file_id or file_id in linked:
            continue
        findings.append(_finding(
            "orphan_file",
            f"file {file_id} has no relationships; link it to "
            "a source or project, or confirm it is spare",
            [file_id], current))
        if len(findings) >= MAX_FINDINGS:
            break
    return findings


def scan_duplicate_files(files: list[dict], current: datetime
                         ) -> list[Finding]:
    """Files sharing one sha256. Reason shown: the hash."""
    by_hash: dict[str, list[str]] = {}
    for record in _bounded(files):
        digest = str(record.get("sha256", "")).lower()
        file_id = str(record.get("id", record.get("file_id",
                                                  "")))
        if not digest or not file_id:
            continue
        by_hash.setdefault(digest, []).append(file_id)
    findings = []
    for digest in sorted(by_hash):
        ids = by_hash[digest]
        if len(ids) < 2:
            continue
        findings.append(_finding(
            "duplicate_file",
            f"{len(ids)} files share sha256 {digest[:16]}...; "
            "deduplicate or confirm intentional copies",
            ids[:10], current))
        if len(findings) >= MAX_FINDINGS:
            break
    return findings


def scan_unfinished_designs(fabrications: list[dict],
                            current: datetime) -> list[Finding]:
    """Fabrication records stuck before verification.
    Reason shown: current stage."""
    findings = []
    for record in _bounded(fabrications):
        status = str(record.get("status", ""))
        if status in ("verified", "cancelled"):
            continue
        findings.append(_finding(
            "unfinished_design",
            f"fabrication {record.get('fabrication_id', '?')} "
            f"is at stage '{status or 'unknown'}'; finish or "
            "cancel explicitly",
            [str(record.get("fabrication_id", ""))], current))
        if len(findings) >= MAX_FINDINGS:
            break
    return findings


def scan_skill_gaps(requirements: list[dict],
                    owned_skill_names: list[str],
                    current: datetime) -> list[Finding]:
    """Project skill needs without an owned skill. Reason
    shown: which project needs which skill. Suggestion only:
    never enrols or buys anything."""
    owned = {str(name).strip().lower()
             for name in (owned_skill_names or [])}
    findings = []
    for requirement in _bounded(requirements):
        skill = str(requirement.get("skill", "")).strip()
        project = str(requirement.get("project_ref",
                                      requirement.get(
                                          "project_id", "")))
        if not skill or skill.lower() in owned:
            continue
        findings.append(_finding(
            "skill_gap",
            f"project {project or '?'} needs skill '{skill}' "
            "which is not owned; consider a learning resource "
            "or a small practice task",
            [project] if project else [], current))
        if len(findings) >= MAX_FINDINGS:
            break
    return findings


def scan_device_staleness(devices: list[dict], current: datetime,
                          *, kind: str = "device_stale",
                          stale_hours: float = 24.0 * 7
                          ) -> list[Finding]:
    """Printers/cameras/nodes unseen beyond the bound. Reason
    shown: last-seen age."""
    findings = []
    for device in _bounded(devices):
        last_seen = str(device.get("last_seen",
                                   device.get("updated_at",
                                              "")))
        age = _age_hours(last_seen, current)
        if age is None or age < stale_hours:
            continue
        findings.append(_finding(
            kind,
            f"{device.get('device_id', device.get('id', '?'))} "
            f"unseen for {age / 24:.1f}d; check power, "
            "connection and retention",
            [str(device.get("device_id",
                            device.get("id", "")))], current))
        if len(findings) >= MAX_FINDINGS:
            break
    return findings
