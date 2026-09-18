# NEXT-AI-CONTEXT — continue Mycelium development here

Date: 2026-09-18. HEAD: `BIG #32 - build living knowledge and research network`
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
before TestClient). Full Mycelium suite: 1162 tests, batch-run
(single run exceeds 10-min timeout); INVENTory: 179 + 1
pre-existing byte-size failure (do not touch that test).

## What BIG #32 added (where)

- `coordinator/app/knowledge.py` — candidates + support +
  promotion (`knowledge_candidates` table); `GET/POST
  /api/v1/candidates*`, finding/observation/question → candidate,
  `/knowledge` + web forms.
- `worldgraph.py` — `filter_graph()` + memory/candidate/
  conversation overlays; `/world` Layers & truth panel.
- `node_client/main.py` — `research.fetch_url` executor;
  `main.py` eligible/routing/queue-seed/completion hook.
- `context_packet.py` — v2 knowledge section; `living_state.py`
  — 24h reasons; `notify_center.py` +9 types; `events.py` +8
  types; mobile remember/queue/missed; camera/dossier candidate
  buttons; `/3d` relations.
- Tests: `tests/test_big32_knowledge.py` (22).
- Route-conflict lesson (again): `/api/v1/nodes/{id}` shadows
  sub-paths — `/api/v1/eligible-nodes` used instead.
- F-string lesson: never split nested-quote f-strings across
  lines via implicit concatenation (SyntaxError even on 3.14).

## Docs to read first

`docs/ARCHITECTURE_STATUS.md` (truth), `docs/ROADMAP.md` +
`docs/ROADMAP-V2.md` (BIG #33–40), `docs/living-ecosystem.md`,
`docs/knowledge-lifecycle.md`, `docs/research-routing.md`,
`docs/context-packets.md`, `docs/mycelium-ui-personality.md`,
`docs/BIG32-final-report.md` (§21 = commit/push record).

## Next BIG (from BIG32 report §20 / ROADMAP-V2)

BIG #33: reviewed `research.extract` executor + per-node
capability matrix + queue fan-out. Constraints: no new stores,
existing gates, honest labels, tmp DBs, screenshots in
`docs/r33-shots/`, one commit `BIG #33 - ...`, push to
`origin/main`.
