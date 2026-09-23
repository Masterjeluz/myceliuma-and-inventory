# Mycelium autonomy scout

One look, at most one task. External helper beside `code_worker/`:
each process run is one interval — it reads presence + tasks (+
nodes for fleet matching), applies deterministic rules, and POSTs
at most one new queued task when real work is missing. No
coordinator daemon, no scheduler, no new database, no approval
paths touched.

## Run

Single interval (cron calls this; nothing runs permanently):

```powershell
python -m scout.main --coordinator http://127.0.0.1:8000
```

Decide without creating anything:

```powershell
python -m scout.main --coordinator http://127.0.0.1:8000 --dry-run
```

## Rules (fixed order, first applicable wins)

1. **Fleet telemetry** — presence counts `offline > 0` and no open
   `fleet-telemetry` task and a live online node advertises
   `system_inventory` → one `system_inventory` task.
2. **Attention summary** — first NEEDS-band attention item with a
   stable id, no open `att-<id>` task, and a live node advertises
   `analysis.summarize` → one `analysis.summarize` task.

Anything uncertain (HTTP error, unreadable shape, id-less item,
no capable online node, unreliable dedupe) means **no task**
(fail closed, never best-effort).

## Allowed task kinds

`system_inventory`, `research.fetch_url`, `inventory.lookup`,
`analysis.*`, `code.*`. Everything else is refused locally.

## Safety policy

- Endpoints: `GET /presence`, `GET /tasks`, `GET /nodes`,
  `POST /tasks` (creation only). No approve/write/physical/
  verify/desktop/dispatch/mission/claim/complete endpoints —
  refused before any network I/O.
- Dedupe by stable key in the task payload (`scout_dedupe_key`);
  only `queued`/`assigned` tasks block duplicates. Max one
  creation per run.
- Payloads carry goals and keys only — never commands, paths,
  or secrets.

## Interval

Cadence comes from the caller (OS cron / n8n schedule), never
from this script and never from the coordinator. Suggested start:
every 15 minutes; `--dry-run` first to observe decisions.
