# NEXT-AI-CONTEXT — continue Mycelium development here

Date: 2026-09-20. HEAD: `BIG #45 - finish living ecosystem connections`
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
(`docs/v2-ecosystem.md`, BIG #41) unifies BIG #1–40 systems;
BIG #42 hardened it (links, finance/energy, quests,
workflows); BIG #43 added the game layer (campaigns, game
state view, companion guide); BIG #44 made /world the
primary experience (HUD + objects + symbiosis + craft +
campaign + energy + attention); BIG #45 adds the living
connections view over it all (`connections.py`: unified
entity connections, cross-project network over shared
records, campaign ecosystem, Guide-vocabulary detail,
POSSIBLE discovery — read-only over symbiosis, finance
(amounts never leak), energy, hardware, quests, campaigns,
research, registry nodes + claimed tasks; bare names must
exist in a registry or refuse 422). Presentation over real
state only — no XP, no scores, no second truth. Provenance
always; health scoped; no shell/RCE; no background threads
(explicit triggers only). Tests: `pytest -v` per project with
tmp DB env vars (`MYCELIUM_DATABASE_PATH`,
`MYCELIUM_CHAT_DATABASE_PATH` before TestClient;
`MYCELIUM_FABRICATION_DIR` for fab tests;
`MYCELIUM_OPERATOR_KEY` for hardware verify tests). Testing
discipline (BIG #43+): targeted tests during dev,
touched-module regression, smoke for the BIG, FULL Mycelium
suite ONCE + FULL INVENTory suite ONCE at finalization only,
bounded batches (single run exceeds 10-min timeout; camera
device enumeration may log access-violation noise on
Windows — pre-existing, unrelated).

## What BIG #45 added (where)

- `connections.py` (new) — `entity_connections()`,
  `project_network()` (shared-record cross-links only),
  `campaign_ecosystem()`, `connection_detail()`,
  `possible_connections()`; `_check_entity` (prefixes pass,
  bare names need node registry or live-link device_ref),
  `_known_device_ref`, device-side hardware lookup
- `main.py` — `GET /api/v1/connections*` (entity, network,
  detail, campaign, possible), `/connections` detail page,
  `_world_connections_html` (focused groups + unfocused
  clusters) in `world_page`, morning `connections` builder
- `guide.py` — possible-connection card (WHY PROPOSED /
  gate / blocked_by / unlocks / evidence) + node
  research-readiness card
- `mobile.py` — `connected_panel()` (CONNECTED / WAITING /
  DISCOVERED) + dashboard key
- `presence.py` — additive `campaign_blocked` type (needs,
  88, "campaign chain blocked")
- `reports.py` — `connections` morning key (additive)
- `ui.py` — `conn-cluster` CSS, `data-proposed` signal +
  JS (same loop, reduced-motion safe)
- Tests: `tests/test_big45_connections.py` (16).
- Scripts: `scripts/b45_smoke.py` (43 checks, fresh tmp DBs;
  claims via the real pull endpoint before asserting
  WORKING — delegation only pins), `scripts/b45_shots.py`
  (+ `shots_ids.json`) + `scripts/b45_screenshots.py`.
- Docs: `docs/BIG45-final-report.md`.
- Lessons: delegation leaves tasks queued+pinned — claim
  before asserting WORKING; `_assigned_tasks_map` emits
  `task_id` (older readers expect `id` — accept both at
  the consumer); the hardware store has no device filter —
  scan live links for device-side lookups.

## Docs to read first

`docs/ARCHITECTURE_STATUS.md` (truth),
`docs/v2-ecosystem.md` (V2 contracts), `docs/ROADMAP.md` +
`docs/ROADMAP-V2.md`, `docs/living-solarpunk-world.md`,
`docs/living-game-layer.md`, `docs/quest-trails.md`,
`docs/hardware-verification.md`, `docs/presence-ecosystem.md`,
`docs/hardware-reality-layer.md`, `docs/context-packets.md`,
`docs/mobile-mycelium.md`,
`docs/BIG45-final-report.md` (§2 = commit/push record).

## Next BIG (not started)

BIG #46: nothing designed yet.
