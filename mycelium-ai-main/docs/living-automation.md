# Living Automation (BIG #38)

Mycelium's automation keeps the workshop going where work is
already safe and approved, and stops exactly where human
authority begins.

## Philosophy

```
Observe → Research → Propose → Wait-for-YES →
Act inside approved plan → Observe → Verify → Record
```

- **No new execution power**: automation uses only existing
  functions (research engine, missions executor, knowledge,
  camera, workshop, conversation intel, packets, notifications).
- **No background threads**: `drive` and `resume` are explicit
  calls from API buttons only.
- **Default-deny step kinds**: a closed allow-list; anything
  else refuses at creation AND at drive time.
- **Consequential work waits**: preparation steps create inert
  drafts/proposals and then the run WAITS with the exact gate
  named. Resume re-reads live store state — approvals are never
  fabricated, inferred, or reused stale.
- **Bounds on every run**: steps, runtime, retries, consecutive
  failures. Fail-closed with exact reasons.
- **Health content never enters candidates**: reuses
  `candidate_from_finding` gate.
- **Secrets never in payloads/packets**: reuses redaction +
  nodemesh hints.

## Step Kinds (Closed Allow-List)

### Read-Only (run freely, also overnight)
- `observe` — missions, candidates, research, nodes, inbox, events
- `readout` — project context, inventory search
- `search` — inventory GET-only bridge
- `research_queue` — queue a research question (draft)
- `research_execute` — execute a queued research run
- `conversation_analyze` — extractive intelligence
- `intel_analyze` — conversation intel summary
- `knowledge_candidate` — propose a candidate (ai-generated, unverified)
- `symbiosis_propose` — propose a connection candidate
- `craft_update` — compute craft tree gaps
- `context_packet` — build a bounded context packet
- `notify` — in-app notification fan-out
- `wait` — explicit pause with a gate

### Preparation (create inert drafts, then wait)
- `mission_propose` — draft mission (read-only steps only)
- `write_propose` — propose a controlled write
- `fab_prepare` — prepare/slice/propose a fabrication job
- `node_prepare` — prepare a node task (capability-routed)
- `camera_session` — run/describe/propose camera session
- `mission_tick` — tick an APPROVED mission only

## Gates (Closed Set)

Every `wait` step carries a gate. Resume re-checks the live store:

- `mission_approved` — mission status is `approved` or `running`
- `write_approved` — proposal status `approved`, decided by human
- `desktop_decided` — desktop action `approved`/`completed`
- `candidate_advanced` — candidate state `supported`/`promoted`
- `research_completed` — research run has dossier or completed
- `time_elapsed` — wall-clock wait until ISO timestamp

## Run Lifecycle

```
create_run(goal, steps, bounds?, overnight?, mission_id?, template_id?)
    → run_id, state="running"
drive_run(run_id, budget_steps=10)
    → executes safe steps until gate, bound, or completion
    → state: running | waiting_for_human | waiting_for_agent | blocked | failed | completed
resume_run(run_id, budget_steps=10)
    → re-checks ALL gates live, continues if met
cancel_run(run_id, reason)
    → terminal state "cancelled"
```

## Bounds (Validated at Creation)

| Bound | Default | Max |
|-------|---------|-----|
| max_steps | 10 | 20 |
| max_runtime_seconds | 600 | 3600 |
| max_retries | 2 | 5 |
| max_consecutive_failures | 3 | 5 |

Exceeding bounds → `blocked` or `failed` with exact reason.

## Overnight Eligibility

A run can be marked `overnight: true` only if ALL steps are in
`OVERNIGHT_SAFE_KINDS` (read-only research/analysis/candidate/
proposal/notify/wait). The night shift observes and prepares;
it never advances executable state.

## Templates

Three built-in templates (JSON + web form):

- `intel_to_research` — analyze conversation → queue research →
  candidate → notify (4 steps, overnight-safe)
- `observation_to_symbiosis` — observe candidates → propose
  symbiosis → craft update → notify (4 steps, overnight-safe)
- `missed_to_mission` — observe intel missed items → propose
  mission → wait for approval → tick (3 steps, NOT overnight)

## API Surface

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

Web routes:
- `GET /automation` — overview + start from template
- `GET /automation/{run_id}` — quest trail, waiting bundle, actions

## Surfaces

- **Guide** (`/api/v1/guide`, `/guide`): waiting/blocked/failed
  automation items with WHAT/WHY/NEXT
- **Mobile** (`/api/v1/mobile/dashboard`, `/mobile`): automation
  quests in progress panel
- **Morning report** (`/api/v1/reports/morning`): automation
  section with runs, states, gates
- **Context packet** (`/api/v1/context/packet`, `packet2`):
  automation section with run_id, goal, state, waiting gate
- **Living state** (`/api/v1/state`): `automation_waiting`,
  `automation_running` counts

## Notifications

Reuses existing notify_center kinds:
- `mission_waiting` — run started, stops at first gate
- `research_finding` — research completed
- `task_completed` — run completed

## Decision Vocabulary

From `decisions.py`:
- `CONTINUE` — safe step done, drive next
- `RETRY` — step failed, within retries
- `REPLAN` — gate unmet, different path needed
- `WAITING_FOR_HUMAN` — gate needs human YES
- `WAITING_FOR_AGENT` — gate needs node/desktop
- `BLOCKED` — bounds exceeded
- `FAILED` — step failed, no retries left
- `COMPLETED` — all steps done
- `CANCELLED` — operator stop

## Security

See `docs/automation-security.md` for threat model, injection
defense, capability escalation refusal, and provenance discipline.

## REAL / TEST / SIMULATED / UNAVAILABLE

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