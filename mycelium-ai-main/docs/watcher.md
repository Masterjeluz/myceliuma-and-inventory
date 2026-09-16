# Watcher (BIG #11-15, Phase 1+) — IMPLEMENTED

Periodic world inspection as pure detectors over bounded
rows: stale/blocked/failed tasks, repeatedly failing
tasks, unfinished/stalled projects, forgotten objects,
dangling relationships, missing provenance, unverified AI
data, old ideas, orphan files, duplicate hashes,
unfinished designs, skill gaps, stale devices.

## Rules

- Findings carry kind, explanation, evidence
  (entity_refs), and read as "why this exists" (age,
  status, counts) — no AI-feeling ranking.
- Output is FINDING → explanation → evidence → affected
  entities → suggested next action → optional proposal.
- Never executes, never writes. Health findings only
  appear when the caller explicitly asks (the scan route
  stays health-free by default).
- Served at `GET /api/v1/watcher/scan`, on the `/watcher`
  page, inside morning reports, and as the `watcher_scan`
  job. Continuous observation (camera/sensor loops) is
  FUTURE and stays opt-in; no always-on microphone, no
  unbounded recording.
