"""Focused tests for the coordinator's bounded background scheduler."""

import asyncio

from coordinator.app import scheduler


def test_scheduler_runs_allowlisted_job_and_stops_cleanly(monkeypatch):
    monkeypatch.setattr(
        scheduler, "_STATUS",
        {"running": False, "started_at": "", "last_runs": {}},
    )
    monkeypatch.setattr(scheduler, "SCHEDULED_JOBS",
                        {"device_health": 0.1})
    monkeypatch.setattr(scheduler, "prune_scheduled_runs", lambda: 0)
    calls = []

    def fake_run_job(name, params, *, run_key):
        calls.append((name, params, run_key))
        return {
            "run_id": "job_test",
            "status": "completed",
            "started_at": "2026-01-01T00:00:00+00:00",
            "summary": {"devices": 0},
        }

    monkeypatch.setattr(scheduler, "run_job", fake_run_job)
    stop = asyncio.Event()

    async def exercise():
        task = asyncio.create_task(scheduler.run_scheduler(stop))
        for _ in range(50):
            if calls:
                break
            await asyncio.sleep(0.01)
        stop.set()
        await scheduler.stop_scheduler(stop, task)

    asyncio.run(exercise())

    assert calls
    name, params, run_key = calls[0]
    assert name == "device_health"
    assert params == {}
    assert run_key.startswith("schedule:device_health:")
    status = scheduler.status()
    assert status["running"] is False
    assert status["last_runs"]["device_health"]["status"] == "completed"
    assert status["last_runs"]["device_health"]["run_id"] == "job_test"


def test_scheduler_is_enabled_by_default_and_can_be_disabled(monkeypatch):
    monkeypatch.delenv("MYCELIUM_BACKGROUND_SCHEDULER", raising=False)
    assert scheduler.enabled() is True
    monkeypatch.setenv("MYCELIUM_BACKGROUND_SCHEDULER", "0")
    assert scheduler.enabled() is False


def test_scheduler_status_exposes_only_fixed_read_only_jobs(monkeypatch):
    monkeypatch.delenv("MYCELIUM_BACKGROUND_SCHEDULER", raising=False)
    monkeypatch.setattr(
        scheduler, "SCHEDULED_JOBS",
        {"watcher_scan": 600, "device_health": 300},
    )
    status = scheduler.status()
    assert status["enabled"] is True
    assert {job["job_name"] for job in status["jobs"]} == {
        "watcher_scan", "device_health"
    }
    assert all(job["safety"] == "bounded read-only"
               for job in status["jobs"])
