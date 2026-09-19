# NEXT-AI-CONTEXT — continue Mycelium development here

Date: 2026-09-19. HEAD: `BIG #41 - build Mycelium V2 foundation`
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
agent is the only hands (pull-only, outbound). V2
(`docs/v2-ecosystem.md`, BIG #41) unifies BIG #1–40 systems:
mesh delegation pins targets through the existing task queue
(validate → auth → precheck → create → assign → rollback;
target must still claim); routing explains verdicts
(waiting/blocked/unavailable) + workload ordering; node
reality exposes trust (ADVERTISED/OBSERVED, VERIFIED reserved
for human links) + current task; presence/attention derives
live (only SEEN/DEFERRED stored); priority is deterministic
rules (never an LLM). Provenance always; health scoped; no
shell/RCE; no background threads (explicit triggers only).
Tests: `pytest -v` per project with tmp DB env vars
(`MYCELIUM_DATABASE_PATH`, `MYCELIUM_CHAT_DATABASE_PATH`
before TestClient; `MYCELIUM_FABRICATION_DIR` for fab tests).
Testing discipline: targeted tests during dev, module tests
for changed areas, smoke for the BIG, FULL Mycelium suite
ONCE + FULL INVENTory suite ONCE near the end, bounded
batches (single run exceeds 10-min timeout). Counts: 1380
Mycelium green; INVENTory 179 + 1 pre-existing byte-size
failure (do not touch that test).

## What BIG #41 added (where)

- `routing.py` — rejection verdicts, `prefer_idle`, `explain_decision`
- `nodemesh.py` — targeted delegation (exact-cap pin, timeout,
  clipped reason); `main.py` — `/mesh/preview`, `/mesh/delegate`
  (auth→validate→precheck→create→assign→rollback), route `why`,
  `current_task`, `/nodes/{id}/reality`, `/ecosystem/overview`,
  world strip, craft states
- `schemas.py` — `MeshDelegateBody`, `MeshPreviewBody`
- `events.py` — additive `task.delegated` audit type
- `worldgraph.py` — attention counts (boundary-matched)
- `ecosystem.py` — `ecosystem_overview` (8 answers, sources)
- `craft.py` — `stage_states` (✓/●/○/!)
- `symbiosis.py` — V2 prefixes + closed predicates
- `guide.py` — research unlock + blocked items (shared
  readiness; fixed wolf-crying inline check)
- `presence.py` — craft gaps in morning discoveries
- `mobile.py`/`ui.py` — current-task lines, node-tempo
  background (capped, reduced-motion safe)
- `notify_center.py` — public `severity_for`
- `scripts/mycelium-notify.py` — `blocked`, waiting guidance,
  `checklist`
- Tests: `tests/test_big41_v2.py` (24).
- Scripts: `scripts/b41_smoke.py` (54 checks, fresh tmp DBs),
  `scripts/b41_shots.py` + `scripts/b41_screenshots.py`.
- Docs: `docs/v2-ecosystem.md`, `docs/BIG41-final-report.md`.
- Lessons: candidate ACTIVE_STATES; severity bucket ≠ kind;
  pydantic bounds fire before engine clipping (reason ≤2000,
  engine clips to 200); smoke reruns need fresh DBs; raw
  registry rows lack fresh/auth flags (reuse readiness);
  cp1252 consoles need encoding-safe prints.

## Docs to read first

`docs/ARCHITECTURE_STATUS.md` (truth),
`docs/v2-ecosystem.md` (V2 contracts), `docs/ROADMAP.md` +
`docs/ROADMAP-V2.md` (BIG #42), `docs/presence-ecosystem.md`,
`docs/hardware-reality-layer.md`, `docs/living-automation.md`,
`docs/automation-security.md`,
`docs/conversation-intelligence.md`, `docs/mobile-mycelium.md`,
`docs/3d-workshop.md`, `docs/camera-ecosystem.md`,
`docs/living-ecosystem.md`, `docs/knowledge-lifecycle.md`,
`docs/research-routing.md`, `docs/context-packets.md`,
`docs/mycelium-ui-personality.md`, `docs/BIG41-final-report.md`
(§2 = commit/push record).

## Next BIG (from BIG41 report §23 / ROADMAP-V2)

BIG #42: Ecosystem hardening + first V2 workflows — human
link store for hardware verification (unlock VERIFIED),
finance/energy entity stores (complete the symbiosis map),
mission templates chaining mesh delegation into craft chains,
unified quest trails. Screenshots in `docs/r42-shots/`, one
commit `BIG #42 - ...`, push to `origin/main`.
