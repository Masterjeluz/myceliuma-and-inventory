# BIG #40 — eindrapport

## 1. Status

DONE — built, tested, smoked, screenshotted, documented,
committed, pushed.

## 2. Commit SHA

`BIG #40 - build presence ecosystem` (SHA verified against
remote HEAD after push; see git log).

## 3. Files changed

New:
- `coordinator/app/presence.py` — attention engine
  (12 collectors, deterministic scoring, triage store,
  bands, progression, overnight digest, notify fan-out)
- `tests/test_big40_presence.py` — 31 tests (aggregation,
  priority, transitions, deeplinks, surfaces, progression,
  overnight, notifications, security)
- `scripts/b40_smoke.py` — full chain on tmp DBs
  (49 checks)
- `scripts/b40_shots.py` — seed data for screenshots
- `scripts/b40_screenshots.py` — server + Playwright capture
- `docs/r40-shots/` (7 PNGs)
- `docs/presence-ecosystem.md`
- `docs/BIG40-final-report.md` (this file)

Extended:
- `coordinator/app/main.py` — presence API
  (`/api/v1/presence`, `/seen`, `/defer`, `/notify`),
  `/web/presence/defer|seen`, `/presence` page, mobile
  presence bands, morning presence sections, offline card
  dimming
- `coordinator/app/mobile.py` — dashboard `presence` bands
  + `greeting` + `progression`
- `coordinator/app/ui.py` — `presence_card`,
  `guide_card` AFTERWARDS line, presence CSS (breathe/dim/
  bands, reduced-motion safe), topbar presence counts
- `coordinator/app/guide.py` — `after` (AFTERWARDS) on
  every guide item, kind-specific honest mechanics text
- `coordinator/app/reports.py` — 7 presence sections,
  MAX_BLOCKS 16 → 24
- `coordinator/app/schemas.py` — `PresenceTriageBody`,
  `PresenceNotifyBody`
- `coordinator/app/notify_center.py` — 4 additive kinds
  (`mission_blocked`, `contradiction_detected`,
  `automation_waiting`, `fabrication_waiting`) + public
  `severity_for` for dedup
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

## 4. Implementation

Presence answers three questions over live stores: what
deserves attention, why (scored reasons), and what Jelles can
do (existing routes only). Full contract in
`docs/presence-ecosystem.md`.

Twelve collectors read approvals (desktop/write/mission),
missions (blocked/failed/paused), nodes (offline/stale/
degraded/hardware/compute), automation (human/agent/failed),
fabrication + 3D jobs, research dossiers + node-aware
readiness, candidates, contradictions + discoveries, camera
inbox, symbiosis, craft gaps, and 24h task/mission failures
from the bus. Each collector is best-effort and never raises.

Two fixes found while testing (both covered by new tests):
1. Candidate states are `observation/candidate/supported`
   (not `observed/proposed`) — collector filter corrected.
2. The notifications store carries the severity bucket in
   `type`, not the kind — fan-out dedup matches on
   (severity, title) via the new public `severity_for`.

## 5. Tests

New: 31 tests in `test_big40_presence.py`, all green.
Targeted regression on touched areas (mobile, living world,
telemetry, memory, ecosystem, knowledge, automation):
113 passed, 0 failed. Full-suite discipline held: no repeated
full runs during development.

Categories:
- Aggregation structure + determinism (stable ids, bands,
  provenance, repeat-call order)
- Live derivation (desktop/mission approvals, offline/stale
  nodes, telemetry/hardware/capability items, research
  node-awareness both directions, candidates, bus failures,
  automation waiting with gate text)
- Collector mapping (intel, symbiosis, craft, dossiers,
  fabrication, notify-kind completeness)
- Priority (pure determinism, age bonus cap, unknown-type
  refusal, needs-outranks-discovered)
- Triage (seen/defer flow, band exit, garbage refusals,
  RESOLVED memory, DEFER decides nothing)
- Deep links (every item matches a real route prefix; key
  pages resolve 200)
- Surfaces (mobile bands + greeting, guide AFTERWARDS,
  presence page, topbar counts, 7 morning sections)
- Progression (real quest hrefs, full key set) + overnight
  read-only proof
- Notifications (IN_APP receipt, WEB_PUSH UNAVAILABLE,
  drain-then-empty dedup, kind registry)
- Security (fake-id web defer performs nothing, non-YES
  denies fail-closed, stored markup escaped end-to-end on
  /presence + /mobile + /guide, no health-memory leak,
  wildcard registration refused, capabilities shown as
  claims)

Full Mycelium suite: **1356 passed, 0 failed** across all
109 test files in bounded batches (single run exceeds the
10-min tool timeout; per-batch evidence in the run log).

INVENTory suite: **179 passed + 1 pre-existing failure**
(`test_milestone_3_8.py::test_real_inventory_db_untouched`
asserts the real `data/inventory.db` is exactly 73728 bytes;
on disk it is 573440 bytes through real use). `inventory/`
is untouched by this BIG; failure is environmental and
unchanged. Do not touch that test.

## 6. Smoke

`scripts/b40_smoke.py` on tmp DBs (fresh DBs each run;
reruns clear stale state instead of conflicting): 49/49 OK.

Chain verified:
1. Node registered + telemetry heartbeat (201/204)
2. Hardware/capability availability items derived
3. Seeded offline node → OFFLINE band item
4. Mission + desktop approvals → NEEDS YOU
5. Automation driven to waiting_for_human → item with gate
6. Candidate → DISCOVERED; bus task.failed → NEEDS YOU
7. Research readiness honest (no eligible → named wait)
8. Mobile dashboard greeting + all five bands
9. Guide items all carry Afterwards
10. Notify fan-out IN_APP (WEB_PUSH UNAVAILABLE), then
    drain-to-empty dedup
11. Morning carries all 7 presence sections
12. Pages render: /presence /mobile /guide /nodes /world
    /activity
13. Every deep link resolves 200 (8 hrefs incl. run and
    mission detail pages)
14. Defer hides from needs band, decides nothing
15. Refusals: fake id 404, wildcard 422

## 7. Screenshots

`docs/r40-shots/` (Edge headless, real seed data, reviewed):

1. `mobile-presence-1440.png` — `/mobile` with greeting +
   five bands on top
2. `desktop-presence-1440.png` — `/presence`: NEEDS (5)
   with YES/NO/OPEN/DEFER + priority reasons, AVAILABLE
   (3), DISCOVERED (2), OFFLINE (1), cleared, activity +
   quests; topbar counts visible
3. `world-activity-1440.png` — `/activity` event stream
4. `guide-1440.png` — `/guide` with Afterwards lines
5. `morning-1440.png` — `/morning` with all 7 presence
   sections
6. `notifications-1440.png` — mobile `#recent` rail:
   deeplinked notifications + recent events
7. `node-aware-waiting-1440.png` —
   `/nodes?check_cap=analysis.ollama`: 1 eligible node
   named, offline card dimmed

## 8. Security

- Fake/malformed/resolved attention ids refused (404/422);
  replay refused (must be live).
- Non-YES decisions deny fail-closed through existing
  gates; DEFER (API + web) stores triage only.
- Stored `<script>` markup escaped on every page
  (verified end-to-end); render boundary escapes all item
  text; candidate/input validation holds first.
- Prompt injection contained: extractive text only, no LLM
  in priority or prose.
- No health-memory content in presence output (asserted).
- Wildcard capabilities refused; node claims shown as
  advertisements, never attestations.
- Fan-out skips deferred items, dedups on (severity,
  title), caps per call, never touches WEB_PUSH.
- No new execution surface (static pattern: presence
  imports no executors; triage writes one chat table).

## 9. REAL / TEST / SIMULATED / UNAVAILABLE

| Aspect | Label |
|--------|-------|
| Attention items (derived from live stores) | REAL |
| Priority scores (rule-based, explained) | REAL (deterministic, not a model) |
| Triage states (operator's own decisions) | REAL |
| RESOLVED memory (stored snapshots ≤ 7d) | REAL (labeled as memory, pruned) |
| Hardware/compute availability | REAL claims, unverified (as BIG #39) |
| IN_APP fan-out | REAL (deduplicated store) |
| WEB_PUSH | UNAVAILABLE (explicit, capability endpoint) |
| Overnight digest | REAL observation (no execution) |
| Progression (quests/discoveries/growth) | REAL (store-backed, no XP) |
| Camera live / printer transport / fab execute | Unchanged (UNAVAILABLE / SIMULATED) |

## 10. Limitations

- Presence is only as fresh as its sources (pull-only
  nodes; heartbeat freshness).
- RESOLVED memory (7d) and triage rows (30d) prune —
  long-past resolutions are forgotten by design.
- World reaction is data + CSS (health/counts, dimming,
  breathing dots), not animated graph markers.
- Single recipient (`jelles`); no push transport.
- Contradiction/discovery/symbiosis/craft collectors are
  covered via mapped-module tests; live end-to-end for
  those needs richer seed conversations.

## 11. What Jelles can use tomorrow

1. Open `/presence` — everything needing you in one view,
   ordered, explained, actionable
2. Open `/mobile` — GOOD MORNING/NOW + five bands with the
   same cards and gates
3. Tap YES/NO on any card — the existing gate runs exactly
   as before; DEFER hides without deciding
4. Read the topbar anywhere — waiting/discoveries/offline
   counts link to `/presence`
5. Open `/morning` — seven presence sections answer why
   opening Mycelium is useful today
6. Press notify fan-out — deduplicated IN_APP delivery, no
   spam, no push promises
7. Ask "which node can run research?" — the answer names
   the node and why the others cannot
8. Run `python scripts/b40_smoke.py` with `B40_SMOKE_TMP`
   set — 49 checks re-prove the chain any time

## 12. Recommended BIG #41

Mycelium V2 — the coherent autonomous local-first
ecosystem (per ROADMAP-V2): conversation → idea → research
→ node → observation → candidate → memory → relation →
project → fabrication → verification → morning, provenance
at every link, Jelles approving everything consequential.
Presence gives V2 its attention layer: deepen remote mesh
execution (safe task routing already permits the reads),
grow the quest/progression foundation into the living
game layer, and keep every new power behind the same gates.
