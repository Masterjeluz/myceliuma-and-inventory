# BIG #32 — Living Knowledge + Research Network: final report

## 1. Baseline

`98a3631` (BIG #31), branch `main`. Mycelium 1140 tests green;
INVENTory 179 + 1 pre-existing (`test_real_inventory_db_untouched`,
byte-size pin on the gitignored local DB).

## 2. Architecture reused

Memory (`new_memory/save_memory` + revision fencing,
`verify_memory`, `retrieve_memories`, truth tiers), research
(`new_source/save_source/extract_source`, runs/dossiers/queue),
task queue (queued → capability-matched claim → lease → complete),
`route_task` dry-run, event bus + notifications, conversation
bridge (findings/analysis/missed), camera ingest chain, writes
(propose → exact YES → execute → verify), living state, context
packets, world graph + overlays. Nothing rebuilt, no gate
removed.

## 3. Files changed

New: `coordinator/app/knowledge.py`,
`tests/test_big32_knowledge.py` (22 tests),
`docs/knowledge-lifecycle.md`, `docs/research-routing.md`,
`docs/ROADMAP-V2.md`, `docs/BIG32-final-report.md` (this file),
`docs/r32-shots/` (7 PNG's). Extended: `main.py` (candidates API,
`/knowledge`, graph filters + overlays, eligible/routing, queue
seed_urls/route, ingest hook, finding/observation/question → candidate,
mobile remember/queue/missed, dossier buttons, camera detail buttons,
3D relations, eligible endpoint), `worldgraph.py` (overlays +
`filter_graph`), `living_state.py` (24h counts + candidates),
`context_packet.py` (knowledge section), `ecosystem.py` (roles,
clickable notification links), `conversation_bridge.py` (compare,
markdown), `vision_ingest.py` (`FileIngestAdapter`, inbox),
`node_client/main.py` (`research.fetch_url`), `events.py` (+8
types), `notify_center.py` (+9 types), `ui.py` (Knowledge nav,
growth/glyph helpers, filament/grain CSS), docs (9 updated),
`README.md`, `node_client/bootstrap.py` (sys.path fix).

## 4. Knowledge lifecycle

OBSERVATION → CANDIDATE → SUPPORTED (2 distinct supporters) →
PROMOTED MEMORY (or REJECTED). Intake from findings, research
questions, observations, manual/mobile. `/knowledge` cards show
title/summary/type/provenance/sources/evidence/counter-evidence/
entities/origin/supporters/truth/next action with Support/
Promote/Reject/Keep. No invented confidence — support counts.

## 5. Candidate promotion

Default truth per type; fact tiers need a human `verified_by`
through `verify_memory()`; verified/user_fact overlap refuses
with conflict IDs; provenance/sources/contradictions survive in
`data.origin` + `derived_from`; idempotent (`deduped`),
fingerprint dedupe, revision fencing; `candidate.promoted`
event. AI recommends, human decides.

## 6. Linux executor

`research.fetch_url` REAL in `node_client`: coordinator-validated
URL in, bounded text out (no redirects/credentials/binaries,
64KB, 20s, defense-in-depth host check). Claim loop enforces
`research.fetch`. Live-tested via mock transport + API-level
claim/complete.

## 7. Node routing

`eligible_nodes_for()` + `GET /api/v1/eligible-nodes` +
`/nodes?check_cap=` panel (honest WAITING_FOR_AGENT). Queue
`seed_urls` (validated ≤3) + `route`; node-first creates fetch
tasks; completion hook ingests `web` SourceRecords onto the run
(dedupe, extract, `research.fetched` event). Multi-node ready:
capability-based, no names. `extract/analyze/compare` FUTURE.

## 8. Graph filters

Truth (all/verified/memory/candidate/observation), source, kind,
since + memory/candidate/conversation overlays (health refused
at builders). Unfiltered output byte-identical to before
(regression fixed + tested). New `/api/v1/graph` flags; `/world`
Layers & truth panel.

## 9. Context changes

Packet v2 `knowledge`: observations/candidates/supported/
`memories_by_tier`/contradictions/`research_performed`,
rendered in Markdown. Health excluded everywhere (tested).

## 10. Mobile changes

Remember this → candidate; Look into this → research queue;
What did we miss → discoveries; Observe & add + copy-context
kept; inline YES approvals kept.

## 11. Camera/3D preparation

Observation "Review as candidate" buttons (detail + API);
Insta360 requirements stay documented + UNAVAILABLE transport.
`/3d?entity_id=` shows CONNECTED TO relations; links still via
`/writes` + YES. No printer claims.

## 12. UI changes

Knowledge nav + page, mission growth states + glyphs, filament/
grain CSS (reduced-motion safe), living-state 24h reasons,
clickable notifications, useful empty states, world filter form,
nodes routing panel, dossier/conversation candidate buttons.

## 13. Screenshots

`docs/r32-shots/` (headless Chrome, tmp DB seed: node, camera,
import + analysis, finding→candidate→support→promoted memory,
second candidate, node-first queue run, OVERNIGHT): knowledge,
world-filters, nodes-routing (eligible + WAITING states),
mobile-1440/390, morning (OVERNIGHT), conversations. Real data
throughout; stale/empty states shown honestly.

## 14. Security

New code scanned: no subprocess/shell/eval/exec; ingest
traversal/missing/oversize refuse; closed predicates; mode/
priority/route allow-lists; URL validation (coordinator full +
node depth); capability subset enforced by claim loop; no
human_verified escalation (tested); health isolation (tested);
prompt-injection content stays escaped data; revision fencing on
candidates + memories.

## 15. Performance

All listings capped (20–200); graph caps preserved + early exit;
compose/search bounded; packet sections capped; no N+1 (single
queries per store); fetch 64KB/20s; queue ≤3 URLs/run.

## 16. Tests before/after

Before: 1140 collected. After: **1162 collected, all green**
(batch-verified, 0 failures; 1 pre-existing worldgraph
regression found and fixed during development). New: 22
(`test_big32_knowledge.py`). INVENTory: 179 passed + the same 1
pre-existing failure (untouched, see §21).

## 17. Real smoke tests

Live coordinator on tmp DBs: register → heartbeat → eligible;
import → analyze → finding → candidate → support ×2 →
promote → memory; queue node-first → task → claim → complete →
run source + event; file ingest → observation → candidate;
mode DAY↔OVERNIGHT; packet v2 markdown. Screenshots prove it.

## 18. REAL/TEST/SIMULATED/UNAVAILABLE matrix

REAL: lifecycle/promotion/conflicts, graph filters + overlays,
node fetch executor, routing, queue node-first, ingest hook,
packet knowledge, mobile remember/queue, writes inbox flows,
file ingest. TEST: synthetic adapters (labeled). SIMULATED:
printers (unchanged). UNAVAILABLE: Insta360 direct transport,
printer transports, web push, Garmin OAuth, STT engine, node
extract/analyze/compare.

## 19. Remaining limitations

Compose/search fan-out costs seconds (on-demand); full suite
needs batching (>10 min single run); camera-ctypes Windows noise
pre-existing; node network fetches depend on node egress;
overnight digest shows open questions only (no auto-write).

## 20. Future BIG roadmap

`docs/ROADMAP-V2.md`: #33 research network (extract executor),
#34 camera ecosystem, #35 3D workshop, #36 mobile, #37
conversation intelligence, #38 living automation, #39 presence,
#40 Mycelium V2. Directional — never premature.

## 21. Commit SHA

(BIG #32 commit, see `git log`.) INVENTory untouched: 179
passed, 1 pre-existing `test_real_inventory_db_untouched`
failure identical before/after (local DB size drift, documented
as brittle by design).

## 22. Push result

Pushed to `origin/main`, remote HEAD verified. Pre-existing
`Mycelium/agent/agent_ui.py` modification left untouched.

## 23. Final git status

Clean except the pre-existing agent UI modification (not ours).
