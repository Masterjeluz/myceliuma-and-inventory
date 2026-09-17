# Autonomous missions (BIG #21 → #24 → #25)

## The loop

```
plan → execute → observe → evaluate → DECIDE → continue
```

`mission_loop.run_loop()` drives one mission until a gate, a
terminal state, or the round budget (max 10 per call). It adds
no execution power: it calls `executor.tick()`, reads the
gates, and stops at every one of them.

## Decisions (BIG #24, `decisions.py`)

After each observation the current step evaluates to one
explicit state:

| Decision | Meaning |
|---|---|
| CONTINUE | Step succeeded (or pending + read-only) — evaluate next |
| RETRY | Read-only step failed, attempts left — bounded backoff |
| REPLAN | Retries exhausted — revised plan needs a new human YES |
| WAITING_FOR_HUMAN | Exact gate named (desktop YES, write YES, physical YES…) |
| WAITING_FOR_AGENT | Dispatched action is out — agent report unblocks |
| BLOCKED | Cannot proceed safely — human reviews |
| FAILED / COMPLETED / CANCELLED | Mirrors terminal executor state only |

`decide()` is a pure function: it never mutates, never
approves, and the LLM never decides — provider advice is
evidence at most. A failed step never fails the whole mission
by itself; `POST /api/v1/missions/{id}/decide` exposes the
evaluation read-only.

## Recovery (BIG #25, `recovery.py`, `recovery.md`)

Missions persist in SQLite, so they survive restarts. Recovery
makes resuming safe and explicit — see `recovery.md`.
