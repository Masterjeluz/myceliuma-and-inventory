"""Scheduled-job foundation (BIG #11-15, Phase 6).

Jobs are named, bounded units of work: watcher scans,
memory-consolidation proposals, morning-report builds,
health imports, research processing, skill discovery,
inventory reconciliation, device health. Each run is
observable (job_runs table), retryable (just run again),
cancellable (a running marker can be cancelled) and
idempotent (a caller run_key returns the existing run
instead of executing twice).

There is deliberately no background thread in the web
lifespan: runs trigger via API (or an operator poll loop),
so tests and local runs stay deterministic.
"""

import secrets
import time

JOB_NAMES = (
    "watcher_scan",
    "memory_consolidation",
    "morning_report",
    "health_import",
    "research_process",
    "skill_discover",
    "inventory_reconcile",
    "device_health",
)

RUN_STATUSES = (
    "running",
    "completed",
    "failed",
    "cancelled",
)


class JobRefusedError(ValueError):
    """Fail-closed job validation."""


def now() -> str:
    import datetime
    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


def generate_run_id() -> str:
    return f"job_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def _record_run(run_id: str, job_name: str, status: str,
                detail: str, started_at: str,
                finished_at: str = "") -> None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO job_runs
        (run_id, job_name, status, detail, started_at,
         finished_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
         status=excluded.status, detail=excluded.detail,
         finished_at=excluded.finished_at""",
                     (run_id, job_name, status,
                      str(detail or "")[:2000], started_at,
                      finished_at))


def list_runs(*, job_name: str = "",
              limit: int = 20) -> list[dict]:
    from .database import chat_connection, init_chat_database
    if job_name and job_name not in JOB_NAMES:
        raise JobRefusedError(f"Unknown job '{job_name}'")
    init_chat_database()
    with chat_connection() as db:
        if job_name:
            rows = db.execute(
                "SELECT * FROM job_runs WHERE job_name=? "
                "ORDER BY started_at DESC LIMIT ?",
                (job_name, max(1, min(int(limit or 20),
                                      100)))).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM job_runs ORDER BY started_at "
                "DESC LIMIT ?",
                (max(1, min(int(limit or 20), 100)),)).fetchall()
    return [dict(row) for row in rows]


def cancel_run(run_id: str) -> bool:
    """Mark a run cancelled. Synchronous runs finish
    immediately, so this honours in-flight markers and
    anything still queued behind the same key."""
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        cursor = db.execute(
            "UPDATE job_runs SET status='cancelled', "
            "finished_at=? WHERE run_id=? AND status="
            "'running'", (now(), run_id))
    return cursor.rowcount > 0


def _run_watcher_scan() -> dict:
    from datetime import datetime, timezone
    from .watcher import scan_failed_tasks, scan_stale_tasks
    from .database import connection
    current = datetime.now(timezone.utc)
    with connection() as db:
        rows = db.execute("SELECT id, status, created_at, "
                          "attempt_count FROM tasks ORDER BY id "
                          "DESC LIMIT 200").fetchall()
    tasks = [dict(row) for row in rows]
    for task in tasks:
        task["attempts"] = task.pop("attempt_count", 0)
    findings = scan_stale_tasks(tasks, current)
    findings += scan_failed_tasks(tasks, current)
    return {"findings": len(findings[:50]),
            "tasks_scanned": len(tasks)}


def _run_memory_consolidation(params: dict) -> dict:
    from .memory import propose_consolidation
    texts = params.get("raw_texts", [])
    if not isinstance(texts, list) or not texts:
        return {"candidates": 0, "note": "no raw texts "
                "supplied; nothing proposed"}
    proposal = propose_consolidation(
        [str(item)[:2000] for item in texts[:20]],
        project_ref=str(params.get("project_ref", "")))
    return {"candidates": len(proposal["candidates"]),
            "duplicates": proposal["duplicates"],
            "contradictions": len(
                proposal["contradictions"])}


def _run_morning_report() -> dict:
    from .reports import morning_report
    report = morning_report({
        "today": [now()],
        "suggestions": ["scheduled build; open /morning "
                        "for the live report"]})
    return {"sections": len(report.sections),
            "report_id": report.report_id}


def _run_health_import(params: dict) -> dict:
    from .garmin import get_garmin_provider, import_samples
    provider = str(params.get("provider", "mock"))
    return import_samples(
        get_garmin_provider(provider),
        since=str(params.get("since", "")),
        cursor=int(params.get("cursor", 0) or 0),
        limit=min(int(params.get("limit", 50) or 50), 100))


def _run_research_process() -> dict:
    from .research import list_sources
    sources = list_sources(limit=50)
    by_type: dict[str, int] = {}
    for entry in sources:
        by_type[entry.source_type] = by_type.get(
            entry.source_type, 0) + 1
    return {"sources": len(sources), "by_type": by_type}


def _run_skill_discover(params: dict) -> dict:
    from .skills import discover_candidates, save_candidate
    text = str(params.get("project_text", ""))
    if not text.strip():
        return {"candidates": 0, "note": "no project text; "
                "nothing discovered"}
    candidates = discover_candidates(
        text[:5000],
        project_ref=str(params.get("project_ref", "")))
    for candidate in candidates:
        save_candidate(candidate)
    return {"candidates": len(candidates)}


def _run_inventory_reconcile() -> dict:
    from .database import connection
    with connection() as db:
        counts = db.execute("SELECT status, COUNT(*) AS n "
                            "FROM tasks GROUP BY status").fetchall()
    return {"task_states": {row["status"]: row["n"]
                            for row in counts}}


def _run_device_health() -> dict:
    from datetime import datetime, timezone
    from .database import connection
    from .watcher import scan_device_staleness
    current = datetime.now(timezone.utc)
    with connection() as db:
        rows = db.execute("SELECT node_id AS id, status, "
                          "last_seen FROM nodes LIMIT 200"
                          ).fetchall()
    findings = scan_device_staleness(
        [dict(row) for row in rows], current)
    return {"devices": len(rows),
            "stale_findings": len(findings)}


_RUNNERS = {
    "watcher_scan": lambda params: _run_watcher_scan(),
    "memory_consolidation": _run_memory_consolidation,
    "morning_report": lambda params: _run_morning_report(),
    "health_import": _run_health_import,
    "research_process": lambda params: _run_research_process(),
    "skill_discover": _run_skill_discover,
    "inventory_reconcile": lambda params: _run_inventory_reconcile(),
    "device_health": lambda params: _run_device_health(),
}


def run_job(job_name: str, params: dict | None = None, *,
            run_key: str = "") -> dict:
    """Execute one bounded job synchronously and record the
    run. A repeated run_key returns the existing run
    (idempotent); failures record with the error capped."""
    if job_name not in JOB_NAMES:
        raise JobRefusedError(f"Unknown job '{job_name}'")
    if params is not None and not isinstance(params, dict):
        raise JobRefusedError("params must be an object")
    params = dict(params or {})
    if len(params) > 10:
        raise JobRefusedError("params are capped")
    if run_key:
        marker = f"key={run_key}"
        for row in list_runs(job_name=job_name, limit=100):
            if row["detail"] == marker or row["detail"].startswith(
                    marker + " "):
                return dict(row)
    run_id = generate_run_id()
    started = now()
    _record_run(run_id, job_name, "running",
                f"key={run_key}" if run_key else "", started)
    try:
        summary = _RUNNERS[job_name](params)
    except (JobRefusedError, ValueError, KeyError,
            TypeError) as error:
        _record_run(run_id, job_name, "failed", str(error),
                    started, now())
        raise JobRefusedError(f"job failed: {error}")
    detail = f"key={run_key} {summary}" if run_key else str(
        summary)
    _record_run(run_id, job_name, "completed", detail[:2000],
                started, now())
    return {"run_id": run_id, "job_name": job_name,
            "status": "completed", "summary": summary,
            "started_at": started}
