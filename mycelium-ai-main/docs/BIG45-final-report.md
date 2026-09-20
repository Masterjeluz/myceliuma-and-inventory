# BIG #45 — eindrapport

## 1. Status

DONE — built, tested, smoked, screenshotted, documented,
committed, pushed. BIG #46 not started.

## 2. Commit SHA

`BIG #45 - finish living ecosystem connections` (SHA verified
against remote HEAD after push; see git log).

## 3. Files changed

New:
- `coordinator/app/connections.py` — read-only aggregation:
  `entity_connections()`, `project_network()`,
  `campaign_ecosystem()`, `connection_detail()`,
  `possible_connections()` + collectors
- `tests/test_big45_connections.py` — 16 tests (unified
  connections, network, ecosystem, detail, possible,
  world/guide/mobile/morning/presence, refusals)
- `scripts/b45_smoke.py` — full chain on tmp DBs (43
  checks, fresh DBs each run)
- `scripts/b45_shots.py` — seed data for screenshots
  (+ `shots_ids.json` for detail URLs)
- `scripts/b45_screenshots.py` — server + Playwright capture
  (desktop 1440 + mobile 390)
- `docs/r45-shots/` (8 PNGs)
- `docs/BIG45-final-report.md` (this file)

Extended:
- `coordinator/app/main.py` — `GET /api/v1/connections*`
  (entity, network, detail, campaign, possible),
  `/connections` detail page, `_world_connections_html`
  (focused groups + unfocused project clusters) wired into
  `world_page`, morning `connections` section builder
- `coordinator/app/guide.py` — possible-connection card
  (WHY PROPOSED / gate / blocked_by / unlocks / evidence)
  + research-readiness node card
- `coordinator/app/mobile.py` — `connected_panel()`
  (CONNECTED/WAITING/DISCOVERED) + dashboard key
- `coordinator/app/presence.py` — additive
  `campaign_blocked` attention type (band needs, score 88)
- `coordinator/app/reports.py` — `connections` morning key
  (additive, "Ecosystem connections")
- `coordinator/app/ui.py` — `conn-cluster` CSS,
  `data-proposed` background signal + JS (same loop,
  reduced-motion safe)
- `docs/NEXT-AI-CONTEXT.md`, `docs/ROADMAP-V2.md`,
  `README.md`

NOT in this commit (left untouched on purpose):
- `Mycelium/agent/agent_ui.py` — pre-existing local
  modification, not ours
- `scripts/b38_screenshots.py` — untracked BIG #38 leftover,
  not staged
- `inventory/` — zero changes

## 4. What connections now exist

One unified read-only view over the existing relationship
systems — no parallel graph, no second source of truth:

- `GET /api/v1/connections?entity_id=` — symbiosis edges +
  open proposals + finance/energy/hardware/quest/campaign/
  research/node associations for one entity. Every entry:
  source/target ids + kinds, closed predicate, state,
  origin store, href, evidence, detail.
- `GET /api/v1/connections/network?projects=` — per-project
  clusters (max 6) + cross-links where projects share the
  SAME record (never word similarity).
- `GET /api/v1/connections/campaign/{id}` — a campaign's
  ecosystem: quest chain + referenced records grouped by
  domain (PROJECT/ITEM/MACHINE/ENERGY/FINANCE/…).
- `GET /api/v1/connections/detail?a=&b=` — one relationship
  in Guide vocabulary: WHAT / WHY / SOURCE / STATUS /
  EVIDENCE / NEXT. Rendered by `/connections`.
- `GET /api/v1/connections/possible` — POSSIBLE discovery
  (open proposals, craft gaps, unlinked quest steps) with
  the gate href each time. Discovery, never relationship.

## 5. Data sources used

Symbiosis edges + proposals (`symbiosis.py`), finance
records (`finance.py`, ids/kinds/status only — amounts never
leave the finance page), energy records (`energy.py`,
values as recorded or UNKNOWN), hardware links
(`hardware_links.py`, PROPOSED/VERIFIED only, REVOKED never
appears), quest steps (`quests.py`, `note` steps excluded),
campaign chains (`campaigns.py`), research runs/dossiers
(`research_engine.py`, findings not facts), node registry +
claimed tasks (`main.list_nodes`, WORKING only after a real
pull/claim lease — delegation alone pins, never works).

## 6. Validation (finished during this BIG)

- Known `xxx_` prefixes pass; empty downstream means
  absent (`proj_nowhere` → 200 empty, correct).
- Bare names must exist in a registry: a registered node
  (`nodes` table) or a device_ref named by a live hardware
  link. Syntax alone never suffices: `ghost-xyz` → 422.
- Two interrupted-session failures fixed without touching
  test intent: `_check_entity` registry check (nodes +
  device_refs) and device-side hardware lookup (the store
  has no device filter, so live links are scanned).
- One smoke gap fixed honestly: the smoke asserted WORKING
  right after delegate, but delegation only pins (queued);
  the smoke now claims via the real pull endpoint first —
  WORKING reflects a lease-bound assignment.

## 7. Read-only / security boundaries

GET-only routes (POST 405). No approval, no YES gate, no
execution, no task claim, no lease, no write path through
connections. Predicates closed (`SYMBIOSIS_PREDICATES` or
"related" display mapping, never stored). Finance amounts
never leak (asserted). Fake/traversal/wildcard ids → 422;
fake campaign/quest refresh/delete → 404/422; secret mesh
payloads → 422; prompt-injected predicates refuse at
candidate creation. REVOKED links invisible. No test
weakened, no gate weakened, INVENTory untouched.

## 8. Surfaces

/world shows Ecosystem connections (focused entity:
grouped connections with Why-links; unfocused: project
clusters + shared records). /guide explains the first open
proposal (PROPOSED because unreviewed, gate of its kind) and
which node can help. /mobile dashboard gains `connected`.
/morning gains Ecosystem connections only when real data
exists. Presence gains `campaign_blocked`. Background gains
`data-proposed` (open proposals pulse like seedlings, same
rAF loop, reduced-motion safe).

## 9. Tests

Per §test discipline: 16 targeted green during dev (14
passing at resume, 2 validation failures fixed, then the
device-side + claim findings fixed with no test edits),
touched-module regression 169 green (big44/43/42/41/40,
big36/39, worldgraph/proxy), smoke 43 green. Full Mycelium
suite ONCE at finalization (bounded batches). INVENTory
ONCE at finalization.

Full Mycelium suite: **1446 passed, 0 failed** across all
114 test files in bounded batches (218 + 238 + 198 + 209 +
195 + 79 + 16 + 67 + 226; single run exceeds the 10-min
tool timeout). Pre-existing Windows camera-enumeration
access-violation noise appears in the log (cameras.py,
untouched); every affected test still passes and every
batch completes.

INVENTory suite: **179 passed + 1 pre-existing failure**
(`test_milestone_3_8.py::test_real_inventory_db_untouched`
byte-size; environmental, unchanged, test untouched).

## 10. Smoke

`scripts/b45_smoke.py` on tmp DBs: **43/43 OK** — nodes →
link → finance/energy → quest/campaign → seedling →
project→X per domain → research run → delegate → claim →
node WORKING (no ownership) → network → machine device
side → detail vocabulary + page → campaign ecosystem →
world/guide/mobile/morning/presence → 10 refusal probes.

## 11. Screenshots

`docs/r45-shots/` (Edge headless, real seed data, all
visually inspected): connections-detail (WHAT/WHY/SOURCE/
STATUS/EVIDENCE/NEXT), world-focused (grouped connections
+ symbiosis seedling + objects + energy + attention),
world-network (proj_hydro/proj_solar clusters), world
mobile 390 (clean stack), mobile 390 (Connected
ecosystem), guide (Possible connection + campaign cards),
morning (Ecosystem connections), campaigns (trail chain).

## 12. REAL / TEST / SIMULATED / UNAVAILABLE

| Aspect | Label |
|--------|-------|
| Connections/network/ecosystem/detail | REAL derived state |
| Possible connections | Discovery, not relations |
| Node WORKING | REAL lease-bound assignment |
| Background proposed pulse | Ambient, not data |
| Finance amounts in connections | NEVER (scoped page only) |
| Printer transport | UNAVAILABLE (unchanged) |
| Fab execution | SIMULATED (unchanged) |
| WEB_PUSH | UNAVAILABLE (unchanged) |
| Energy-aware routing | FUTURE (not implemented) |

## 13. Limitations

- Network cross-links need projects sharing the same
  record; merely related projects cluster without
  cross-links (honest, not missing).
- Device-side endpoints exist only for device_refs named
  by a live hardware link; free-form energy device names
  without links still refuse.
- Campaign/network/possible views are JSON APIs except
  the detail page; world/guide/mobile/morning render
  their summaries.
- No campaign arcs across projects yet; no evening
  digest (BIG #46 direction, not designed).

## 14. What Jelles can use tomorrow

1. Open `/world?entity_id=proj_…` — every relation around
   a project, grouped, each with Why/Open links
2. Open `/connections?a=…&b=…` — one relationship
   explained (source, status, evidence, next step)
3. Open `/world` unfocused — project clusters + shared
   records across the workshop
4. Read the guide's 🔗 card — why a link is only
   PROPOSED and which gate verifies it
5. Phone shows Connected/WAITING/DISCOVERED counts
6. Re-prove with `b45_smoke.py` (43 checks)

## 15. Recommended BIG #46

Not started, not designed. Possible directions only:
evening digest mirroring the morning, campaign arcs
across projects, craft↔quest deep links, energy-aware
routing from the BIG #42 store.
