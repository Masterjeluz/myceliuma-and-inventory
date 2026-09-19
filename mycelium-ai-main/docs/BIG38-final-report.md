# BIG #38 — eindrapport

## 1. Status

DONE — built, tested, smoked, screenshotted, documented,
committed, pushed.

## 2. Commit SHA

`BIG #38 - build living automation` (SHA verified against
remote HEAD after push; see git log).

## 3. Files changed

New:
- `coordinator/app/automation.py` — engine (runs/steps/bounds/
  resume, step executors on existing functions, gates)
- `tests/test_big38_automation.py` — 20 tests (engine, bounds,
  resume, gates, security)
- `scripts/b38_smoke.py` — full chain on tmp DBs (17 checks)
- `scripts/b38_shots.py` — seed data for screenshots
- `docs/r38-shots/` (6 PNGs)
- `docs/living-automation.md`
- `docs/automation-security.md`
- `docs/BIG38-final-report.md` (this file)

Extended:
- `coordinator/app/events.py` — additive `automation.*` bus types
- `coordinator/app/main.py` — automation API + web routes,
  `/automation` pages, mission-detail link, morning section,
  packet section
- `coordinator/app/living_state.py` — automation counts
- `coordinator/app/guide.py` — waiting/blocked/failed items
- `coordinator/app/mobile.py` — automation quests in progress
- `coordinator/app/ui.py` — subtle symbiosis/craft automation
  styling (reduced-motion safe)
- `coordinator/app/reports.py` — automation morning section
- `coordinator/app/context_packet.py` — automation sections
- `docs/NEXT-AI-CONTEXT.md`
- `docs/ROADMAP-V2.md`
- `README.md` (touch-up)

## 4. Living Automation Engine

`automation.py` implements the observe → research → propose →
wait-for-YES → act-inside-approved-plan → observe → verify →
record loop. Mycelium keeps going where work is already safe
and approved, and stops exactly where human authority begins.

**No new execution power** — steps execute only through
existing functions (research engine, knowledge, missions
executor, camera, workshop, conversation intel, packets,
notify).

**No background threads** — `drive` and `resume` are explicit
calls from API buttons only.

**Default-deny step kinds** — closed allow-list; anything else
refuses at creation AND at drive time.

**Consequential work waits** — preparation steps create inert
drafts/proposals and then the run WAITS with the exact gate
named. Resume re-reads live store state — approvals are never
fabricated, inferred, or reused stale.

**Bounds on every run** — steps, runtime, retries, consecutive
failures. Fail-closed with exact reasons.

## 5. Step Kinds (Closed Allow-List)

| Category | Kinds |
|----------|-------|
| Read-only (also overnight) | `observe`, `readout`, `search`, `research_queue`, `research_execute`, `conversation_analyze`, `intel_analyze`, `knowledge_candidate`, `symbiosis_propose`, `craft_update`, `context_packet`, `notify`, `wait` |
| Preparation (inert drafts → wait) | `mission_propose`, `write_propose`, `fab_prepare`, `node_prepare`, `camera_session` |
| Execution (inside approved only) | `mission_tick` |

## 6. Gates (Closed Set)

`mission_approved`, `write_approved`, `desktop_decided`,
`candidate_advanced`, `research_completed`, `time_elapsed`.

Resume re-checks live store every time — no cached verdicts.

## 7. Run Lifecycle

```
create_run(goal, steps[], bounds?, overnight?, mission_id?, template_id?)
    → run_id, state="running"
drive_run(run_id, budget_steps=10)
    → executes until gate/bound/completion
    → state: running | waiting_for_human | waiting_for_agent | blocked | failed | completed
resume_run(run_id, budget_steps=10)
    → re-checks ALL gates live, continues if met
cancel_run(run_id, reason)
    → terminal "cancelled"
```

## 8. Bounds (Validated at Creation)

| Bound | Default | Max |
|-------|---------|-----|
| max_steps | 10 | 20 |
| max_runtime_seconds | 600 | 3600 |
| max_retries | 2 | 5 |
| max_consecutive_failures | 3 | 5 |

## 9. Overnight Eligibility

Runs marked `overnight: true` must contain ONLY overnight-safe
kinds (read-only research/analysis/candidate/proposal/notify/
wait). Checked at creation and via `/overnight` endpoint.
Night shift observes and prepares; never advances executable
state. No self-start at night — explicit arming only.

## 10. Templates

Three built-in templates (API + web form):

1. `intel_to_research` (4 steps, overnight-safe):
   `intel_analyze` → `research_queue` → `knowledge_candidate` → `notify`
2. `observation_to_symbiosis` (4 steps, overnight-safe):
   `observe` candidates → `symbiosis_propose` → `craft_update` → `notify`
3. `missed_to_mission` (3 steps, NOT overnight):
   `intel_analyze` → `mission_propose` → `wait` (mission_approved)

## 11. API Surface

```
GET  /api/v1/automation/templates
POST /api/v1/automation/from-template
POST /api/v1/automation/runs
GET  /api/v1/automation/runs
GET  /api/v1/automation/runs/{run_id}
GET  /api/v1/automation/runs/{run_id}/overnight
POST /api/v1/automation/runs/{run_id}/drive
POST /api/v1/automation/runs/{run_id}/resume
POST /api/v1/automation/runs/{run_id}/cancel
```

Web:
- `GET /automation` — overview + start from template
- `GET /automation/{run_id}` — quest trail, waiting bundle, drive/resume/cancel buttons

## 12. Surfaces

| Surface | Automation Integration |
|---------|------------------------|
| Guide (`/guide`, `/api/v1/guide`) | Waiting/blocked/failed items with WHAT/WHY/NEXT |
| Mobile (`/mobile`, `/api/v1/mobile/dashboard`) | Quests in progress panel |
| Morning report (`/api/v1/reports/morning`) | Automation section with runs, states, gates |
| Context packet (`/api/v1/context/packet`, `packet2`, `.md`) | Automation section with run_id, goal, state, waiting gate |
| Living state (`/api/v1/state`) | `automation_waiting`, `automation_running` counts |
| Notifications | Reuses `mission_waiting`, `research_finding`, `task_completed` |

## 13. Decision Vocabulary

From `decisions.py`: `CONTINUE`, `RETRY`, `REPLAN`,
`WAITING_FOR_HUMAN`, `WAITING_FOR_AGENT`, `BLOCKED`,
`FAILED`, `COMPLETED`, `CANCELLED`. Bus events use
`automation.*` types.

## 14. Security

See `docs/automation-security.md`. Key invariants:

- Closed step-kind allow-list (creation + drive)
- Gate re-checks live store on resume
- No approval fabrication
- Secret scan on write_propose payloads
- Health content never becomes candidate
- Capability escalation refused (no wildcard, allow-list only)
- Path traversal refused (entity_id validation)
- No shell/RCE surface (static assert)
- Prompt injection contained (deterministic extractive only)
- Provenance: `ai-generated`, `human_verified=False`

## 15. Tests

New: 20 tests in `test_big38_automation.py` — all green.

Categories:
- Creation validation (closed kinds, bounds, gates, secrets)
- Safe drive chain (read-only completes, health blocked)
- Research queue + guarded execute
- Symbiosis + craft + links
- Wait gate + resume flow
- Mission propose → wait → approve → resume → tick
- Stale approval never wakes
- Mission tick refuses unapproved
- Write prepare → human YES → resume
- Bounds stop runs (max_steps, max_consecutive_failures)
- Cancel + terminal rules
- Templates + overnight eligibility
- Surfaces (guide, mobile, morning, packet, living state)
- Pages (automation overview, detail, mission link, drive)
- Security (injection contained, capability escalation refused, no shell surface, gates honest)

## 16. Smoke

`scripts/b38_smoke.py` on tmp DBs: 17/17 OK.

Chain verified:
1. Conversation import → intelligence analysis
2. Research queued from intel fingerprint
3. Automation run from template
4. Manual automation run (8 steps)
5. Safe continuation drives to `waiting_for_human`
6. Gate names exact mission approval
7. Human YES through existing endpoint
8. Resume re-checks live → completes
9. Memory/event recorded
10. Morning report covers automation
11. Packet carries automation section
12. Mobile path renders
13. Living state honest
14. Bounded retry fails closed
15. Camera path honest (unknown session refuses)
16. 3D path honest (missing entity refuses)
17. Node route prep honest

## 17. Screenshots

`docs/r38-shots/`:

1. `automation-overview.png` — `/automation` with templates and runs in various states
2. `automation-detail-waiting.png` — run detail showing quest trail, waiting gate, resume button
3. `automation-detail-completed.png` — completed run with memory link
4. `guide-automation.png` — guide showing automation waiting item
5. `mobile-automation.png` — mobile dashboard progress panel with automation quest
6. `morning-automation.png` — morning report automation section

All captured with Edge headless, real seed data, reviewed.

## 18. REAL / TEST / SIMULATED / UNAVAILABLE

| Aspect | Label |
|--------|-------|
| Safe step execution | REAL |
| Gate re-check (live store) | REAL |
| Research queue/execute | REAL (provider REAL/TEST/UNAVAILABLE) |
| Mission propose/tick | REAL (tick only inside approved) |
| Write propose | REAL (inert proposal, human gate) |
| Node prepare | REAL (capability-routed, no execution) |
| Camera session | REAL (describe/propose), UNAVAILABLE (live Insta360) |
| Fab prepare | REAL (prepare/slice/propose), SIMULATED (execute) |
| Overnight runs | FUTURE (armed explicitly, no self-start) |
| Background threads | NEVER |

## 19. Limitations

- No background scheduler — runs only drive on explicit call
- Overnight eligibility checked but no auto-arm (future: cron)
- Camera live capture UNAVAILABLE (Insta360 transport missing)
- Printer transport UNAVAILABLE (fab execute SIMULATED)
- Web push UNAVAILABLE
- Full Mycelium suite needs batching (1231+ tests > 10 min)

## 20. What Jelles can do tomorrow

1. Open `/automation` — see templates + runs
2. Start `intel_to_research` template from a conversation
3. Watch it queue research, propose candidate, notify
4. Start manual chain: observe → research → propose symbiosis → propose mission → wait
5. Approve mission at `/missions/{id}` → exact YES
6. Resume automation → ticks mission → notifies → completes
7. Check `/guide` — sees automation waiting items
8. Check `/mobile` — automation quest in progress
9. Read morning report — automation section summarizes
10. Copy context packet (with automation section) to continue elsewhere

## 21. Recommended BIG #39

Presence — notifications, mornings, overnight: per-recipient
in-app delivery, morning "why open Mycelium today" answer,
overnight digest of queue + discoveries + connections. Web
push only with a real transport; until then explicit
UNAVAILABLE.