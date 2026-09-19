# NEXT-AI-CONTEXT — continue Mycelium development here

Date: 2026-09-20. HEAD: `BIG #44 - build the living solarpunk world`
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
state view, companion guide); BIG #44 makes /world the
primary experience: HUD + world objects + symbiosis network
+ craft world + campaign + energy + attention panels (all
best-effort, empty means absent), background gains solar +
needs signals (one loop, reduced-motion safe), graph draws
verified hardware with glow, guide explains dim nodes
(heartbeat/task/restore path), mobile shares the world
vocabulary. Presentation over real state only — no XP, no
scores, no second truth. Provenance always; health scoped;
no shell/RCE; no background threads (explicit triggers
only). Tests: `pytest -v` per project with tmp DB env vars
(`MYCELIUM_DATABASE_PATH`, `MYCELIUM_CHAT_DATABASE_PATH`
before TestClient; `MYCELIUM_FABRICATION_DIR` for fab tests;
`MYCELIUM_OPERATOR_KEY` for hardware verify tests). Testing
discipline (BIG #43+): targeted tests during dev,
touched-module regression, smoke for the BIG, FULL Mycelium
suite ONCE + FULL INVENTory suite ONCE at finalization only,
bounded batches (single run exceeds 10-min timeout; camera
device enumeration may log access-violation noise on
Windows — pre-existing, unrelated).

## What BIG #44 added (where)

- `world.py` (new) — world objects (10 closed kinds, href +
  text per object), `world_hud()`, `symbiosis_network()` +
  `symbiosis_seedlings()`, energy/discovery/research/node/
  campaign/craft collectors
- `main.py` — `_world_hud_html`, `_world_objects_html`,
  `_world_symbiosis_html`, `_world_craft_html`,
  `_world_campaign_html`, `_world_energy_html`,
  `_world_presence_html` wired into `world_page`;
  `_mobile_world_html` in the mobile page
- `ui.py` — data-energy/data-needs signals + JS (same loop);
  world CSS (hud, wobject kinds, symtree, energyflow,
  pixel/solar); GRAPH_JS verified glow + ring;
  `.verified-glow` style
- `worldgraph.py` — unchanged (verified flag already there
  from BIG #43; renderer now uses it)
- `mobile.py` — `world_panel()` + dashboard key
- `guide.py` — quiet/offline node cards gain heartbeat,
  last task, restore path, reality evidence links
- Tests: `tests/test_big44_world.py` (13).
- Scripts: `scripts/b44_smoke.py` (41 checks, fresh tmp DBs),
  `scripts/b44_shots.py` + `scripts/b44_screenshots.py`.
- Docs: `docs/living-solarpunk-world.md`,
  `docs/BIG44-final-report.md`.
- Lessons: page-embedded `<style>` contains UI comments —
  assert panel markup (`<h2>…</h2>`), not bare words;
  presence honestly derives items on empty DBs (no eligible
  node, inbox files) — mirror it, don't fight it; quest
  `note` steps skip ref validation (use entity kind to test
  malformed refs); never write def+docstring edits — always
  re-verify imports after touching mobile/main.

## Docs to read first

`docs/ARCHITECTURE_STATUS.md` (truth),
`docs/v2-ecosystem.md` (V2 contracts), `docs/ROADMAP.md` +
`docs/ROADMAP-V2.md`, `docs/living-solarpunk-world.md`,
`docs/living-game-layer.md`, `docs/quest-trails.md`,
`docs/hardware-verification.md`, `docs/presence-ecosystem.md`,
`docs/hardware-reality-layer.md`, `docs/context-packets.md`,
`docs/mobile-mycelium.md`,
`docs/BIG44-final-report.md` (§2 = commit/push record).

## Next BIG (not started)

BIG #45: nothing designed yet.
