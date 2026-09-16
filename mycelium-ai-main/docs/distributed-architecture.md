# Distributed Mycelium Architecture (BIG #8)

Pull-based, capability-gated task distribution over ordinary
local machines. **The coordinator never sends arbitrary
executable code to nodes**: nodes pull task kinds they
understand, execute only allow-listed local behavior, and
report results. Routing is scheduling logic — never a claim
that one model is "better".

```
task requirements (closed, declarative)
        ↓
route_task(requirements, advertised nodes, policy)
        ↓ RouteDecision (selected + eligible + rejected + why)
        ↓
assign (queued task → node constraint, still pull-only)
        ↓
node pulls / claims (revalidates caps, lease, attempts)
        ↓
execute (allow-listed local executor only)
        ↓
result → verification (existing rules)
```

## Nodes

Stable `node_id` (never display names). Statuses: unknown,
online, stale, offline, disabled (sticky — re-registration
never clears it). Freshness: heartbeat ≤ 60s. Node/runtime
state lives in the coordinator queue DB, never in INVENTory.

Advertisement (validated, closed, fail-closed):

- capabilities: explicit strings, no `*` wildcards, no
  inheritance. A task can never grant a capability.
- models: `mod_*` (INVENTory world-model link) or `model:`
  (node-local runtime). World records describe models;
  advertisements describe "this node has this available now".
- executors: `exec:<kind>` namespace only.
- resources: bounded hints (cpu/mem/gpu/storage/energy),
  never guarantees, never measurements.
- locality: closed label; equality match or `any`.
  Loopback-only transport stays the real boundary.

## Trust (minimal, local-first)

Per-node bearer token from local config (`--node-token` /
`MYCELIUM_NODE_TOKEN`, placeholder in `.env.example`, never
committed). The coordinator stores only a salted hash, never
the token; tokens never appear in logs or API output. First
registration binds, later calls must match (403 otherwise).
Nodes without a hash stay in legacy mode so existing clients
keep working. This proves secret possession on a trusted LAN
— it is NOT PKI. Rotation = register again with a new token.

## Routing

`route_task` in `coordinator/app/routing.py`. Hard gates:
fresh + live + authenticated (when required) + required
capabilities ⊆ advertised + model types + executor +
locality. Preferences only order: preferred model ids,
memory/GPU minimums, solar + energy-level policy. Energy
never disqualifies. Tie-break: lowest node_id (fully
deterministic). Every decision explains itself
(`selected … because …`, per-node rejection reasons).

Model routing reuses the requirement vocabulary (model type /
model id / vision capability) — never quality ranking, never
auto-invocation, never downloads, never cloud.

## Queue placement

`POST /api/v1/tasks/{id}/assign` constrains a queued task to
a node (explicit id must prove eligible, or auto-route);
assignment never pushes work — the node still claims.
`POST /api/v1/tasks/route` is a dry run (no state change).
`GET /api/v1/tasks/{id}` exposes requirements, assignment
and the routing explanation for chat/mission clients.

Claim revalidates live: assignment ownership, capability
subset, model types, executor, token, freshness, attempts.
The desktop-action claim path (`/desktop/actions/next`)
checks tokens identically.

## Leases, retry, failure

Existing lease/attempt machinery is authoritative (300s
lease, max 3 attempts, atomic transitions). Lease expiry
requeues software tasks and fails exhausted ones — except
physical tasks (`requirements.physical_action`) with
uncertain execution, which become `blocked` for the operator
instead of silently requeueing. A printer start, click or
other physical action is therefore never duplicated because
a node disappeared. Retry stays bounded; counters never reset.

## Desktop agent

Unchanged behavior, token-aware: register/heartbeat/claim
send `MYCELIUM_NODE_TOKEN` when configured, omit it
otherwise (legacy mode). Pull-only, no shell, approval gate
and binding proof untouched.

## Energy

Optional hints (`energy_source`, `energy_level`,
`energy_priority`) feed ordering only. Explanations say
"policy-compatible hint", never "greener/better". No power
control, no shutdown, no autonomous energy decisions.

## Chat / missions

Assignment responses and task detail carry the routing
decision, so chat can say: "Ik stuur deze taak naar node X
omdat die de vereiste camera- en VLM-capabilities heeft."
Descriptive only — chat cannot pick node IDs to bypass
routing; explicit selection stays on the assign endpoint.

## UI

Dashboard nodes table shows derived status (incl. stale),
capability/model/executor counts. Detail lives in JSON
(`GET /api/v1/nodes`, `/api/v1/nodes/{id}`).

## Security model

Unknown/disabled/unauthenticated/stale nodes refused;
wildcards, paths, commands and URLs refused at every
boundary; credentials never logged/returned; identity bound
to tokens; lease ownership enforced; physical work never
auto-reroutes; fingerprints still gate approvals and
artifacts. No cloud fallback, no public bind, no open ports,
no inbound connections, no privilege escalation.

## Limitations (honest)

- Token auth is bearer-on-LAN, not PKI; no rotation protocol
  beyond re-register; legacy mode exists for compatibility.
- No encrypted transport; loopback-only by default.
- Locality labels are policy hints, not topology proof.
- Energy hints are self-reported, not measured.
- Simulated nodes (`sim_nodes.py`) test orchestration only.
