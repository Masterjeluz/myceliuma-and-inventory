"""Central event/log retention (BIG #16, Fase 4).

One understandable policy instead of per-module random
caps. Deterministic: keep the newest N rows per scope,
delete the oldest excess. Tombstone-, verification- and
provenance-aware by exclusion: dist_events (sync cursors
and conflict bases depend on it), dist_conflicts (open
conflicts are live security state) and write_proposals
(approval lifecycle) are NEVER pruned here.

Pruning runs operator-triggered via
POST /api/v1/maintenance/prune (and is directly testable);
no background thread, no silent loss — every run returns
counts per table.
"""

INTERFACE_EVENTS_KEEP = 500
JOB_RUNS_KEEP_PER_JOB = 20
CONVERSATION_EVENTS_KEEP_PER_MISSION = 200


class RetentionRefusedError(ValueError):
    """Fail-closed retention validation."""


def prune_job_runs(keep_per_job: int = JOB_RUNS_KEEP_PER_JOB
                   ) -> int:
    """Keep the newest runs per job name, drop older excess."""
    from .database import chat_connection, init_chat_database
    try:
        keep = max(1, int(keep_per_job))
    except (TypeError, ValueError):
        raise RetentionRefusedError("keep must be an integer")
    init_chat_database()
    # Portable per-job cap: explicit excess ids, newest kept.
    removed = 0
    with chat_connection() as db:
        jobs = db.execute(
            "SELECT DISTINCT job_name FROM job_runs").fetchall()
        for job in jobs:
            rows = db.execute(
                "SELECT rowid FROM job_runs WHERE job_name=? "
                "ORDER BY started_at DESC, rowid DESC LIMIT -1 "
                "OFFSET ?", (job["job_name"], keep)).fetchall()
            for row in rows:
                db.execute("DELETE FROM job_runs WHERE rowid=?",
                           (row["rowid"],))
                removed += 1
    return removed


def prune_conversation_events(
        keep_per_mission: int = CONVERSATION_EVENTS_KEEP_PER_MISSION
        ) -> int:
    """Keep the newest events per mission (or conversation
    when no mission is attached), drop older excess."""
    from .database import chat_connection, init_chat_database
    try:
        keep = max(1, int(keep_per_mission))
    except (TypeError, ValueError):
        raise RetentionRefusedError("keep must be an integer")
    init_chat_database()
    removed = 0
    with chat_connection() as db:
        scopes = db.execute(
            "SELECT DISTINCT mission_id, conversation_id FROM "
            "conversation_events").fetchall()
        for scope in scopes:
            rows = db.execute(
                """SELECT rowid FROM conversation_events WHERE
                mission_id=? AND conversation_id=? ORDER BY
                created_at DESC, rowid DESC LIMIT -1 OFFSET ?""",
                (scope["mission_id"], scope["conversation_id"],
                 keep)).fetchall()
            for row in rows:
                db.execute("DELETE FROM conversation_events "
                           "WHERE rowid=?", (row["rowid"],))
                removed += 1
    return removed


def run_retention(*, interface_keep: int = INTERFACE_EVENTS_KEEP,
                  job_keep: int = JOB_RUNS_KEEP_PER_JOB,
                  mission_keep: int =
                  CONVERSATION_EVENTS_KEEP_PER_MISSION
                  ) -> dict:
    """Run all retention passes. Returns per-table removed
    counts. dist_events, dist_conflicts and write_proposals
    are intentionally excluded (see module docstring)."""
    from .events import prune_events
    removed_events = prune_events(keep=interface_keep)
    removed_runs = prune_job_runs(keep_per_job=job_keep)
    removed_mission = prune_conversation_events(
        keep_per_mission=mission_keep)
    return {"interface_events": removed_events,
            "job_runs": removed_runs,
            "conversation_events": removed_mission,
            "excluded": ["dist_events", "dist_conflicts",
                         "write_proposals"]}
