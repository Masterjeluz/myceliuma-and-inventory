# Mycelium Live (BIG #10)

Capability-scoped Live-sessies: een begrensde, vervallende
context-bundel voor een interface (web/telefoon), met
minimale rechten. Lezen via sessie, muteren alleen via de
bestaande approval-flows.

```
POST /api/v1/live/sessions {interface, actor,
  capabilities[], context_scope{}, ttl} → live-*-sessie
POST /api/v1/live/context {session_id, query, budget,
  entity_id} → bounded package (sections + used ≤ budget)
POST /api/v1/live/propose {session_id, kind, ...} →
  capability-check, daarna bestaande proposal-flow
```

## Regels

- Capabilities zijn een gesloten allow-list (`task.read`,
  `node.read`, `git.read`, `git.commit`, ...). Onbekende
  capabilities weigeren bij het openen; `git.push` bestaat
  niet en wordt nooit verleend.
- Sessies vervallen (TTL, default 1u, max 24u) en zijn
  herroepbaar; verlopen/herroepen → 403, onbekend → 404.
- Context is begrensd per sectie (taken/nodes/observaties/
  events, elk ≤20 items, korte velden) en past binnen het
  budget; `used` wordt gerapporteerd.
- `git.commit ≠ git.push`: een commit-voorstel via Live
  landt in de bestaande git-proposal-flow (mens keurt
  goed); pushen kan via geen enkele sessie.
- Watcher (`GET /api/v1/watcher/scan`) levert alleen
  findings (stale taken, stille nodes, project-signalen) —
  nooit executie, nooit writes.
- Morning report (`GET /api/v1/reports/morning`) is
  deterministisch: zelfde inputs, zelfde secties; tellen
  en korte regels, nooit dumps.

## BIG #11-15: universele interface (PARTIAL)

Live ontsluit nu ook memory, health, research, skills,
workshop, fabrication, twin en watcher-findings — elke
sectie achter een eigen capability
(`memory.read`, `health.read`, `research.read`,
`skills.read`, `workshop.read`, `fabrication.read`,
`twin.read`, `watcher.read`). Health vereist bovendien
een expliciete `include_health`-scope; zonder die vlag
komt er geen enkele gezondheidsbyte in het pakket.
Voorstel-capabilities (`3d.propose_transform`,
`research.propose`, …) blijven inert tot de bestaande
approval-flow ze oppakt. Volledige spraak-/actie-
dekking van alle Live-commando's is FUTURE; elke actie
blijft door capability/proposal/approval gaan.
