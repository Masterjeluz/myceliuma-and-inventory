# NEXT-AI-CONTEXT — continue Mycelium development here

Date: 2026-09-19. HEAD: `BIG #40 - build presence ecosystem`
(main, pushed to origin/main). Start with `git log --oneline -5`
and `git status` (a pre-existing `Mycelium/agent/agent_ui.py`
modification is NOT ours — leave it; `scripts/b38_screenshots.py`
is an untracked BIG #38 leftover — leave it).

## Architecture in one paragraph

Local-first personal AI: coordinator (`:8000`, FastAPI + SQLite
WAL) is the authority (approvals, tasks, leases, missions);
INVENTory (`:8080`) is the world memory, read via GET-only
loopback bridge (`inventory_read.py`), written only via gated
proposals (`inventory_writes.py` + exact YES + verification);
Ollama/external models are advisors (never authority); desktop
agent is the only hands (pull-only, outbound). Presence
(`presence.py`, BIG #40) derives attention live from existing
stores — no duplicate state; only operator SEEN/DEFERRED is
stored. Priority is deterministic rules with reasons (never an
LLM). Nodes report telemetry/hardware/compute/energy on
heartbeat (BIG #39); health is derived. Provenance always;
health scoped; no shell/RCE; no background threads (jobs and
notify fan-out run on explicit trigger). Tests: `pytest -v`
per project with tmp DB env vars (`MYCELIUM_DATABASE_PATH`,
`MYCELIUM_CHAT_DATABASE_PATH` before TestClient;
`MYCELIUM_FABRICATION_DIR` for fab tests). Testing discipline:
targeted tests during dev, full Mycelium suite ONCE + full
INVENTory suite ONCE at finalization, bounded batches (single
run exceeds 10-min timeout). Counts: 1356 Mycelium green;
INVENTory 179 + 1 pre-existing byte-size failure (do not touch
that test).

## What BIG #40 added (where)

- `coordinator/app/presence.py` — attention engine (12
  collectors, deterministic scoring + reasons, triage store
  SEEN/DEFERRED, 5 bands, RESOLVED/EXPIRED memory,
  progression, overnight digest, dedup IN_APP fan-out)
- `main.py` — presence API + `/web/presence` forms +
  `/presence` page, mobile presence bands, morning presence
  sections, offline card dimming
- `mobile.py` — dashboard `presence` bands + `greeting` +
  `progression`
- `ui.py` — `presence_card` (gate-exact YES/NO, OPEN, DEFER),
  guide AFTERWARDS line, presence CSS (reduced-motion safe),
  topbar presence counts → `/presence`
- `guide.py` — `after` on every guide item (honest mechanics)
- `reports.py` — 7 presence morning sections (MAX_BLOCKS 24)
- `schemas.py` — `PresenceTriageBody`, `PresenceNotifyBody`
- `notify_center.py` — 4 additive kinds
  (`mission_blocked`, `contradiction_detected`,
  `automation_waiting`, `fabrication_waiting`) + public
  `severity_for` (store carries severity bucket in `type`;
  dedup matches on severity+title)
- Tests: `tests/test_big40_presence.py` (31).
- Scripts: `scripts/b40_smoke.py` (49 checks, tmp DBs,
  fresh DBs each run), `scripts/b40_shots.py` +
  `scripts/b40_screenshots.py`.
- Docs: `docs/presence-ecosystem.md`,
  `docs/BIG40-final-report.md`.
- Lessons: candidate states are
  observation/candidate/supported (ACTIVE_STATES); severity
  bucket ≠ kind in notifications store; non-YES decisions
  deny fail-closed (`rejected`); smoke reruns need fresh
  DBs (script clears its own tmp).

## Docs to read first

`docs/ARCHITECTURE_STATUS.md` (truth), `docs/ROADMAP.md` +
`docs/ROADMAP-V2.md` (BIG #41),
`docs/presence-ecosystem.md`,
`docs/hardware-reality-layer.md`, `docs/living-automation.md`,
`docs/automation-security.md`,
`docs/conversation-intelligence.md`, `docs/mobile-mycelium.md`,
`docs/3d-workshop.md`, `docs/camera-ecosystem.md`,
`docs/living-ecosystem.md`, `docs/knowledge-lifecycle.md`,
`docs/research-routing.md`, `docs/context-packets.md`,
`docs/mycelium-ui-personality.md`, `docs/BIG40-final-report.md`
(§2 = commit/push record).

## Next BIG (from BIG40 report §12 / ROADMAP-V2)

BIG #41: Mycelium V2 — the coherent autonomous local-first
ecosystem: conversation → idea → research → node →
observation → candidate → memory → relation → project →
fabrication → verification → morning, provenance at every
link, Jelles approving everything consequential. Deepen
remote mesh execution, grow quests into the game layer.
Screenshots in `docs/r41-shots/`, one commit `BIG #41 - ...`,
push to `origin/main`.
