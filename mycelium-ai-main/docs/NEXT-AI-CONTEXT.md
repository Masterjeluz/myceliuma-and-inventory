# NEXT-AI-CONTEXT — continue Mycelium development here

Date: 2026-09-18. HEAD: `BIG #36 - build mobile Mycelium`
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
Full Mycelium suite: 1215 tests, batch-run (single run exceeds
10-min timeout); INVENTory: 179 + 1 pre-existing byte-size
failure (do not touch that test).

## What BIG #36 added (where)

- `coordinator/app/mobile.py` — read-only surface logic:
  `dashboard()` snapshot, `approval_cards()` (desktop/write/
  mission triage with scope text), `notification_cards()`
  (deeplinks from related_* + type map), `packet_preview()`,
  `camera_panel()`, `craft_panel()`, `symbiosis_panel()`,
  `nodes_panel()` (+ BIG37 mesh path, read-only),
  `progress_panel()` (backend states only).
- `main.py` — `/mobile` restructured (NOW/WAITING/ACTIVE/
  INPUT/GUIDE/CAMERA/PACKET/CRAFT/SYMBIOSIS/NODES/RECENT),
  `GET /api/v1/mobile/dashboard`, section helpers,
  `web_chat` hardening (oversized input → redirect, not 500).
- `scripts/mycelium-notify.py` — `start`, `waiting` (alias),
  `failed` alongside `status`/`need`/`done`.
- Tests: `tests/test_big36_mobile.py` (16).
- Scripts: `scripts/b36_smoke.py` (15 checks, tmp DBs).
- Docs: `docs/mobile-mycelium.md`.
- Mobile contract strings (tests depend on them): INPUT,
  RESULT, Quick actions, "Hoe gebruik ik Mycelium",
  "YES, doorgaan", "Review writes", "Copy context",
  "Camera Lab", "Workbench", "Notifications", node ids,
  "Remember this", "Look into this", "What did we miss".
- Lesson: non-YES decision text REJECTS writes (never
  approves); replayed mission YES is idempotent.

## Docs to read first

`docs/ARCHITECTURE_STATUS.md` (truth), `docs/ROADMAP.md` +
`docs/ROADMAP-V2.md` (BIG #37–40), `docs/mobile-mycelium.md`,
`docs/3d-workshop.md`, `docs/camera-ecosystem.md`,
`docs/living-ecosystem.md`, `docs/knowledge-lifecycle.md`,
`docs/research-routing.md`, `docs/context-packets.md`,
`docs/mycelium-ui-personality.md`,
`docs/BIG36-final-report.md` (§2 = commit/push record).

## Next BIG (from BIG36 report §22 / ROADMAP-V2)

BIG #37: Conversation intelligence — repeated-theme
detection, decision/promise tracking, contradiction
surfacing, import→research proposals; analysis stays
OBSERVATION/CANDIDATE. Constraints: no new stores,
existing gates, honest labels, tmp DBs, screenshots in
`docs/r37-shots/`, one commit `BIG #37 - ...`, push to
`origin/main`.
