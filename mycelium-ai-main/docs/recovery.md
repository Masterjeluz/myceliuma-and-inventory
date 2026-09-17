# Mission recovery (BIG #25)

Missions survive process restarts, coordinator restarts,
agent restarts, Ollama outages, offline nodes, stale leases,
partial completion and sleep/wake — because all state is
durable SQLite plus conditional updates (`save_mission`
races → 409, never silent overwrite).

## What happens on restart

1. `lifespan` runs `_v1_startup_scan()`: list non-terminal
   missions, `assess()` each, log verdicts. **Executes
   nothing.**
2. Each mission reconstructs: status, steps, current pointer,
   action bindings (a dispatched `dact-` without a valid
   binding is treated as suspect, never re-dispatched).
3. Verdicts:
   - `safe_to_resume` — only pending readout/analysis steps
     remain, pointer valid, no stale approvals. May tick
     through the bounded loop, explicitly.
   - `needs_reapproval` — any gated step pending/waiting, a
     stale binding, an unknown kind, or a bad pointer. Fresh
     human YES required; stale approvals never reused.
   - `waiting_agent` — a bound dispatched action is out; only
     the agent's report unblocks it.
   - `terminal` — observing only (+ one episodic memory).
4. Resume paths (all explicit):
   - `POST /api/v1/missions/recover` — report only
   - `POST /api/v1/missions/recover {"resume_safe": true}` —
     resumes read-only missions (max 5, 5 rounds each)
   - Command Center: “Ga verder…” does the same via chat

## Guarantees

- Idempotent steps: readout/analysis re-run safely; desktop
  actions are bound once (`action_bindings`, insert-if-absent).
- Retry limits: decisions carry `MAX_ATTEMPTS = 3` with
  5s/30s/120s backoff; budgets exhaust into REPLAN/BLOCKED,
  never infinite loops.
- Stale detection: node staleness 60s, task lease 300s / max
  3 attempts; coordinator epochs fence old writers.
- Context reconstruction: missions carry their
  `context_records`; the loop re-reads live state each tick.
