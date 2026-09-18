# NEXT-AI-CONTEXT — continue Mycelium development here

Date: 2026-09-18. HEAD: `BIG #31 - activate the living ecosystem`
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
before TestClient). Full Mycelium suite: 1140 tests, batch-run
(single run exceeds 10-min timeout); INVENTory: 179 + 1
pre-existing byte-size failure (do not touch that test).

## What BIG #31 added (where)

- `coordinator/app/context_engine.py` — `compose(intent, ...)`,
  `record_trace/recent_traces`, `get_mode/set_mode` (tables
  `command_traces`, `system_mode`).
- `coordinator/app/living_state.py` — `current_state()`; rendered
  by `ui.shell()` topbar on every page.
- `coordinator/app/context_packet.py` — v2 (`build_packet_v2`,
  `render_packet_v2_markdown`); v1 untouched.
- `coordinator/app/ecosystem.py` — `node_roles`, `discoveries`,
  clickable notification links.
- `coordinator/app/conversation_bridge.py` — `compare_imports`,
  `render_import_markdown`.
- `coordinator/app/vision_ingest.py` — `FileIngestAdapter`,
  `list_inbox_files` (camera dir = system temp `mycelium-cameras`).
- `node_client/bootstrap.py` + `mycelium-node.service`.
- `main.py` routes: `/api/v1/state`, `/context/compose`,
  `/context/packet2`, `/context/packet.md`, `/command/traces`,
  `/api/v1/search` + `/search`, `/writes` + `/web/links|objects|
  writes/*`, `/cameras/{id}` + ingest-file + `/camera-inbox`,
  `/node-roles`, `/mode`, `/discoveries`, `/imports-compare`,
  import markdown/relevance, `/research/queue*`.
- Route-conflict lesson: `/api/v1/nodes/{id}` etc. shadow
  sub-paths — use distinct prefixes (`/node-roles`,
  `/camera-inbox`, `/imports-compare`, `/linux-nodes`,
  `/conversation-imports` list at `/api/v1/conversation-imports`).
- Tests: `tests/test_big31_activation.py` (16).

## Docs to read first

`docs/ARCHITECTURE_STATUS.md` (truth), `docs/ROADMAP.md`
(PHASE R), `docs/living-ecosystem.md`, `docs/context-packets.md`,
`docs/overnight-research.md`, `docs/mycelium-ui-personality.md`,
`docs/BIG31-final-report.md` (§21 = next BIG).

## Next BIG (from final report §21)

BIG #32: candidate→memory promotion UX + Linux research executors
+ graph layer filters. Constraints: no new stores, existing gates,
honest labels, tmp DBs, screenshots in `docs/r32-shots/`, one
commit `BIG #32 - ...`, push to `origin/main`.
