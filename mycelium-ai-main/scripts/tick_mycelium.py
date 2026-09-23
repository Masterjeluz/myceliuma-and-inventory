"""Mycelium tick loop: give the coordinator time without adding logic.

Calls ONLY existing read-only/report endpoints, in a fixed order:
health gate -> lease sweep -> jobs -> optional mission tick ->
ownership snapshot.
Fail-closed: an unhealthy coordinator aborts before any other call.
The sweep calls only the existing expiry rules (requeue below
MAX_ATTEMPTS, fail at the limit, block physical-uncertain work);
it creates nothing, executes nothing, extends no lease.
No scheduler inside the coordinator, no new endpoints, no model calls,
no approvals, no physical actions. Idempotent via date-based run_key
(the server revalidates job names itself).

Usage:
    python scripts/tick_mycelium.py --once
    python scripts/tick_mycelium.py --repeat-seconds 600 --max-ticks 144
    python scripts/tick_mycelium.py --with-mission-tick --once
"""

import argparse
import datetime
import json
import sys
import time
import urllib.request
import urllib.error

# Read-only/report jobs only. health_import excluded: its default
# mock provider writes synthetic samples. memory_consolidation and
# skill_discover without params are honest no-ops; excluded to keep
# every tick side-effect-light (morning_report + job_runs rows only).
TICK_JOBS = (
    "watcher_scan",
    "device_health",
    "inventory_reconcile",
    "research_process",
    "morning_report",
)

RUNNABLE_MISSION_STATUS = "running"


class TickRefusedError(ValueError):
    """Local policy refused a tick step; nothing was sent."""


def utc_date_key(now=None):
    moment = now or datetime.datetime.now(datetime.timezone.utc)
    return moment.strftime("%Y-%m-%d")


def http_call(base_url, timeout):
    """Build the default urllib transport. Returns call(method, path, body)."""
    base = str(base_url or "").rstrip("/")

    def call(method, path, body=None):
        if not str(path or "").startswith("/api/v1/"):
            raise TickRefusedError(
                f"tick only calls /api/v1/*, refusing {path!r}")
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(
                    request, timeout=int(timeout)) as response:
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            raise TickRefusedError(
                f"{method} {path} -> HTTP {error.code}") from error
        except OSError as error:
            raise TickRefusedError(
                f"{method} {path} unreachable: {error}") from error
        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except ValueError as error:
            raise TickRefusedError(
                f"{method} {path} returned non-JSON") from error

    return call


def check_health(call):
    """Fail-closed gate: only a healthy coordinator gets ticked."""
    try:
        body = call("GET", "/api/v1/health")
    except TickRefusedError:
        return False
    return isinstance(body, dict) and body.get("status") == "healthy"


def run_tick_jobs(call, date_key):
    """Run the fixed read-only job set. One job failing never
    blocks the others; every outcome is reported honestly."""
    results = []
    for job in TICK_JOBS:
        try:
            outcome = call("POST", "/api/v1/jobs/run", {
                "job_name": job,
                "params": {},
                "run_key": f"tick-{date_key}-{job}",
            })
            results.append({"job": job, "ok": True,
                            "summary": outcome if isinstance(
                                outcome, dict) else {"raw": outcome}})
        except TickRefusedError as error:
            results.append({"job": job, "ok": False,
                            "error": str(error)[:300]})
    return results


def sweep_leases(call):
    """Recover expired leases via the maintenance endpoint (same
    rules as the claim path). A coordinator without the endpoint
    reports an error instead of failing the whole tick."""
    try:
        outcome = call("POST", "/api/v1/maintenance/sweep-leases")
    except TickRefusedError as error:
        return {"ok": False, "error": str(error)[:300]}
    if not isinstance(outcome, dict):
        return {"ok": False, "error": "unexpected shape"}
    return {"ok": True, "tasks": outcome.get("tasks"),
            "desktop_actions": outcome.get("desktop_actions")}


def select_runnable_mission(missions):
    """First mission with status 'running' in API order, else None.
    Draft/paused/terminal missions are never ticked by the loop."""
    if not isinstance(missions, list):
        return None
    for entry in missions:
        if not isinstance(entry, dict):
            continue
        if entry.get("status") == RUNNABLE_MISSION_STATUS:
            mission_id = str(entry.get("mission_id", "")).strip()
            if mission_id:
                return mission_id
    return None


def tick_mission(call, mission_id):
    try:
        outcome = call(
            "POST", f"/api/v1/missions/{mission_id}/tick")
    except TickRefusedError as error:
        return {"ticked": mission_id, "ok": False,
                "error": str(error)[:300]}
    return {"ticked": mission_id, "ok": True,
            "summary": outcome if isinstance(outcome, dict)
            else {"raw": outcome}}


def ownership_snapshot(call):
    """Read-only task ownership from the existing list endpoint:
    id/kind/status/owner/attempts/lease. No mission link exists on
    the tasks table, so none is reported (never invented)."""
    try:
        rows = call("GET", "/api/v1/tasks")
    except TickRefusedError as error:
        return {"ok": False, "error": str(error)[:300], "tasks": []}
    if not isinstance(rows, list):
        return {"ok": False, "error": "unexpected shape",
                "tasks": []}
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        items.append({
            "id": row.get("id"),
            "kind": row.get("kind"),
            "status": row.get("status"),
            "assigned_node_id": row.get("assigned_node_id"),
            "attempt_count": row.get("attempt_count", 0),
            "lease_until": row.get("lease_until"),
        })
    return {"ok": True, "tasks": items}


def run_tick(call, date_key, with_mission_tick=False):
    """One bounded tick pass. Pure orchestration over the injected
    transport; safe to unit-test with a fake callable."""
    if not check_health(call):
        return {"ok": False, "aborted": "coordinator not healthy",
                "sweep": None, "jobs": [], "mission_tick": None,
                "ownership": {"ok": False, "tasks": []}}
    swept = sweep_leases(call)
    jobs = run_tick_jobs(call, date_key)
    mission_tick = None
    if with_mission_tick:
        try:
            missions = call("GET", "/api/v1/missions")
        except TickRefusedError as error:
            missions = None
            mission_tick = {"ticked": None, "ok": False,
                            "error": str(error)[:300]}
        if missions is not None:
            mission_id = select_runnable_mission(missions)
            if mission_id is None:
                mission_tick = {"ticked": None, "ok": True,
                                "note": "no running mission"}
            else:
                mission_tick = tick_mission(call, mission_id)
    ownership = ownership_snapshot(call)
    errors = [job for job in jobs if not job["ok"]]
    if not swept["ok"]:
        errors.append(swept)
    if mission_tick is not None and not mission_tick["ok"]:
        errors.append(mission_tick)
    if not ownership["ok"]:
        errors.append(ownership)
    return {"ok": not errors, "aborted": None, "sweep": swept,
            "jobs": jobs, "mission_tick": mission_tick,
            "ownership": ownership}


def arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="Mycelium tick loop (time only, no logic)")
    parser.add_argument("--coordinator",
                        default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--once", action="store_true",
                        help="Single tick pass, then exit (default)")
    parser.add_argument("--repeat-seconds", type=float, default=0.0,
                        help="Loop with this pause; requires --max-ticks")
    parser.add_argument("--max-ticks", type=int, default=1)
    parser.add_argument("--with-mission-tick", action="store_true",
                        help="Also tick the first running mission "
                             "(off by default)")
    return parser.parse_args(argv)


def main(argv=None):
    config = arguments(argv)
    call = http_call(config.coordinator, config.timeout)
    if config.repeat_seconds and config.repeat_seconds > 0:
        if config.max_ticks < 1:
            print(json.dumps({"ok": False,
                              "error": "--repeat-seconds needs "
                                       "--max-ticks >= 1"}))
            return 1
        passes = []
        for _ in range(min(config.max_ticks, 10000)):
            summary = run_tick(
                call, utc_date_key(),
                with_mission_tick=config.with_mission_tick)
            passes.append(summary)
            if len(passes) >= config.max_ticks:
                break
            time.sleep(config.repeat_seconds)
        ok = all(item["ok"] for item in passes)
        print(json.dumps({"ok": ok, "passes": len(passes),
                          "ticks": passes}))
        return 0 if ok else 1
    summary = run_tick(call, utc_date_key(),
                       with_mission_tick=config.with_mission_tick)
    print(json.dumps(summary))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
