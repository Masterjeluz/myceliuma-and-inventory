# NEXT-AI-CONTEXT — continue Mycelium development here

Date: 2026-09-19. HEAD: `BIG #37 - build conversation intelligence`
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
Full Mycelium suite: 1231 tests, batch-run (single run exceeds
10-min timeout); INVENTory: 179 + 1 pre-existing byte-size
failure (do not touch that test).

## What BIG #37 added (where)

- `coordinator/app/conversation_intel.py` — deterministic
  extractive engine (`extractive-local`, no LLM): themes,
  decisions, promises, contradictions, categorized missed
  items, research proposals, entity links, symbiosis
  discoveries; sha256 fingerprint dedupe; additive
  `conversation_intel` table; explicit idempotent
  `materialize()` (candidate / research-queue / link);
  cross-conversation aggregate + REVISIT; timeline;
  overlay-shaped graph.
- `main.py` — 5 intel API routes + cross + 2 web routes;
  archive overview + detail sections + DISCOVERY banner +
  materialize buttons; `intel` flag in `_graph_data`;
  mobile Threads section + 4 quick actions.
- `worldgraph.py` — `_overlay_intel` + theme/decision/
  promise/question node types.
- `context_packet.py` — optional bounded `intelligence`
  section in the existing packet.
- `guide.py` — fresh-intel, REVISIT and contradiction items.
- `mobile.py` — `intel_panel()` in dashboard.
- Tests: `tests/test_big37_conversation_intel.py` (16).
- Scripts: `scripts/b37_smoke.py` (17 checks, tmp DBs).
- Docs: `docs/conversation-intelligence.md`.
- Lessons: `list_intel(conversation_id, limit, kind)` —
  limit is positional #2; notification `type` stores
  severity not kind (assert titles); symbiosis `proposed()`
  needs ≥2 valid entities; duplicate imports refuse by
  content hash (422); `/api/v1/missions` returns a bare
  list.

## Docs to read first

`docs/ARCHITECTURE_STATUS.md` (truth), `docs/ROADMAP.md` +
`docs/ROADMAP-V2.md` (BIG #38–40),
`docs/conversation-intelligence.md`,
`docs/mobile-mycelium.md`, `docs/3d-workshop.md`,
`docs/camera-ecosystem.md`, `docs/living-ecosystem.md`,
`docs/knowledge-lifecycle.md`, `docs/research-routing.md`,
`docs/context-packets.md`, `docs/mycelium-ui-personality.md`,
`docs/BIG37-final-report.md` (§2 = commit/push record).

## Next BIG (from BIG37 report §26 / ROADMAP-V2)

BIG #38: Living automation — observe → research → propose →
act → observe loops inside approved plans only; mission
templates chaining queue + candidates + writes; human gates
at every consequential step. Constraints: no new stores,
existing gates, honest labels, tmp DBs, screenshots in
`docs/r38-shots/`, one commit `BIG #38 - ...`, push to
`origin/main`.
