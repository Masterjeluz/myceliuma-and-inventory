# NEXT-AI-CONTEXT — continue Mycelium development here

Date: 2026-09-18. HEAD: `BIG #33 - build the living world`
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
before TestClient). Full Mycelium suite: 1173 tests, batch-run
(single run exceeds 10-min timeout); INVENTory: 179 + 1
pre-existing byte-size failure (do not touch that test).

## What BIG #33 added (where)

- `coordinator/app/symbiosis.py` — PROPOSED/SUPPORTED/VERIFIED
  over real edges + connection candidates; `GET
  /api/v1/symbiosis`, `/symbiosis` page.
- `coordinator/app/craft.py` — 12-stage craft tree on real
  neighborhoods + gaps with next actions; `GET /api/v1/craft`,
  `/craft` page.
- `coordinator/app/guide.py` — WHAT/WHY/NEXT from live state
  (approvals, candidates, missed items, open questions,
  inbox, fabs, quiet nodes, orphan projects); `GET
  /api/v1/guide`, `/guide` page + home/mobile strips.
- `coordinator/app/nodemesh.py` — node→coordinator→node
  validation (closed kinds, no wildcards/shell/secrets);
  `GET /api/v1/mesh/topology`, `POST /api/v1/mesh/validate`,
  mesh panel on `/nodes`.
- `coordinator/app/ui.py` — nav (Craft/Guide/Symbiosis),
  living CSS (spore canvas, reduced-motion safe), state chips,
  growth bar, quest trail, guide cards, empty states.
- `coordinator/app/main.py` — 5 APIs + 3 pages; quest steps
  on `/missions`; quick-action grid + needs-you on `/mobile`;
  framing passes on cameras/3d/conversations/research/agenda/
  activity (test-contract strings preserved).
- `scripts/mycelium-notify.py` — BEL + OSC 9/99 progress and
  approval/completion signals, ASCII fallback.
- Tests: `tests/test_big33_living_world.py` (11).
- Heading lesson (again): page `<h1>` strings are test
  contracts (`test_research_api`, `test_big30`) — reframe via
  paragraphs, never rename headings blindly.
- F-string lesson: no backslashes inside f-string expressions
  pre-3.12 (SyntaxError); build nested strings beforehand.

## Docs to read first

`docs/ARCHITECTURE_STATUS.md` (truth), `docs/ROADMAP.md` +
`docs/ROADMAP-V2.md` (BIG #34–40), `docs/living-ecosystem.md`,
`docs/knowledge-lifecycle.md`, `docs/research-routing.md`,
`docs/context-packets.md`, `docs/mycelium-ui-personality.md`,
`docs/BIG33-final-report.md` (§13 = commit/push record).

## Next BIG (from BIG33 report §12 / ROADMAP-V2)

BIG #34: camera ecosystem (multi-file ingest sessions,
observation → VLM advice → candidate guided flow, camera
detail timelines; Insta360 transport stays UNAVAILABLE until
a verified adapter exists). Constraints: no new stores,
existing gates, honest labels, tmp DBs, screenshots in
`docs/r34-shots/`, one commit `BIG #34 - ...`, push to
`origin/main`.
