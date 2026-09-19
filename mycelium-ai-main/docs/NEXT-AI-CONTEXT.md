# NEXT-AI-CONTEXT — continue Mycelium development here

Date: 2026-09-19. HEAD: `BIG #38 - build living automation`
(main, pushed to origin/main). Start with `git log --oneline -5`
and `git status` (a pre-existing `Mycelium/agent/agent_ui.py`
modification is NOT ours — leave it).

## Architecture in one paragraph

Local-first personal AI: coordinator (`:8000`, FastAPI + SQLite
WAL) is the authority (approvals, tasks, leases, missions);
INVENTory (`:8080`) is the world memory, read via GET-only
loopback bridge (`inventory_read.py`), written only via gated
proposals (`inventory_writes.py` + exact YES + verification);
Ollama/external models are advisors (never authority); desktop
agent is the only hands (pull-only, outbound). Provenance always;
health scoped; no shell/RCE; no background threads (jobs run on
explicit trigger). Tests: `pytest -v` per project with tmp DB
env vars (`MYCELIUM_DATABASE_PATH`, `MYCELIUM_CHAT_DATABASE_PATH`
before TestClient; `MYCELIUM_FABRICATION_DIR` for fab tests).
Full Mycelium suite: 1251 tests, batch-run (single run exceeds
10-min timeout); INVENTory: 179 + 1 pre-existing byte-size
failure (do not touch that test).

## What BIG #38 added (where)

- `coordinator/app/automation.py` — engine (runs/steps/bounds/
  resume, step executors on existing functions, closed gates)
- `main.py` — automation API + web routes, `/automation` pages,
  mission-detail link, morning section, packet section
- `events.py` — additive `automation.*` bus types
- `living_state.py` — automation counts (reasons only)
- `guide.py` — waiting/blocked/failed automation items
- `mobile.py` — automation quests in progress panel
- `ui.py` — subtle symbiosis/craft automation styling
- `reports.py` — automation morning section (allow-listed)
- `context_packet.py` — automation sections (v1 + v2 + markdown)
- Tests: `tests/test_big38_automation.py` (20).
- Scripts: `scripts/b38_smoke.py` (17 checks, tmp DBs),
  `scripts/b38_shots.py` (seed for screenshots).
- Docs: `docs/living-automation.md`,
  `docs/automation-security.md`,
  `docs/BIG38-final-report.md`.
- Lessons: closed step-kind allow-list (creation + drive);
  overnight subset; live gate re-check on resume (no cached
  verdicts); health regex blocks candidates; secret scan on
  write_propose payloads; capability escalation refused;
  no shell/RCE surface (static assert); provenance
  `ai-generated` + `human_verified=False`.

## Docs to read first

`docs/ARCHITECTURE_STATUS.md` (truth), `docs/ROADMAP.md` +
`docs/ROADMAP-V2.md` (BIG #39–40),
`docs/living-automation.md`, `docs/automation-security.md`,
`docs/conversation-intelligence.md`, `docs/mobile-mycelium.md`,
`docs/3d-workshop.md`, `docs/camera-ecosystem.md`,
`docs/living-ecosystem.md`, `docs/knowledge-lifecycle.md`,
`docs/research-routing.md`, `docs/context-packets.md`,
`docs/mycelium-ui-personality.md`, `docs/BIG38-final-report.md`
(§2 = commit/push record).

## Next BIG (from BIG38 report §21 / ROADMAP-V2)

BIG #39: Presence — per-recipient in-app delivery, morning "why
open Mycelium today" answer, overnight digest of queue +
discoveries + connections. Web push only with a real transport;
until then explicit UNAVAILABLE. Screenshots in `docs/r39-shots/`,
one commit `BIG #39 - ...`, push to `origin/main`.