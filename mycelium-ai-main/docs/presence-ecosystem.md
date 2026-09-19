# Presence Ecosystem (BIG #40)

Mycelium knows what deserves Jelles' attention, why, and what
can be done about it — derived live from existing stores,
never stored twice, never inventing urgency.

## Philosophy

```
Existing stores → presence derives → bands + priority →
mobile / desktop / world / guide / morning. Triage only
stores Jelles' own SEEN/DEFERRED. Nothing else is stored.
```

- **No duplicate state**: attention items are derived fresh
  on every call from approvals, missions, nodes, telemetry,
  research, candidates, conversations, cameras, craft,
  symbiosis, automation and fabrication. The single stored
  table (`attention_triage`) holds only the operator's own
  triage decisions.
- **No new authority**: presence never approves, executes, or
  grants anything. YES/NO post to the existing gates with
  their exact mechanics; DEFER is an honest non-action that
  only hides an item from the urgent bands.
- **Deterministic priority, never an LLM**: base score per
  closed type + age bonus (+1/hour, capped +24), every point
  explained in `priority_reasons`. Same store state always
  yields the same order.
- **Stable ids, no fake items**: `att_<kind>_<real-id>`.
  Triage of an id that is not live right now is refused
  (fake ids, resolved items, replay all fail closed).
- **Provenance always**: items carry `derived /
  presence-engine / human_verified=False`. Node capabilities
  render as advertisements, never attestations. Health
  content is never pulled in.

## Attention model

`{id, type, band, priority, priority_reasons, title, reason,
source, related_entity, related_mission, related_task,
action, open_href, created_at, updated_at, status,
provenance}`

Bands: NEEDS YOU (approvals, blocked/failed), WAITING
(stale, degraded, contradictions, paused work), AVAILABLE
(connected hardware, offered capabilities), DISCOVERED
(candidates, findings, observations, proposals), OFFLINE
(offline/stale nodes, disconnected hardware).

Statuses: NEW / ACTIONABLE (derived), SEEN / DEFERRED
(operator triage, stored), RESOLVED (triage exists but the
source cleared — shown briefly from the stored snapshot),
EXPIRED (deferred older than 7 days). Rows prune after
30 days.

## Triage store

`attention_triage(item_id, status, decided_by, title, kind,
updated_at)` in the chat DB. Only SEEN/DEFERRED are stored;
only for currently-live items; DEFER performs nothing.

## Priority (base scores)

100 approvals (human authority) · 90 blocked/failed ·
85 automation waits for human · 80 node offline · 70
fabrication waiting · 65 paused mission · 60 stale node ·
55 disconnected hardware · 50 stale telemetry /
contradiction · 45 research finding / research waiting ·
35 candidate · 30 inbox / craft gap · 25 discovery /
symbiosis · 20 available hardware / capability. Age adds up
to +24. Agent-side waits score lower (40) than human gates.

## Node-aware waiting (BIG #39 hardware reality)

Research readiness reuses the real router over live registry
state: eligible nodes plus per-node rejection reasons. The
guide and presence say *which* node can serve and *why the
others cannot* ("only workshop-laptop can; pi-sensor lacks
analysis.ollama"). No remote execution beyond what task
routing already permits.

## Surfaces

| Surface | Presence integration |
|---------|----------------------|
| `/presence` + `/api/v1/presence` | Bands, items with WHAT/WHY/SOURCE/NEXT + YES/NO/OPEN/DEFER, priority reasons, recently cleared, ecosystem activity, quests |
| `/mobile` + dashboard JSON | GOOD MORNING/NOW greeting, five bands on top, same cards and gates; `#recent` rail with deeplinks |
| Topbar (every page) | Living state + `N waiting · M discoveries · K offline` linking to `/presence` (best-effort, never breaks pages) |
| `/nodes` | Offline/stale cards dim; online dots breathe; capability dry-run answers routing questions |
| World graph | Registry overlay carries health/telemetry/hardware/compute; overlays stay dashed context, never truth |
| Guide | Every item gains AFTERWARDS: what truthfully happens after the NEXT step |
| Morning (`/morning`, `/api/v1/reports/morning`) | Seven sections: Needs you, Overnight changes, Discoveries, Available resources, Blocked work, Offline and stale hardware, Suggested next actions |
| Notifications | Deduplicated IN_APP fan-out (`POST /api/v1/presence/notify`), explicit calls only; new kinds `mission_blocked`, `contradiction_detected`, `automation_waiting`, `fabrication_waiting`; WEB_PUSH stays UNAVAILABLE |

## Overnight digest

Read-only: event counts per type in the window + current
waiting totals. Observes, never proposes, never approves.
Morning presents it as "Overnight changes". No scheduler, no
background threads — explicit reads only.

## Progression (game-layer foundation)

Quests (open missions + automation runs with done/total),
discoveries/observations/growth/activity counts (24h),
online nodes, capabilities unlocked — every number backed by
a live store. No XP, no fake accomplishments. Real state is
the progression system.

## Security

- Fake attention/mission/entity ids refused at triage.
- Replay (deferring resolved items) refused.
- Non-YES decisions deny fail-closed through existing gates.
- Stored markup is escaped at every render boundary
  (`ui.esc`); candidate/input validation holds first.
- Prompt injection contained: presence text is extractive
  (titles, counts, closed-template reasons) — no LLM.
- Health memories never enter presence output.
- Node-reported capabilities displayed as claims; wildcard
  advertisements still refused at registration/heartbeat.
- Notification fan-out deduplicates on (severity, title);
  deferred items never notify; WEB_PUSH never involved.

## Limitations

- Presence is only as fresh as its sources (pull-only
  nodes; heartbeat freshness).
- RESOLVED memory lasts 7 days from stored snapshots, then
  prunes — long-past resolutions are forgotten.
- The world graph shows presence as data (health/counts),
  not as animated markers; motion stays in CSS
  (reduced-motion safe).
- No per-recipient routing beyond `jelles`; no push
  transport.
