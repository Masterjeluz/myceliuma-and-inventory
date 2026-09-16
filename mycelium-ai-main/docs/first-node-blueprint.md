# First Node Blueprint — eerste echte externe node (BIG #5)

Praktische blauwdruk voor de eerste node buiten de coordinator-
machine zelf (oude laptop, werkplaats-pc). Alleen wat het
huidige protocol al kan: registreren, heartbeat, pull, claim,
uitvoeren, rapporteren. Geen nieuw distributed runtime-systeem.

## Stroom (pull-only)

```
Coordinator (:8000)
    ↓  node pollt (outbound-only, geen inbound ports)
Node
    ↓  capability discovery (vrijwillig profiel + owner-capabilities)
claim (één bounded task, lease 300s, max 3 pogingen)
    ↓  revalidatie (capability-match op live data)
execute (alleen wat de taak beschrijft — nooit meer)
    ↓  result (completed/failed + observatie-referentie)
verification (coordinator/mens, los van het resultaat)
```

## Identity

- `node_id` bij registratie (`POST /api/v1/nodes/register`);
  een her-registratie met hetzelfde id upsert — gebruik bij
  twijfel over stale state een verse id (`seed-02`).
- Tier: `seed` (begin hier), later `worker`/`core`.
- Start-capability: `system_inventory` (read-only loop).
  Desktop-input weigert de node-client zonder expliciete
  menselijke approval; uitvoeren van input loopt uitsluitend
  via de standalone desktop-agent op een vertrouwde machine.

## Capabilities (geen escalatie)

- Capabilities worden door de eigenaar opgegeven, nooit door
  het netwerk verleend. Geen automatische uitbreiding: een node
  die `desktop.mouse.click` claimt zonder dat de owner het
  configureerde, krijgt geen taken (`exec:`-namespace,
  exacte match).
- Model-routing via capability-matching (`capability_matching.py`);
  twijfel = deny.

## Heartbeat & freshness

- Heartbeat (`POST /api/v1/nodes/{id}/heartbeat`); poll elke ~5s.
- Stale-grens 60s (`NODE_STALE_SECONDS`): oudere nodes gelden
  als offline en krijgen geen claims.
- Taken: lease 300s (`LEASE_SECONDS`), max 3 pogingen
  (`MAX_ATTEMPTS`); verlopen leases vallen terug in de queue.

## Claims & revalidatie

- Claim (`POST /api/v1/tasks/claim/{node_id}`) is atomair;
  staged proposal-taken zijn onbereikbaar voor claims (alleen
  `queued` claimt).
- Vóór uitvoering: capability-snapshot moet gelijk zijn aan de
  goedgekeurde snapshot (promotion-poort); verschil = deny.
- Resultaat (`POST /api/v1/tasks/{id}/complete`) is een
  observatie, geen waarheid — verificatie gebeurt apart
  (BIG #5: readback, geen model-mening).

## Provenance & failure

- Elke taak draagt provenance; `ai-generated` wordt nooit
  automatisch `human_verified`.
- Failure-semantiek: completed/failed/cancelled/blocked met
  timing en error. Gefaalde pogingen tellen op tot het maximum;
  daarna menselijke review, geen stille retry.
- Stale nodes: hun leases verlopen, hun taken worden opnieuw
  verdeeld, hun oude registratie blijft zichtbaar als offline.

## Harde grenzen voor de eerste node

- Geen inbound ports op de node (alleen outbound polls).
- Geen arbitrary shell, geen arbitraire code-uitvoering.
- Geen credential-opslag op de node.
- Geen push/merge/commit via de node (git writes alleen via
  de gecontroleerde coordinator-capability met allow-list).
- Geen automatische capability-escalatie.
- Cloud is additief, nooit vereist; LAN volstaat.

## Startcommando's

Coordinator eerst, daarna de node (twee terminals):

```powershell
python -m uvicorn coordinator.app.main:app --host 127.0.0.1 --port 8000
python -m node_client.main --coordinator http://127.0.0.1:8000 --node-id seed-01 --tier seed --capability system_inventory --poll-seconds 5
```

Zichtbaar in de UI onder Nodes als `seed-01`/`seed`/`online`
na enkele seconden. Lukt dat, dan werkt de basis; alles
daarna (writes, missies, verificatie) loopt via dezelfde
voorstel → approval → uitvoering → verificatie-keten.
