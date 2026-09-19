# Mission templates V2 (BIG #42)

Reusable mission chains built ONLY on existing mission /
approval / task infrastructure. Templates compose safe
operations; they never bypass gates.

## New templates

- `idea_to_verification` (10 steps): readout (idea) →
  research → analysis (candidate) → proposal (project) →
  readout (materials) → analysis (node choice) → fabricate →
  camera_observe → analysis (verification). Fabrication and
  observation start only after explicit mission approval, as
  with any hand-built mission.
- `project_finance_energy` (5 steps): readout (project) →
  analysis (finance) → analysis (energy) → research (gap) →
  proposal (next action). No automatic bookings, no invented
  measurements — unknown stays UNKNOWN.

## Guarantees

- Every step kind is an existing `VALID_STEP_KINDS` member
  (asserted in tests); instantiation runs the same mission
  validation as hand-built missions.
- No generic workflow executor exists: the catalogue is
  closed (8 templates), placeholders are plain `{goal}`
  substitution, consequential steps keep their YES gates.
- Quest states: template-driven missions surface in quest
  trails like any other mission (READY/ACTIVE/WAITING/
  BLOCKED/COMPLETED/FAILED derived from live records).

## Bounded mesh workflows

`POST /api/v1/workflows/preview` (dry run, creates nothing)
and `POST /api/v1/workflows/dispatch` (max 6 steps) chain
pinned mesh delegations — research on Node A, camera work on
Node B, compute on Node C — through the existing task queue:
validate → auth → eligibility precheck → create → assign per
step, coordinator authoritative, nodes pull-based. A failed
step stops the workflow; queued steps keep their own
lease/claim lifecycle and stay visible (never silently
dropped). Same closed contracts as `/mesh/delegate`: no
wildcards, no shell, no secrets, no target drift.
