# BIG #33 — Living World: final report

## 1. Baseline

`8a2467b` (BIG #32 report SHA record) on `main`. Mycelium 1162
tests green; INVENTory 179 + 1 pre-existing
(`test_real_inventory_db_untouched`, byte-size pin on the
gitignored local DB). User processes left running throughout:
INVENTory `:8080`, coordinator `:8000`.

## 2. What BIG #33 set out to do

Two sources: the user's "THE LIVING WORLD" brief (world +
ecosystem + systems + guide + missions; symbiosis; craft tree;
living animated world; guide; quest presentation; mobile input
surface; camera/3D/node UX; node-mesh foundation; overnight
architecture; notifications; agenda; dev notify utility) and
`ROADMAP-V2.md` (BIG #33 = research network: extract executor
review, capability matrix, queue fan-out). Archaeology (Fase 0)
showed most substrate already existed; BIG #33 therefore adds
the missing first-class layers and the living presentation on
top, without rebuilding anything.

## 3. New modules (all read-only, no new stores, no new gates)

- `coordinator/app/symbiosis.py` — first-class symbiosis:
  SUPPORTED/VERIFIED projected from real INVENTory edges
  (provenance `human_verified`), PROPOSED from open
  `connection`-type knowledge candidates. Strict entity-id
  validation (known `xxx_` prefixes). `GET /api/v1/symbiosis`,
  `/symbiosis` page.
- `coordinator/app/craft.py` — Craft Tree over 12 stages
  (idea → … → new project) from the real neighborhood graph
  (inventory + missions/nodes/research/observations/printers/
  memory/candidates/conversations overlays). Every node links
  to its record; gaps are missing links with real next
  actions, never fake nodes. `GET /api/v1/craft`, `/craft`
  page with seeds + growth bar.
- `coordinator/app/guide.py` — Guide reads live state on
  every call and returns WHAT/WHY/NEXT items: approvals,
  candidates, conversation missed items, research open
  questions, camera inbox, waiting fabrications, quiet nodes,
  mission-less projects, idle missions. `GET /api/v1/guide`,
  `/guide` page + home/mobile strips.
- `coordinator/app/nodemesh.py` — node → coordinator →
  node delegation contracts: closed task-kind allow-list, no
  wildcards, no shell, registered-nodes only, advertised-
  capability check, ≤4KB JSON payload, secret-name refuse,
  ≤120 capability chars. Validation only; dispatch reuses the
  normal task queue. `GET /api/v1/mesh/topology`,
  `POST /api/v1/mesh/validate`, mesh panel on `/nodes`.
- `scripts/mycelium-notify.py` — stdlib dev notifier:
  `status` progress line, `need` loud approval signal (BEL +
  OSC 9 Windows Terminal toast + OSC 99 WezTerm), `done`
  completion signal, ASCII fallback on cp1252 consoles.
- `scripts/b33_seed_shots.py` — tmp-DB screenshot seeder
  (nodes, candidates, connection proposal, conversation +
  analysis, mission, Insta360 registration, research run).
- `tests/test_big33_living_world.py` — 11 tests.

## 4. UI changes (`ui.py` + `main.py`, additive only)

- Nav: Craft Tree, Guide, Symbiosis under WORLD.
- Living layer: drifting-spore canvas + gradient, all
  `prefers-reduced-motion`-safe; pixel-edge buttons; state
  language chips (REAL/TEST/SIMULATED/UNAVAILABLE/WAITING/
  ACTIVE/BLOCKED/VERIFIED/CANDIDATE/OBSERVATION); growth bar
  (seed→harvest); quest trail (✓/●/○, status text kept);
  symbiosis chips; guide cards; honest empty states.
- `/` home: guide strip, seed chips with craft/symbiosis
  links, mission cards, nodes/status/notifications rail.
- `/world`: living background + links to craft/symbiosis/guide.
- `/missions`: quest steps per mission card; detail page
  unchanged (same plan, same YES gates).
- `/mobile`: quick-action grid (8 emoji actions to existing
  routes), PROCESSING/RESULT explanation, Needs-you strip.
  Contract strings kept: INPUT, RESULT, Quick actions,
  "Hoe gebruik ik Mycelium".
- `/nodes`: mesh panel (shared-capability edges, delegable
  kinds, topology JSON link).
- `/cameras` → "Camera Lab" framing; `/workshop/3d` craft
  pointer; `/conversations` → "AI Conversation Archive"
  framing; `/research` network paragraph (heading + read-only
  strings kept); `/agenda` ecosystem paragraph; `/activity`
  breathing framing + living background.
- Preserved test-contract strings verified: "Living
  Workshop", "wstage", "UNAVAILABLE", "WHAT EXISTS",
  "VERIFY", "Import a conversation", "WHAT IT CAN DO",
  "Research workshop", "read-only", "Transformatie-voorstel".

## 5. Reused, not rebuilt

Missions/approvals, knowledge lifecycle, worldgraph +
overlays, ecosystem/entity_context, living_state, research
engine + queue, conversation bridge + discoveries, context
packets, cameras/ingest, fabrication, nodes/routing/leases,
notifications/events, agenda importer, mobile flows. No gate
removed, no provenance rule relaxed, no INVENTory change.

## 6. Screenshots

`docs/r33-shots/` — 14 PNGs (Edge headless, tmp DBs, real
seed records): home, world, craft, guide, symbiosis,
missions, mobile 1440+390, nodes, cameras, research,
conversations, activity, knowledge. Reviewed: guide shows
real counts (2 candidates, 2 missed items, 5 inbox files,
quiet seed-pi); missions show honest BLOCKED with
`TransportUnavailableError: wikipedia HTTP 403`; home shows
real INVENTory seeds + mission + nodes rail.

## 7. Security

New code: no subprocess/shell/eval/exec; closed allow-lists
(task kinds, capability prefixes, candidate states);
entity-id regex + prefix allow-list; mesh refuses wildcards,
unknown nodes, secret-bearing and oversize payloads;
symbiosis/craft/guide read-only; no human_verified change;
HTML escaped at render; prompt content stays data. Tested:
fake IDs, wildcard/shell/evil capabilities, unknown node,
secret payload, oversize capability, invalid delegation kind.

## 8. Performance

Guide/symbiosis/craft/mesh all bounded (caps 12–60, early
exits); one living canvas (26 spores, rAF, display:none on
reduced-motion); no new polling, no new dependencies, no N+1
(single store reads per section).

## 9. Tests before/after

Before: 1162 collected. After: **1173 collected (1162 + 11
new), all green** — full suite batch-verified across all 102
files in 10 bounded runs, 0 failures (2 heading regressions
found during development: "Research workshop" and
"read-only" strings restored, then green). New: 11
(`test_big33_living_world.py`). INVENTory: 179 passed + the
same 1 pre-existing failure (untouched; code not modified).
Final targeted run: 13 passed (big33 + research/big30 page
contracts).

## 10. Smoke tests (real localhost HTTP, tmp DBs)

Seed → register 2 nodes → candidates → connection proposal →
import + analyze → chat → mission (from-template) →
Insta360 register → research queue: all 201/200. Live
`:8001` server: health 200, 14 screenshots rendered. Seeded
mission blocked honestly on Wikipedia 403 (external
transport restriction, NOT a code bug — surfaced as
`TransportUnavailableError`, mission BLOCKED, no fake
findings).

## 11. REAL/TEST/SIMULATED/UNAVAILABLE matrix

REAL: symbiosis/craft/guide/mesh-validation over live
stores, quest display, mobile quick actions, notify
sequences, camera registration, research queue, mission
lifecycle. TEST: procedural meshes (unchanged). SIMULATED:
printers (unchanged). UNAVAILABLE: Insta360 live transport,
printer transports, web push, STT engine, Wikipedia from
this network (403 — transport-level, honest BLOCKED).

## 12. Remaining limitations

Graph fan-out costs seconds on demand; full suite needs
batching (>10 min single run); camera-ctypes Windows
access-violation noise is pre-existing (non-fatal, tests
pass); seed chips show raw IDs when INVENTory records carry
no name/title (honest fallback); overnight stays
read-only queue + morning digest (no new autonomy);
remote execution beyond task-queue routing is FUTURE.

## 13. Commit

`BIG #33 - build the living world` (files listed in §14).
INVENTory untouched. Pre-existing
`Mycelium/agent/agent_ui.py` modification left untouched
and uncommitted (not ours).

## 14. Files changed

New: `coordinator/app/symbiosis.py`,
`coordinator/app/craft.py`, `coordinator/app/guide.py`,
`coordinator/app/nodemesh.py`,
`tests/test_big33_living_world.py`,
`scripts/mycelium-notify.py`, `scripts/b33_seed_shots.py`,
`docs/r33-shots/` (14 PNGs), `docs/BIG33-final-report.md`
(this file). Extended: `coordinator/app/main.py` (5 APIs +
3 pages + home/world/missions/mobile/nodes/camera/3d/
conversations/research/agenda/activity passes),
`coordinator/app/ui.py` (nav + living CSS + 7 helpers),
`docs/NEXT-AI-CONTEXT.md`, `docs/ROADMAP-V2.md`,
`README.md` touched only if needed (left as-is).
