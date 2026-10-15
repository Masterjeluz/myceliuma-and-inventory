# Stabilization (BIG #16) — IMPLEMENTED

Concurrency, fencing, approvals, auth and retention
hardened without new product features. Invariants:

## Concurrency model

- One connection factory (`database._open_db`): WAL
  journal mode + 15s busy_timeout on every connection.
  Short-lived connections only, never shared across
  threads, never held across requests.
- Schema setup is a process-wide critical section
  (`_INIT_LOCK`); data writes serialize in the engine.
- No retry loops: contention waits in the engine, races
  resolve atomically (conditional writes) or refuse
  loudly. The lifespan has one bounded scheduler task; its
  closed read-only job set uses short-lived worker threads,
  each opening its own DB connections. No queue dispatch,
  model, hardware, approval, or mission-resume work is scheduled.

## Fencing invariant

Central gate `failover.require_writer_epoch`: no lease
row ever → live epoch 0, epoch-0 writers pass
(single-coordinator bootstrap). Once an election ran,
only the live epoch passes — on sync-apply (envelope
epoch), claim (stamped routing epoch) and complete
(stamped routing epoch). Fencing is authority
protection: never approval, never verification, never
a human_verified bypass.

## Campaign ownership invariant

`campaign()` takes BEGIN IMMEDIATE, then writes only
conditionally on the exact row just read (renew:
holder+epoch match; takeover: epoch+holder+expiry
match; first lease: INSERT … ON CONFLICT DO NOTHING +
rowcount). Two simultaneous campaigners can never both
become valid holders of the same epoch: same node
converges (renew keeps the token), rivals lose loudly.

## Event retention

Central `retention.run_retention` (operator-triggered
via POST /api/v1/maintenance/prune): newest N survive
per scope — interface_events (500), job_runs (20/job),
conversation_events (200/mission). dist_events,
dist_conflicts and write_proposals are never pruned
(sync cursors, live conflicts, approval lifecycle).
The background scheduler separately caps only its own
tagged `job_runs` entries at 20 per scheduled job; it does
not run the broader retention pass.
Indexes: tasks(status), nodes(last_seen),
research_sources(content_hash), memories(updated_at,
truth). Claim hot path bounded (500).

## Node authentication model

- New identities require a non-trivial token (≥16
  chars); choosing a node_id alone creates nothing.
- Token-bound identities verify on register/heartbeat/
  claim; rebind needs the current token (rotation
  endpoint) or the operator key (legacy bind).
- Legacy rows keep heartbeating/claiming frozen
  (freshness only, advertisement and authority flags
  immutable) until operator rotation binds a token.
- Legacy identities cannot campaign.
- enable/disable and rotation-on-legacy need
  MYCELIUM_OPERATOR_KEY (local env; unset refuses
  everything). Disabled stickiness preserved.

## Health isolation

Health-type memories stay out of generic list/retrieve
and Live memory sections unless explicit health scope
(`include_health` + `health.read`). Same rule for
consolidation dedup. Derived content quoting health
data should itself be typed health (caller duty).

## Physical-agent approval/verification

robot.execute and drone.mission are WriteProposal
mutation types: exact YES via decide_write,
fingerprint/staleness/target bound, live recheck of
safety/capability/idleness at approve time. The
generic execute path refuses them (HARDWARE_REQUIRED).
Verification needs telemetry plus a cited stored
record (mem_… memory or obs-… camera observation);
caller text alone never verifies.

## Mock/simulation labeling

Mock Garmin imports carry origin garmin:mock (API
field + UI badge); Instagram mock exports keep
mock: references and instagram:mock provenance to
storage; simulated printers and test-only camera
observations render [SIMULATED]/[TEST] badges. Live
Garmin/Instagram stay UNAVAILABLE.

## Pagination convention

Cursors: after_rowid (int) for append-only logs,
since (ISO timestamp) for feeds, cursor (int) for
mock/provider pages. Page caps enforced everywhere
(sync 100, memory 200, health 500, jobs/runs 100,
events 100); MAX_MEMORIES (5000) enforced at save.
Legacy endpoints keep their shapes; new code follows
this convention.

## Voice/desktop policy (option A)

Desktop input is interface approval, never physical:
a spoken YES may resolve pending desktop actions
through the voice flow. Physical mutations
(printer.execute, robot.execute, drone.mission) never
resolve by voice — enforced at approval-request time.
