# NEXT-AI-CONTEXT — continue Mycelium development here

Date: 2026-09-18. HEAD: `BIG #34 - build camera ecosystem`
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
before TestClient). Full Mycelium suite: 1186 tests, batch-run
(single run exceeds 10-min timeout); INVENTory: 179 + 1
pre-existing byte-size failure (do not touch that test).

## What BIG #34 added (where)

- `coordinator/app/camera_ecosystem.py` — `cing_…` sessions
  (≤8 files, sha256 dedupe, per-file states, additive table),
  VLM wrapper (REAL Ollama / UNAVAILABLE fallback, stored
  distinguishably), per-label idempotent candidates, bounded
  possible-matches, connection-candidate link proposals,
  timeline from the shared bus, IN_APP fan-out to nodes.
- `main.py` — 9 API routes (`/api/v1/camera-sessions*`,
  `/observations/{id}/describe|propose-candidates`,
  `/camera-match`, `/camera-suggest-link`,
  `/camera-timeline`) + 5 web routes; Camera Lab page +
  8-step Insta360 guide; detail page (sessions, Describe /
  Propose / Review buttons, link form, timeline); mobile
  camera panel.
- `guide.py` — camera items (inbox files, undescribed
  observations with deep links).
- `symbiosis.py` — `obs_`/`obs-`/`cam_`/`cing_` prefixes so
  camera entities participate (regex allows `-`).
- Tests: `tests/test_big34_camera_ecosystem.py` (13).
- Scripts: `scripts/b34_smoke.py` (full chain on tmp DBs).
- Heading lesson (again): page `<h1>` strings are test
  contracts — reframe via paragraphs; fix double-numbering
  when mixing `<ol>` with manual "1." prefixes.
- Route lesson: `/api/v1/camera-sessions/{id}` + `/run`
  suffix is safe (no sub-path shadowing like nodes/{id}).

## Docs to read first

`docs/ARCHITECTURE_STATUS.md` (truth), `docs/ROADMAP.md` +
`docs/ROADMAP-V2.md` (BIG #35–40), `docs/camera-ecosystem.md`,
`docs/camera-workflow.md`, `docs/living-ecosystem.md`,
`docs/knowledge-lifecycle.md`, `docs/research-routing.md`,
`docs/context-packets.md`, `docs/mycelium-ui-personality.md`,
`docs/BIG34-final-report.md` (§19 = commit/push record).

## Next BIG (from BIG34 report §21 / ROADMAP-V2)

BIG #35: 3D Workshop — models ↔ projects ↔ materials ↔
fabrication as visible relations; verify loop with camera
observations; no printer transport claims. Constraints: no
new stores, existing gates, honest labels, tmp DBs,
screenshots in `docs/r35-shots/`, one commit `BIG #35 -
...`, push to `origin/main`.
