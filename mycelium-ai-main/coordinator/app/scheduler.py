"""Small in-process scheduler for bounded, read-only coordinator jobs.

The scheduler deliberately has a closed allowlist. It does not create or
dispatch queue tasks, invoke models, touch hardware, or cross approval gates.
Runs are recorded by the existing jobs module and kept to a bounded history.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from .jobs import SCHEDULED_JOBS, prune_scheduled_runs, run_job

logger = logging.getLogger(__name__)

_FALSE_VALUES = frozenset({"0", "false", "no", "off", "disabled"})
_STATUS: dict = {
    "running": False,
    "started_at": "",
    "last_runs": {},
}


def enabled() -> bool:
    """Background scheduling is on by default and has a simple opt-out."""
    return os.environ.get("MYCELIUM_BACKGROUND_SCHEDULER", "1").strip().lower() not in _FALSE_VALUES


def status() -> dict:
    """Return process-local schedule health without exposing internals."""
    return {
        "enabled": enabled(),
        "running": bool(_STATUS["running"]),
        "started_at": str(_STATUS["started_at"]),
        "jobs": [
            {"job_name": name, "interval_seconds": seconds,
             "safety": "bounded read-only"}
            for name, seconds in SCHEDULED_JOBS.items()
        ],
        "last_runs": {
            name: dict(item)
            for name, item in _STATUS["last_runs"].items()
        },
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _wait_or_stop(stop: asyncio.Event, seconds: float) -> bool:
    """Return True when shutdown was requested, False on timeout."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=max(0.1, seconds))
        return True
    except asyncio.TimeoutError:
        return False


async def run_scheduler(stop: asyncio.Event) -> None:
    """Run the fixed set of safe jobs on intervals until lifespan stops."""
    _STATUS["running"] = True
    _STATUS["started_at"] = _utc_now()
    deadlines = {
        name: time.monotonic() + interval
        for name, interval in SCHEDULED_JOBS.items()
    }
    logger.info("background_scheduler_started jobs=%s",
                ",".join(SCHEDULED_JOBS))
    try:
        while not stop.is_set():
            now = time.monotonic()
            due = [name for name, deadline in deadlines.items()
                   if deadline <= now]
            if not due:
                next_due = min(deadlines.values(), default=now + 60)
                if await _wait_or_stop(stop, next_due - now):
                    break
                continue

            for name in due:
                if stop.is_set():
                    break
                interval = SCHEDULED_JOBS[name]
                bucket = int(time.time() // interval)
                run_key = f"schedule:{name}:{bucket}"
                started_at = _utc_now()
                try:
                    result = await asyncio.to_thread(
                        run_job, name, {}, run_key=run_key)
                    prune_scheduled_runs()
                    _STATUS["last_runs"][name] = {
                        "run_id": result.get("run_id", ""),
                        "status": result.get("status", "unknown"),
                        "started_at": result.get("started_at", started_at),
                        "summary": result.get("summary", {}),
                    }
                    logger.info("background_job_finished name=%s status=%s",
                                name, result.get("status", "unknown"))
                except Exception as error:
                    _STATUS["last_runs"][name] = {
                        "status": "failed",
                        "started_at": started_at,
                        "error": str(error)[:300],
                    }
                    logger.exception("background_job_failed name=%s", name)
                finally:
                    # Avoid a catch-up storm after a slow DB or a laptop
                    # waking from sleep: each job runs at most once per loop.
                    deadlines[name] = time.monotonic() + interval
    finally:
        _STATUS["running"] = False
        logger.info("background_scheduler_stopped")


async def stop_scheduler(stop: asyncio.Event,
                         task: asyncio.Task | None) -> None:
    """Signal a clean shutdown and wait for any bounded job to finish."""
    stop.set()
    if task is not None:
        await task
