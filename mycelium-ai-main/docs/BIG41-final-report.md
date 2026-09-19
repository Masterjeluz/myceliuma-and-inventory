# BIG #41 — eindrapport

## 1. Status

DONE — built, tested, smoked, screenshotted, documented,
committed, pushed.

## 2. Commit SHA

`BIG #41 - build Mycelium V2 foundation` (SHA verified
against remote HEAD after push; see git log).

## 3. Files changed

New:
- `coordinator/app/v2_ecosystem.md` → `docs/v2-ecosystem.md`
  (architecture: mesh, routing, hardware, world, craft,
  symbiosis, game layer, labels, limits)
- `tests/test_big41_v2.py` — 24 tests (routing verdicts +
  workload + explainer, mesh validation/preview/delegate,
  trust levels, reality endpoint, symbiosis, craft states,
  overview, world strip, guide unlocks, morning, background,
  audit trail, refusals)
- `scripts/b41_smoke.py` — full chain on tmp DBs
  (54 checks, fresh DBs each run)
- `scripts/b41_shots.py` — seed data for screenshots
- `scripts/b41_screenshots.py` — server + Playwright capture
- `docs/r41-shots/` (7 PNGs)
- `docs/BIG41-final-report.md` (this file)

Extended:
- `coordinator/app/routing.py` — rejection verdicts
  (waiting/blocked/unavailable), `prefer_idle` workload
  preference, `explain_decision` (WHY ELIGIBLE/WAITING/
  BLOCKED/NOT AVAILABLE)
- `coordinator/app/nodemesh.py` — targeted delegation
  (exact-capability pin, timeout 5–300s, clipped reason)
- `coordinator/app/main.py` — `/mesh/preview`,
  `/mesh/delegate` (auth → validate → precheck → create →
  assign → rollback), route `why` block, `current_task`
  projection, `/nodes/{id}/reality`, `/ecosystem/overview`,
  world state strip, craft states in API + page, mobile
  current-task lines
- `coordinator/app/schemas.py` — `MeshDelegateBody`,
  `MeshPreviewBody` (reason ≤ 2000, clipped to 200 by engine)
- `coordinator/app/events.py` — additive `task.delegated`
  audit type
- `coordinator/app/worldgraph.py` — per-node
  `attention_needs/offline` (boundary-matched)
- `coordinator/app/ecosystem.py` — `ecosystem_overview`
  (8 answers, named sources, explicit degradation)
- `coordinator/app/craft.py` — `stage_states`
  (✓/●/○/! with evidence)
- `coordinator/app/symbiosis.py` — V2 prefixes (`node_`,
  `node-`, `res_`, `dos_`, `auto_`, `food_`, `meal_`) +
  closed `SYMBIOSIS_PREDICATES` + strict/display checks
- `coordinator/app/guide.py` — research unlock + blocked
  items via shared presence readiness (also fixed a
  wolf-crying inline check that lacked fresh/auth flags)
- `coordinator/app/presence.py` — craft gaps in morning
  discoveries
- `coordinator/app/mobile.py` — `current_task` in nodes
  panel
- `coordinator/app/ui.py` — node-tempo background data
  attribute (capped, ambient, reduced-motion safe)
- `scripts/mycelium-notify.py` — `blocked`, waiting guidance
  (→ /mobile + mission), `checklist` (✓/●/○/`?`)
- `docs/NEXT-AI-CONTEXT.md`
- `docs/ROADMAP-V2.md`
- `README.md` (docs list + test count touch-up)

NOT in this commit (left untouched on purpose):
- `Mycelium/agent/agent_ui.py` — pre-existing local
  modification, not ours
- `scripts/b38_screenshots.py` — untracked BIG #38 leftover,
  not staged
- `inventory/` — zero changes; its 1 pre-existing failure is
  unchanged (see §Tests)

## 4. What existed (BIG #1–40, reused untouched)

Task queue with leases (300s), 3 attempts, capability-gated
claim, assign-pins, fencing; closed mesh validation
(prefixes, secret scan, registry checks); telemetry-aware
routing with hard gates + preferences; node JSON with
health/hardware/compute; presence attention (12 collectors,
triage, bands, fan-out); living state; world graph overlays;
craft tree (12 stages + gaps); symbiosis PROPOSED/SUPPORTED/
VERIFIED; guide WHAT/WHY/NEXT/AFTERWARDS; 7 morning presence
sections; mobile bands + gates; IN_APP notifications
(WEB_PUSH UNAVAILABLE); drifting-spore background.

## 5. What changed (V2 glue, no rebuilds)

Everything new is a thin unification over those stores:
verdicts on existing rejections, workload projection from
the tasks table, a delegate flow through create→assign with
rollback, a reality read-model over the registry row,
trust/evidence annotations, one overview composer, state
chips on existing pages. No new stores except zero tables
(no migration in BIG #41 at all).

## 6. Ecosystem integrations

`/api/v1/ecosystem/overview` + `/world` state strip answer
EXISTS/CONNECTED/HAPPENING/NEEDS/NEXT/NODES-CAN-DO/BLOCKED/
GROWING with named sources and explicit degradation.
Presence, living state, mesh, symbiosis, progression feed
one model; pages link back to existing entities/missions/
events everywhere.

## 7. Remote mesh

Pinned delegation with exact-capability checks, requester
authentication (legacy consistent with claim), 5–300s
timeout recorded/enforced-by-lease, clipped reason, secret
scan, 4KB payload cap. Preview dry-runs everything.
Delegate prechecks eligibility, creates + assigns, rolls
back on assign failure (nothing drifts), emits
`task.delegated` (requester → target + reason). Target must
still pull/claim; requester can never steal another pin;
reaching a node grants it nothing. Untargeted dispatch
stays `POST /api/v1/tasks`.

## 8. Hardware reality

`current_task` on every node listing (one indexed query),
mobile panel + hardware detail line included.
`/nodes/{id}/reality`: state, health, heartbeat age,
telemetry summary, per-item trust (ADVERTISED default,
OBSERVED when connected + fresh <300s, VERIFIED reserved
for human links — asserted unreachable by derivation),
compute, energy, roles, task. Read-only.

## 9. Routing

Verdicts on every rejection; `prefer_idle` (+1 idle,
ordering-only, off by default); `explain_decision` groups
WHY ELIGIBLE/WAITING/BLOCKED/NOT AVAILABLE; route preview
returns it as `why`. Deterministic and inspectable — no
ranking beyond the existing score + node_id tie-break.
Existing reason wording preserved (`not live`).

## 10. World/game layer

Registry overlay carries attention counts (boundary-matched
ids); background tempo follows online nodes (capped,
ambient, reduced-motion killed); progression (quests with
done/total + links, 24h counts, capabilities) surfaced on
`/presence`, overview JSON, and world strip. No XP, no
fake accomplishments — QUEST/DISCOVERY/CRAFT/SYMBIOSIS/
GROWTH/UNLOCK name existing concepts.

## 11. Craft

`stage_states`: ✓ linked evidence present (never "work
finished"), ● in-flight linked work, ! failed/blocked
links, ○ empty + gap href. In `/api/v1/craft` (`states`)
and `/craft` headers. General entities, not just 3D.

## 12. Symbiosis

Prefixes for nodes, research runs/dossiers, automation
runs, foods/meals (finance/energy stores don't exist — no
prefixes invented). Closed predicate set (union of the two
existing closed sets): strict at proposal input, display
maps unknown stored verbs to "related" (edges never hidden,
meanings never invented). Never merges entities.

## 13. Guide

Unlock branch (eligible node named → queue research) and
blocked branch (failed runs/missions with exact unlock
path), sharing presence's readiness check — replacing an
inline check that cried wolf for lack of fresh/auth flags.

## 14. Mobile

Unchanged gates; nodes panel + hardware detail carry
`current_task`; mesh receipt vocabulary (WHAT/WHY/WHERE/
CAPABILITY/RISK/RESULT) matches what mobile shows before
any approval. Delegated tasks trace via `/activity` +
task detail.

## 15. Security

- Fake node/capability/hardware/task, ghost requesters,
  traversal targets: refused (404/422).
- Wrong credentials 403; disabled targets refused.
- Wildcard/shell/unknown kinds refused; secret payloads
  refused; oversized payloads refused; timeout clamped.
- Stale targets 409 with nothing queued (verified no drift).
- Prompt-injected reasons clipped to audit text; risk text
  static; no capability text reaches a shell (no shell).
- Delegation creates no approvals (counts asserted).
- Replay creates distinct tasks (no merge, no double-apply).
- Claim still enforces liveness + credential + capability
  subset + attempt cap; completion still gated by lease.
- No new execution surface; triage/attention paths untouched.

## 16. Tests

New: 24 tests in `test_big41_v2.py`, all green. Targeted
regression on touched areas (routing, mesh/world, nodes,
events): green. Full-suite discipline held: targeted only
during development.

Full Mycelium suite: **1380 passed, 0 failed** across all
110 test files in bounded batches (single run exceeds the
10-min tool timeout; per-batch evidence in the run log).

INVENTory suite: **179 passed + 1 pre-existing failure**
(`test_milestone_3_8.py::test_real_inventory_db_untouched`
asserts the real `data/inventory.db` is exactly 73728 bytes;
on disk it is 573440 bytes through real use). `inventory/`
is untouched by this BIG; failure is environmental and
unchanged. Do not touch that test.

## 17. Smoke

`scripts/b41_smoke.py` on tmp DBs (fresh DBs each run):
54/54 OK.

Chain verified: register ×2 → telemetry → explainer
verdicts → preview creates nothing → delegate pins +
audits → reality trust (OBSERVED, never VERIFIED) → target
claims, requester cannot steal → current task shown →
completion clears → overview 8/8 → craft/symbiosis/guide/
morning/pages/strip → 9 refusal probes (fake node, wrong
credential, shell, wildcard, unknown cap, secrets,
traversal, unpinned, over-lease timeout) with zero drift.

## 18. Screenshots

`docs/r41-shots/` (Edge headless, real seed data, reviewed):

1. `world-1440.png` — cockpit with state strip (waiting/
   discoveries/offline + top attention + overview link)
2. `guide-1440.png` — guide with Afterwards + unlock items
3. `nodes-1440.png` — node cards + mesh + routing check
4. `mobile-1440.png` — mobile with presence bands
5. `craft-1440.png` — craft tree navigation
6. `symbiosis-1440.png` — PROPOSED row with entities +
   Review link
7. `presence-1440.png` — attention view with bands

## 19. REAL/TEST/SIMULATED/UNAVAILABLE

| Aspect | Label |
|--------|-------|
| Mesh validation/preview/delegate queue flow | REAL mechanics, TEST-safe dry runs |
| Delegated execution | REAL task machine (lease/attempts/claim) |
| Trust levels | REAL derivation (OBSERVED), VERIFIED reserved |
| Routing verdicts/explanations | REAL (deterministic, inspectable) |
| Overview/craft states/symbiosis display | REAL (store-backed, explicit degradation) |
| Background motion | Ambient, not data |
| Printer transport | UNAVAILABLE (unchanged) |
| Fab execution | SIMULATED (unchanged, never REAL) |
| WEB_PUSH | UNAVAILABLE (unchanged) |
| Hardware claims | Node-reported until human-linked |

## 20. Limitations

- Delegation cannot make stale/offline nodes claim (409);
  freshness is enforced at assign AND claim.
- VERIFIED hardware needs a human link store (printer
  twins are the pattern).
- No finance/energy entity stores → no symbiosis pairs.
- Untargeted dispatch stays on the task queue endpoint.
- World graph shows presence as data, not animated markers.
- Single recipient, no push transport.

## 21. Git commit + push

`BIG #41 - build Mycelium V2 foundation` (SHA verified
against remote HEAD after push; see git log).

## 22. What Jelles can actually use tomorrow

1. Open `/world` — state strip + top attention + overview
   JSON link in the cockpit
2. Ask "which node should get this?" — route preview
   explains eligible/waiting/blocked/unavailable per node
3. Delegate a bounded read to a specific node — preview
   first, receipt with risk + result links after
4. Open `/nodes/{id}/reality` — heartbeat age, trust per
   device, current task
5. Follow `/craft` state chips (✓/●/○/!) with evidence
6. Link nodes, research, foods in symbiosis (closed
   predicates, never merged)
7. Read the guide's unlock items — what unblocks what, exactly
8. Run `mycelium-notify.py blocked/checklist/waiting` in
   long terminal sessions
9. Re-prove anything with `b41_smoke.py` (54 checks)

## 23. Recommended BIG #42

Ecosystem hardening + first V2 workflows: human link store
for hardware verification (unlock VERIFIED honestly),
finance/energy entity stores (complete the symbiosis map),
mission templates that chain mesh delegation end to end
(research on Node B feeding a craft chain), and quest
trails with done/total across missions + automation in one
view. Keep every new power behind the existing gates.
