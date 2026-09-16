# n8n Integration Plane (BIG #17) — IMPLEMENTED

Proven end to end locally in BIG #18 (23-check live
harness over real HTTP against uvicorn + committed
workflow artifacts; no n8n binary was installable on
that machine — 0 bytes disk free, Docker daemon down —
so execution semantics were verified request-for-request
with the exact payloads the workflows send).

n8n is the external automation plane around Mycelium:
schedules, external APIs, webhooks, transforms,
notifications, transport retries. It is never the
coordinator and holds no Mycelium authority.

## Local install/start (localhost only)

1. Free ~2 GB disk. Scoped install outside the repo
   (never global, never into the project):
   `mkdir n8n-local && cd n8n-local && npm init -y &&`
   `npm install n8n --no-audit --no-fund`.
2. Start Mycelium first (tmp DBs for tests, real DBs
   for real runs):
   `python -m uvicorn coordinator.app.main:app --host`
   `127.0.0.1 --port 8000` (from `mycelium-ai-main/`).
3. Issue an integration key (operator key from local
   env): `POST 127.0.0.1:8000/api/v1/integrations/`
   `generic/keys {"operator_key": "..."}` — store the
   returned key in n8n, never in git.
4. Start n8n disposable: `N8N_USER_FOLDER=<tempdir>`
   `N8N_HOST=127.0.0.1 N8N_PORT=5678`
   `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`
   `MYCELIUM_N8N_KEY=<issued key> n8n start`.
   No tunnel, no public exposure, no real credentials.
5. Import: `n8n import:workflow
   --input=n8n/workflow-a-schedule-morning-report.json`
   (same for workflow-b). Execute once manually before
   activating any schedule.
6. Stop: Ctrl-C both processes; the temp user folder
   and temp DBs are disposable. Nothing persists in
   the repo (workflows carry no secrets).

## Workflows (committed artifacts in `n8n/`)

- Workflow A (`workflow-a-schedule-morning-report.json`):
  daily 07:00 schedule → trigger `morning_report` with a
  date-stable run_key (re-runs idempotent).
- Workflow B (`workflow-b-outbox-notify.json`): every 5
  minutes poll outbox → local log node as the test
  notification (no external messaging, no credentials)
  → ack loop (SplitInBatches, one by one). Empty outbox
  ends at the IF node.
- Both use `$env.MYCELIUM_N8N_KEY` for the
  `X-Integration-Key` header and talk to
  `http://127.0.0.1:8000` only. `tests/test_n8n_`
  `workflows.py` pins these properties (parseable,
  linked, localhost-only, secret-free, known jobs/
  labels only).

## Architecture boundary

```
external system → n8n → IntegrationEnvelope → validation
→ provenance → domain storage (Mycelium owns all of it)

Mycelium → outbox labels → n8n polls → delivers → acks
(Mycelium never calls n8n, never forwards URLs)
```

n8n must never become a second scheduler (it triggers
KNOWN jobs only), memory store, coordinator, approval
engine or event store. All of those stay in Mycelium
and are reused, not duplicated.

## Authentication

Three separate identities: operator (local env key),
node (bound bearer token), integration (per-integration
bearer key, hash-only storage, operator-issued, shown
once). Capabilities are closed and non-overlapping:

- `integration:ingest` — POST /api/v1/integrations/events
- `integration:trigger` — job trigger, outbox poll/ack
- `integration:status` — ingestion ledger

No global admin token, no node/operator reuse, no
unauthenticated webhooks. Keys arrive via the
`X-Integration-Key` header.

## Webhook flow

POST /api/v1/integrations/events carries an
IntegrationEnvelope (integration_id, source,
external_event_id, event_type, occurred_at, payload,
provenance, schema_version, idempotency_key).
Validation is fail-closed: unknown/disabled
integration, source spoofing, disallowed event type,
executable or secret-shaped payload keys (bounded
nesting via the shared payload rules), non-
external-source or upgraded provenance, bad hashes.
A webhook is an observation/input — never fact, never
approval, never execution. Domain routing is a closed
map: garmin/generic `health.measurements` → health
storage (deduped), generic `memory.observation` →
observation memory (external_source truth).

## Scheduler flow

POST /api/v1/integrations/trigger runs one KNOWN job
by name through the existing `jobs.run_job` semantics
(bounded, idempotent via run_key, recorded). n8n says
which registered job runs — never what code runs.
Suitable for watcher scans, morning reports, research
polling, wearable imports, maintenance/prune.

## Idempotency

(integration_id, idempotency_key) with a UNIQUE ledger
index: first event accepted, same key + same hash →
duplicate, same key + different hash → conflict
(stored side by side, never overwritten). Concurrent
double-submits converge via the unique index instead
of double-applying.

## Provenance

Mandatory external-source provenance with creator
`n8n:<integration>` and human_verified=false; anything
else refuses. The transport layer can never upgrade
provenance. Labels survive to storage: MOCK (mock
Garmin/Instagram), TEST, LIVE (real source). Mapped
domain records cite transport + external event id.

## Secret boundary

n8n holds ALL external credentials in its own
credential store (OAuth secrets, API keys, webhook
secrets). Mycelium receives only identity, metadata,
normalized data and provenance — never refresh
tokens, API passwords or private keys. Secret-shaped
payload keys refuse at the boundary. Mycelium stores
only hashes of integration keys.

## Retry responsibility

n8n: transport retry, external API retry, workflow
failure — bounded (max 3, backoff, stable
idempotency key). Mycelium: validation, idempotency,
provenance, state, approval, verification. Mycelium
never retries into n8n (poll-model outbox). Duplicates
are always safe.

## Mock/live labeling

Garmin: UNAVAILABLE (no official credentials, no
reviewed live transport) with explicit requirements
at GET /api/v1/integrations/garmin/readiness; mock
provider for tests, always labelled MOCK to storage.
Generic webhook source: AVAILABLE as observation
input. No fake-live anywhere.

## Garmin readiness

Ready path when official access exists: n8n → Garmin
integration (official API only, no scraping, no
private endpoints) → webhook health.measurements →
existing import pipeline (cursor, dedup, rate-limit).
Nothing of the live path is implemented; claiming
otherwise would be fake-live.

## Forbidden operations (all tested negative)

approve, physical execution, node-auth bypass,
fingerprint bypass, human_verified escalation,
faked verification, DB access, shell/commands,
auto-FACT promotion, arbitrary URL execution,
secret smuggling, silent conflict overwrite.
