# BIG #42 — eindrapport

## 1. What existed

BIG #41 V2 foundation, reused untouched: mesh preview/delegate
through the task queue (pull-only claims, rollback), Routing
2.0 verdicts + explainer, hardware reality with trust levels
(VERIFIED reserved, unreachable by derivation), ecosystem
overview (8 answers), craft states, closed symbiosis, guide
unlocks, node-tempo background. `inventory/` zero changes.

## 2. Human verification

`coordinator/app/hardware_links.py` (new): PROPOSED →
VERIFIED → REVOKED store in the chat DB (additive table).
Propose (`POST /api/v1/hardware/links`) always starts
PROPOSED. Verify (`POST .../verify`) needs the operator key —
node credentials are never accepted, so devices cannot
self-verify; REVOKED links refuse re-verification (422).
Audit events `hardware.linked/verified/revoked` name human,
node, device. `/nodes/{id}/reality` overlays VERIFIED only
for exact node+device matches; `hardware_trust()` still can
never return VERIFIED. `/hardware` page lists all three
states.

## 3. Finance

`coordinator/app/finance.py` (new): income/expense/budget,
DRAFT/CONFIRMED/ARCHIVED, amounts as minor units + currency.
Omitted amounts stay NULL → UNKNOWN (never zero). No fake
records — rows exist only via the explicit API. Amounts live
only in the store + `/finance` + project-scoped packets;
generic packets carry counts (`SCOPED` marker otherwise).

## 4. Energy

`coordinator/app/energy.py` (new): solar/battery/grid/machine/
other × production/consumption/storage/state. NULL values
stay UNKNOWN. `GET /api/v1/energy/state` derives current
state from latest state-kind rows. Nothing invented; routing
weights unchanged (data exposed honestly for later use).

## 5. Symbiosis

Prefixes `fin_`, `enr_`, `hv_`, `qst_` + closed predicates
`funds`, `funded_by`, `powers`, `powered_by`, `allocated_to`.
Proposal input still strict-refuses unknown verbs; display
still maps to "related". Never merges entities. Enables
project↔finance, project↔energy, energy↔machine/node,
finance↔mission, project↔project, quest↔mission pairs.

## 6. Mission templates

`idea_to_verification` (9 steps: readout→research→analysis→
proposal→readout→analysis→fabricate→camera_observe→analysis)
and `project_finance_energy` (5 steps: project→finance→
energy→research→proposal). Every step kind is an existing
`VALID_STEP_KINDS` member; instantiation runs the same
mission gates. No generic workflow executor; catalogue is
closed at 8.

## 7. Quest trails

`coordinator/app/quests.py` (new): defs hold refs only; every
read derives ✓/●/!/○ from missions, tasks, finance, energy,
hardware links (each step links to its record). Progress is
real done/total — no XP. Quest states READY/ACTIVE/WAITING/
BLOCKED/COMPLETED/FAILED. `/quests` page, JSON API, refresh
audits via `quest.updated`.

## 8. Remote mesh

`POST /api/v1/workflows/preview|dispatch`: max 6 pinned
steps (research on A, camera on B, compute on C) through the
existing task queue — validate → auth → eligibility precheck
→ create → assign per step, coordinator authoritative, nodes
pull-based. Failed step stops the workflow; queued steps keep
their lease lifecycle, never silently dropped. Same closed
contracts as `/mesh/delegate`.

## 9. Hardware-aware readiness

`quests.step_readiness()`: READY names the eligible node
(shared `research_readiness`), WAITING when the camera node
is offline / no researcher eligible, BLOCKED on failed
records, UNAVAILABLE for printer transport. Offline hardware
is never pretended available.

## 10. Guide

New kinds hardware/finance/energy/quest with AFTERWARDS
mechanics text. Live items: unverified advertised GPU/camera
→ /hardware; finance-without-energy → /energy; energy/finance
symbiosis waiting → /symbiosis; research-routable node named;
blocked quests → /quests. Every item keeps WHAT/WHY/NEXT.

## 11. World

State strip gains progressive disclosure (open quests,
verified ratio, finance/energy counts — only when data
exists) + nav links to the four new pages. Animated
background untouched; reduced-motion support untouched.

## 12. Mobile

Dashboard adds quests, hardware, finance (counts only),
energy, mesh_receipts (delegated-task WHAT/WHERE/RESULT)
panels. Same gates — all YES/NO still post to existing web
routes.

## 13. Morning

New sections HARDWARE, QUESTS, ENERGY, PROJECTS, FINANCE —
populated only when real data exists (report + smoke assert
absence otherwise). `reports.py` keys added additively;
presence sections untouched.

## 14. Context packets

packet-v2 gains an `ecosystem` block (quests, symbioses,
hardware trust, energy, finance) — no packet-v3. Finance
amounts enter only when packet `project_id` matches the
record's `project_ref`; generic packets get counts +
`SCOPED`. Markdown render includes the block.

## 15. Security

- Fake link verify → 404; wrong/empty operator key → 403,
  link stays PROPOSED; node credential never verifies.
- Revoked links refuse re-verify (422, asserted).
- Fake finance kind / energy source / predicate → 422.
- Workflow: wrong credential 403; wildcard/shell/unknown
  kind/secret payload/missing target → 422; traversal target
  → 404/422/409; stale target → 409 with nothing queued.
- Claim/lease/attempt gates untouched; delegation creates no
  approvals; replay creates distinct tasks; no shell surface;
  prompt-injected reasons stay audit text.
- Tests updated, none weakened: `test_mission_templates.py`
  count pins moved 6→8 because this BIG explicitly adds two
  templates — the no-input-steps safety test iterates ALL
  templates, so the new ones are covered without modification.

## 16. Tests

New: 22 tests in `tests/test_big42_ecosystem.py`, all green.
Touched-module regression (big41, presence, mobile, living
world, missions, templates, loop, routing): green after the
count-pin update above.
Full Mycelium suite, bounded batches: **1354 passed**
(154 + 376 + 420 + 404 across 107 files; missions/loop/
routing/templates green in the touched run — every file
green at least once). Camera device enumeration logs
pre-existing Windows access-violation noise; unrelated,
untouched, suite completes.
INVENTory suite: **179 passed + 1 pre-existing failure**
(`test_real_inventory_db_untouched` byte-size; environmental,
unchanged, test untouched). `inventory/` has zero changes.

## 17. Smoke

`scripts/b42_smoke.py` on tmp DBs (fresh DBs each run):
**49/49 OK** — propose→PROPOSED→refusals→verify→reality
VERIFIED→finance/energy→templates→quest 0/2→1/2→preview
creates nothing→dispatch 2 steps→mobile/overview/guide/
morning/packet scoping→7 pages→8 refusal probes→revoke
sticks.

## 18. Screenshots

`docs/r42-shots/` (Edge headless, real seed data, reviewed):
world (strip with quest/trust/money/energy), hardware
(nodes-reality), quest (3/4 real progress), symbiosis,
guide, mobile, morning.

## 19. REAL / TEST / SIMULATED / UNAVAILABLE

| Aspect | Label |
|--------|-------|
| Hardware links + VERIFIED | REAL (operator-gated) |
| Finance/energy records | REAL (explicit only) |
| Quest progress | REAL (derived, no XP) |
| Workflow dispatch | REAL queue mechanics |
| Printer transport | UNAVAILABLE (unchanged) |
| Fab execution | SIMULATED (unchanged) |
| WEB_PUSH | UNAVAILABLE (unchanged) |
| Energy-aware routing | FUTURE (data ready) |

## 20. Limitations

- Verify/revoke need the operator key in env; no web-form
  flow yet (API + pages link to it).
- Workflow steps dispatch in order but run async via claims;
  no cross-step result piping (by design — no data flow
  between nodes).
- Energy influences nothing yet beyond honest display.
- Quest `entity` steps link out but don't derive completion
  from INVENTory (link only, never invented).

## 21. Git commit + push

`BIG #42 - ecosystem hardening + first V2 workflows` (SHA
verified against remote HEAD after push; see git log).

NOT in this commit (left untouched on purpose):
- `Mycelium/agent/agent_ui.py` — pre-existing local
  modification, not ours
- `scripts/b38_screenshots.py` — untracked BIG #38 leftover,
  not staged
- `inventory/` — zero changes

## 22. What Jelles can actually use tomorrow

1. Open `/hardware` — propose a link for the GPU/camera,
   verify with the operator key, watch `/nodes/{id}/reality`
   flip to VERIFIED
2. Open `/finance` + `/energy` — record the solar budget and
   production; UNKNOWN stays honest where unmeasured
3. Open `/quests` — define "Build Solar Upgrade" over the
   real records; watch done/total move when work completes
4. Dispatch research→camera→compute across nodes with
   `/api/v1/workflows/preview` first, then dispatch
5. Read the guide — unverified hardware, missing energy,
   blocked quests, routable research, each with NEXT
6. Check `/morning` — HARDWARE/QUESTS/ENERGY/PROJECTS/
   FINANCE appear only when they matter
7. Re-prove anything with `b42_smoke.py` (49 checks)

## 23. Recommended BIG #43

Game layer on hardened ground: quests become campaigns with
arcs over the trail store, symbiosis becomes visible
progression (counts that mean something), presence becomes
stakes (what happens if nobody acts). World and morning stay
honest — progression names real records, never XP. Keep
every new power behind the existing gates; INVENTory stays
read-only as always.
