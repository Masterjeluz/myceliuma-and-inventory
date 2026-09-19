# NEXT-AI-CONTEXT — continue Mycelium development here

Date: 2026-09-20. HEAD: `BIG #43 - build the living game layer`
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
BIG #42 hardened it (human hardware links, finance/energy
stores, quest trails, bounded mesh workflows); BIG #43 adds
the living game layer as presentation over real state:
campaigns group quests with live counts/current/next/evidence
(fake quests refuse, deleted quests mark MISSING, no XP),
`GET /api/v1/game/state` aggregates 10 sections read-only
(POST is 405), symbiosis reads strong/growing/seedling
(display only), the background reacts to 5 real-state signals
(research/discovery/verified/fab/offline, reduced-motion
safe), guide cards carry BLOCKED BY/UNLOCKS/EVIDENCE.
Provenance always; health scoped; no shell/RCE; no background
threads (explicit triggers only). Tests: `pytest -v` per
project with tmp DB env vars (`MYCELIUM_DATABASE_PATH`,
`MYCELIUM_CHAT_DATABASE_PATH` before TestClient;
`MYCELIUM_FABRICATION_DIR` for fab tests; `MYCELIUM_OPERATOR_KEY`
for hardware verify tests). Testing discipline (BIG #43+):
targeted tests during dev, touched-module regression, smoke
for the BIG, FULL Mycelium suite ONCE + FULL INVENTory suite
ONCE at finalization only, bounded batches (single run exceeds
10-min timeout; camera device enumeration may log
access-violation noise on Windows — pre-existing, unrelated).

## What BIG #43 added (where)

- `campaigns.py` (new) — campaign defs + live derivation
  (counts/current/next/evidence); `main.py` —
  `/api/v1/campaigns*` + `/campaigns` page (trail chain)
- `game.py` (new) — read-only `game_state()` (10 sections);
  `main.py` — `GET /api/v1/game/state` + `/game` page
- `ui.py` — living_bg gains data-research/discovery/verified/
  fab/offline + extended JS (same rAF loop, reduced-motion
  safe); game CSS (trail, campaign, strength, companion,
  pixel/solar accents); `guide_card` renders
  blocked_by/unlocks/evidence when present
- `guide.py` — `_item` gains blocked_by/unlocks/evidence;
  ecosystem items + campaign-context (🗺) cards populated
- `mobile.py` — `campaign_panel()` + dashboard key;
  `reports.py` — `campaigns` morning key (additive);
  `main.py` — morning campaigns section (only when data
  exists) + `_GAME_TITLE` game headers (presentation only)
- `worldgraph.py` — verified flag on hardware overlay nodes +
  human_verified edge provenance from the link store
- `main.py` — symbiosis strength bars + progression legend;
  craft page game framing + campaign/game cross-links
- `events.py` — campaign.created/updated (audit only)
- `schemas.py` — CampaignCreateBody
- Tests: `tests/test_big43_game.py` (15).
- Scripts: `scripts/b43_smoke.py` (47 checks, fresh tmp DBs),
  `scripts/b43_shots.py` + `scripts/b43_screenshots.py`.
- Docs: `docs/living-game-layer.md`,
  `docs/BIG43-final-report.md`.
- Lessons: an Edit that "succeeds" with identical old/new
  text can join lines — always verify with import/compile
  after ui/main edits; quest step kinds are closed
  (mission/task/entity/finance/energy/hardware/note — no
  "research" kind, use entity refs); `list_fabrications`
  returns models (model_dump first); morning_page is sync.

## Docs to read first

`docs/ARCHITECTURE_STATUS.md` (truth),
`docs/v2-ecosystem.md` (V2 contracts), `docs/ROADMAP.md` +
`docs/ROADMAP-V2.md`, `docs/living-game-layer.md`,
`docs/quest-trails.md`, `docs/hardware-verification.md`,
`docs/presence-ecosystem.md`, `docs/hardware-reality-layer.md`,
`docs/context-packets.md`, `docs/mobile-mycelium.md`,
`docs/BIG43-final-report.md` (§2 = commit/push record).

## Next BIG (direction only — not started)

BIG #44: deeper campaign arcs, craft↔quest cross-links,
energy-aware routing, evening digest. Nothing designed yet.
