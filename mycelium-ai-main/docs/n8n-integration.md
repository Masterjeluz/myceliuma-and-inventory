# n8n Integration Plane (BIG #17) — IMPLEMENTED

n8n is the external automation plane around Mycelium:
schedules, external APIs, webhooks, transforms,
notifications, transport retries. It is never the
coordinator and holds no Mycelium authority.

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
