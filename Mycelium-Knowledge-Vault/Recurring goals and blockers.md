# Recurring goals and implementation blockers

Audit updated: 2026-10-15. This note compares current source, the dated
`docs/DEVELOPMENT_STATE.md` journal, and the 15 milestone reports
`mycelium-ai-main/docs/BIG31-final-report.md` through
`BIG45-final-report.md`.

## What can be counted

The repository does not contain a complete export of every OpenCode or
Codex conversation, so it cannot support an exact count of how many times
Jelles explained each goal in chat. The counts below are **distinct
milestone documents containing a topic**, not the number of failed
implementations:

| Topic | Evidence in the repo | What the count means |
|---|---|---|
| City, town, and NPC work | 8 dated entries in `docs/DEVELOPMENT_STATE.md` cover Solar Punk/Town/NPC iterations from 2026-10-05 to 2026-10-06. | At least 8 recorded build or repair passes, not 8 restarts from zero. |
| Ollama and vision | 6 of the 15 BIG31–45 reports mention Ollama or vision. | Provider work was revisited across milestones; the reports do not imply each pass failed. |
| Node onboarding | 3 of the 15 reports mention `node_client` or bootstrap. | Bootstrap exists, but a report mention is not evidence that a device remains online. |
| Printing | All 15 reports mention a printer or printing. | This is a repeated status topic. The code still marks real transport unavailable or execution simulated; it is not 15 completed real-print attempts. |
| Background scheduler | BIG38 explicitly records no background scheduler; the current code and `CURRENT_STATE.md` show the new safe scheduler. | Earlier behavior was intentionally on-demand. The read-only scheduler is a new, narrow change. |

## Why it kept feeling “almost done”

### The work landed in separate layers

Several milestones completed data models, routes, or UI controls before
the corresponding local service, worker, credential, or hardware path was
available. A button can be real while its downstream transport is still
`UNAVAILABLE`; a simulated print pipeline is useful preparation, but it
is not a physical print. Older milestone documents often say “DONE” for
their layer, while the current system still has a wider integration gap.

### Services and workers can be independently offline

The coordinator, INVENTory, Ollama, Hermes, CouchDB, and node workers are
separate processes with separate health conditions. On 2026-10-15 the
coordinator, INVENTory, Hermes, Ollama, scheduler, and CouchDB HTTP status
answered locally. The registered node was still reported stale. Obsidian
was connected to the separate Solarlab vault, not the prepared Mycelium
vault; Android had no private HTTPS route. Docker CLI access was denied in
the check, so container state was not independently confirmed. This is why
some model/UI work can be real while node execution and project-vault sync
are still incomplete.

### Nodes deliberately have limited authority

Nodes poll the coordinator and can claim only advertised capabilities.
The current registry had one stale node; no connected worker was available
to claim the queued research task. File transfer between nodes is not
implemented. A truly unattended Windows installer also needs a safe way
to persist its node token, but the repository contract forbids secret
storage and this choice still needs a deliberate policy decision.

### Hardware is kept behind separate gates

The print workflow prepares artifacts and simulates execution, while real
printer transport and print-arm automation remain unavailable. Filament,
printer state, and camera verification must be live and fail-closed before
an automated print path is safe. Existing policy keeps physical actions
out of automated test runs and behind explicit approval.

### Runtime reloads and model availability have caused false “broken” states

The dated journal records a stale Uvicorn process returning 404 for a new
route, Ollama stopping when its service window disappeared, and a local VLM
default model that was not installed. The current vision flow now uses
`qwen3.5:4b`, ignores system proxies for loopback requests, caps generation,
and preserves inline model descriptions. A synthetic screen observation
now passes through the same `_hermes_screen_summary` path used by Mos.

## Current repairs in this pass

- The coordinator starts a fixed scheduler for four read-only jobs and
  exposes process status at `/api/v1/jobs/scheduler` and `/system`.
- Mos can receive opt-in text-only screen context from the local VLM. The
  live synthetic check returned `REAL`; it did not send raw pixels to
  Hermes.
- The live model-route page now returns `200`; only code routes are
  unavailable because the current Python environment cannot import
  `code_worker`. Package discovery includes that package in source now;
  the active process has not been reinstalled or restarted since the fix.
- The per-user startup script attempts all local services independently,
  opens Docker Desktop, and starts loopback CouchDB when the engine is
  ready. It continues when one service is unavailable.

## Practical next order

1. Open `Mycelium-Knowledge-Vault/` as its own Obsidian vault, configure
   its own CouchDB database, and prove one note round-trips on desktop.
2. Configure the selected NetBird-only HTTPS route and prove that same note
   round-trips with Android; keep CouchDB loopback-only.
3. Decide how node tokens may be stored before creating unattended node
   installers or auto-start workers.
4. Reconnect one real node and prove a bounded harmless task end to end.
5. Keep printer automation in simulation until live condition sensors,
   print transport, arm behavior, and visual empty-bed verification are
   independently proven.
6. Make `/solarpunk` status reflect real node/model/task signals before
   expanding the scene or adding more NPC activity.
