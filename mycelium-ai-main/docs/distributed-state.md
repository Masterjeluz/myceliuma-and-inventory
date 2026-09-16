# Distributed State (BIG #10)

Event/change-log-synchronisatie tussen coordinator-instanties.
**Nooit een DB-kopie**: alleen gevalideerde enveloppen gaan over
de lijn, via HTTP-pull, begrensd en idempotent.

```
lokale wijziging → DistEnvelope (dsevt_-id, revisie, epoch)
        ↓  append (durable log, dist_events)
pull: GET /api/v1/sync/changes?after=&limit= (≤100/page)
        ↓  apply_pulled: validate → idempotent apply
duplicaat → acknowledged (geen dubbele toepassing)
conflict  → expliciet record (dscon_-id, status open) — nooit
            stil gemerged, nooit last-write-wins
```

## Regels

- Envelop-ID's zijn `dsevt_`-prefixed; revisies zijn opaque
  strings die alleen op (on)gelijkheid worden vergeleken.
- Payloads: ≤20 keys, waarden ≤2000 tekens, alleen
  str/int/float/bool/None/list/dict. Sleutels als
  `command`, `shell`, `exec`, `script`, `sql`, `eval`
  weigeren — bij constructie én bij apply (pull-path
  omzeilt de constructor).
- `mergeable_update` kent een kleine allow-list voor
  technische metadata; alles daarbuiten bij gelijke
  basis-revisie → conflict, beide versies bewaard.
- Conflicten lossen alleen expliciet op
  (`POST /api/v1/dist/conflicts/{id}/resolve`); oplossen
  herschrijft geen versies, het markeert alleen.
- Cursor advancing: alleen applied/duplicates schuiven de
  cursor op; conflicts houden hun cursor voor review,
  failed items nooit.

## INVENTory-koppeling

Eén richting, read-only, over HTTP:
`GET /api/v1/inventory/changes?since=&limit=` leest de
INVENTory-eventlog via de bestaande bridge
(`events_since`), nooit het SQLite-bestand. INVENTory
kreeg daarvoor één additieve cursor:
`GET /api/v1/events?since=<ISO-timestamp>&limit=` (clamp
1..500). Geen dumps, geen SQL aan de buitenkant.
