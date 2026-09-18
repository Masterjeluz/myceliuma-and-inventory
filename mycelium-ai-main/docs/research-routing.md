# Research Routing (BIG #32)

Coordinator owns the queue; nodes are capability providers.
No second task queue, no pushed work, no shell anywhere.

## Executor: research.fetch_url (REAL)

`node_client` executes one allow-listed kind beyond inventory and
screenshots: `research.fetch_url` with payload `{url, run_id?,
max_chars?}`. Guards on the node (defense in depth — the
coordinator validates fully first with
`research_transport.validate_url`):

- https/http only, no credentials, host not
  local/numeric/empty, URL ≤ 2000 chars
- no redirects ever, 20s timeout, text-ish content only
  (`text/*`, `application/json`, `application/xml`), 64KB cap,
  UTF-8 with replacement

Anything else refuses with a reason. Desktop input kinds still
refuse. Requires advertised capability `research.fetch` (claim
loop enforces the subset match).

Advertise it:

```bash
python -m node_client.main --coordinator http://127.0.0.1:8000 \
  --node-id linux-laptop-1 --tier worker \
  --capability research.fetch --poll-seconds 10
```

## Routing

- `GET /api/v1/eligible-nodes?capability=research.fetch` —
  online nodes carrying one capability (deterministic, read-only).
- `/nodes?check_cap=...` — "Which node can do this?" panel with
  honest `WAITING_FOR_AGENT` when nobody qualifies.
- Existing `POST /api/v1/tasks/route` (dry-run) and
  `/api/v1/tasks/{id}/assign` still constrain; nodes still pull
  (`/tasks/claim/{node}`), leases (300s × 3) and fencing unchanged.

## Queue integration

`POST /api/v1/research/queue` accepts `seed_urls` (≤3,
coordinator-validated) and `route` (`local` default,
`node-first`). `run-once` with `node-first` creates one
`research.fetch_url` task per URL for eligible nodes and returns
`{routed: true, task_ids, eligible}` — or honest
`WAITING_FOR_AGENT` with an empty eligible list.

Completion hook (`_ingest_research_fetch`): a successful node
report re-validates URL + text, dedupes by content hash, stores a
`web` SourceRecord (`creator_id: node:{id}`, extracted), attaches
it to the run (`source_ids`, `sources_meta`,
`metadata.node_fetched`), emits `research.fetched`. Failed
reports ingest nothing. The run stays `draft` until an explicit
execute builds the dossier — collection appends, never resets.

## States

REAL: node fetch executor, routing, queue node-first, completion
ingest. FUTURE: `research.extract/analyze/compare` on nodes
(needs reviewed on-node capability, not shipped).
