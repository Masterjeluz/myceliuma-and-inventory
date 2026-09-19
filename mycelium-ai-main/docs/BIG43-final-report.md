# BIG #43 — eindrapport

## 1. Status

DONE — built, tested, smoked, screenshotted, documented,
committed, pushed. BIG #44 not started.

## 2. Commit SHA

`BIG #43 - build the living game layer` (SHA verified
against remote HEAD after push; see git log).

## 3. Files changed

New:
- `coordinator/app/campaigns.py` — campaign defs + live
  derivation (counts/current/next/evidence)
- `coordinator/app/game.py` — read-only `game_state()`,
  `presence_as_stakes`, `symbiosis_progression`,
  `craft_progression`
- `tests/test_big43_game.py` — 15 tests (campaigns, game
  state, companion, mobile, morning, pages, worldgraph,
  authority probes)
- `scripts/b43_smoke.py` — full chain on tmp DBs (47 checks,
  fresh DBs each run)
- `scripts/b43_shots.py` — seed data for screenshots
- `scripts/b43_screenshots.py` — server + Playwright capture
- `docs/r43-shots/` (9 PNGs)
- `docs/living-game-layer.md`
- `docs/BIG43-final-report.md` (this file)

Extended:
- `coordinator/app/main.py` — `/api/v1/campaigns*`,
  `GET /api/v1/game/state`, `/campaigns` + `/game` pages,
  morning campaigns section + `_GAME_TITLE` headers,
  symbiosis strength bars + legend, craft game framing
- `coordinator/app/ui.py` — living_bg gains 5 real-state
  signals + extended JS (same loop, reduced-motion safe),
  game CSS (trail/campaign/strength/companion/pixel/solar),
  `guide_card` companion fields
- `coordinator/app/guide.py` — `_item` gains
  blocked_by/unlocks/evidence; ecosystem items + 🗺 campaign
  cards populated
- `coordinator/app/mobile.py` — `campaign_panel()` +
  dashboard key
- `coordinator/app/reports.py` — `campaigns` morning key
  (additive)
- `coordinator/app/worldgraph.py` — verified flag on
  hardware overlay nodes + human_verified edge provenance
- `coordinator/app/events.py` — additive `campaign.created`,
  `campaign.updated` audit types
- `coordinator/app/schemas.py` — `CampaignCreateBody`
- `docs/NEXT-AI-CONTEXT.md`, `docs/ROADMAP-V2.md`,
  `README.md` (game bullet, structure, docs list, test
  discipline wording)

NOT in this commit (left untouched on purpose):
- `Mycelium/agent/agent_ui.py` — pre-existing local
  modification, not ours
- `scripts/b38_screenshots.py` — untracked BIG #38 leftover,
  not staged
- `inventory/` — zero changes

## 4. Campaign system

Defs hold title/description/quest ids only (`cmp_` table).
Live view: per-quest states, completed/total/blocked/waiting,
current quest, next actionable item with real href +
readiness reason, evidence links. Fake quest ids refuse
(422, incl. wildcard/malformed/duplicates/empty); deleted
quests render MISSING. No XP, no rewards. Refresh audits.

## 5. Quest progression

Quests unchanged (no second source of truth). Campaigns
chain them: example Solar Workshop 3/4 (✓ energy, ✓
hardware, ✓ research, ○ materials). `/campaigns` renders
the trail chain with ↓ links; completion derives from
finance CONFIRMED and verified links moving in the smoke
run (0/2 → 1/2).

## 6. Craft/game integration

Craft tree untouched logically; page gains gameplay framing
(what ✓/!/○ mean + campaign/game cross-links). Game view
shows quest-linked chains with stage glyphs via
`craft_progression`. COMPLETE still means evidence-backed.

## 7. Symbiosis progression

Display only: VERIFIED→strong, SUPPORTED→growing,
PROPOSED→seedling. Strength bars + legend on the symbiosis
page; "uncertain until reviewed" wording in game view.
Proposal input still strict; nothing promotes silently.

## 8. Presence/game integration

`presence_as_stakes`: same items, hrefs, priority — game
framing words added, original band kept per item. Offline
nodes read "quiet", approvals "player decisions",
candidates "knowledge opportunities". No semantics renamed
in the engine.

## 9. Living world

Background reacts to research tempo, discovery pulses,
verified mycelium threads, fabrication warmth, offline dim —
all clamped ints from real stores, one rAF loop, early
return on reduced-motion. Subtle by design; motion claims
no specific events.

## 10. Guide companion foundation

Cards render BLOCKED BY / UNLOCKS / EVIDENCE when present
(existing cards unchanged). Ecosystem items populated
(hardware→reality evidence, energy→blocker/unlock,
symbiosis→review links, quest→blocked step) plus 🗺
campaign cards (chain progress + next + evidence). No
hallucinated advice — every link opens a record.

## 11. Mobile

Dashboard gains `campaigns` (title, progress, current quest,
next action + href). Approval gates unchanged; a YES still
means YES.

## 12. Morning

`campaigns` section only when campaigns exist (asserted
absent otherwise). Game headers are presentation-only
(🌱/🎯/⚡/🔧/🧠/🌐/📌); report JSON titles stable.

## 13. Game-state API

`GET /api/v1/game/state`: world, campaigns, current_quest,
presence, craft, symbiosis, nodes, energy, workshop,
discoveries — each with named source, explicit empty on
failure, honesty note, derived provenance. POST is 405.
A view, not a database; approves nothing, executes nothing.

## 14. Security

- Fake/malformed/wildcard/duplicate/empty campaign inputs:
  422. Fake campaign/quest refresh/delete: 404. Traversal
  ids: 404/422.
- Game POST: 405. No approval, lease, claim, or write path
  reachable through campaigns/game/mobile additions.
- Secret scan, closed kinds, and claim gates untouched.
- No test weakened. No gate weakened. INVENTory untouched.

## 15. Tests

Test strategy per BIG #43 §14: targeted during dev
(15 new, green), touched-module regression (127 green:
big42/41/40/36/33, templates, reports, worldgraph/proxy),
smoke (47 green). Full Mycelium suite ONCE at finalization
(bounded batches, counts in run log). INVENTory ONCE at
finalization. No repeated full runs during development.

Full Mycelium suite: **1417 passed, 0 failed** across all
112 test files in bounded batches (217 + 411 + 432 + 357;
single run exceeds the 10-min tool timeout).

INVENTory suite: **179 passed + 1 pre-existing failure**
(`test_milestone_3_8.py::test_real_inventory_db_untouched`
byte-size; environmental, unchanged, test untouched).

## 16. Smoke

`scripts/b43_smoke.py` on tmp DBs: **47/47 OK** — nodes →
finance → quests → campaign (counts/current/next/evidence)
→ game state (10 sections + honesty + provenance) → guide
card → mobile panel → morning section + headers → 9 pages
→ real progress (0/2→1/2) → deleted quest MISSING → 8
refusal probes.

## 17. Screenshots

`docs/r43-shots/` (Edge headless, real seed data, reviewed):
world, game (world/campaign/current/symbiosis/stakes/mesh/
energy), campaign (3/4 trail + Next), quest, craft,
symbiosis, guide, mobile, morning.

## 18. REAL / TEST / SIMULATED / UNAVAILABLE

| Aspect | Label |
|--------|-------|
| Campaigns/quests/progress | REAL derived state |
| Game state | REAL view, no stored truth |
| Symbiosis strength | Display over REAL states |
| Background signals | Ambient, not data |
| Printer transport | UNAVAILABLE (unchanged) |
| Fab execution | SIMULATED (unchanged) |
| WEB_PUSH | UNAVAILABLE (unchanged) |
| Energy-aware routing | FUTURE (store ready) |

## 19. Limitations

- Campaigns have no web-form create yet (API + pages link
  to JSON; consistent with quests in BIG #42).
- Workflows still have no cross-step result piping.
- Quest `entity` steps link out without deriving completion.
- Evening digest, campaign arcs, craft↔quest deep links are
  BIG #44 direction only — not designed here.

## 20. What Jelles can use tomorrow

1. Open `/campaigns` — build "Solar Workshop" from real
   quest ids, follow the trail chain and Next action
2. Open `/game` — world, campaign, stakes, mesh, energy in
   one living view; every line links somewhere real
3. Read the guide's 🗺 card — WHAT/WHY/NEXT/BLOCKED
   BY/UNLOCKS/EVIDENCE for the live chain
4. Check `/morning` — 🎯 campaign appears only when it
   exists; 📌 shows what needs you
5. Watch the background breathe with real activity
   (and die completely under reduced-motion)
6. Re-prove anything with `b43_smoke.py` (47 checks)

## 21. Recommended BIG #44

Direction only (do not start): deeper campaign arcs across
projects, craft-stage ↔ quest-step cross-links, energy-aware
routing from the BIG #42 store, an evening digest mirroring
the morning. Keep every power behind the existing gates;
INVENTory stays read-only.
