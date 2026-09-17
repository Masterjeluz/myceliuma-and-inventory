# Research runbook (BIG #29)

## Ask from chat

"Onderzoek mijn camper." → RESEARCH_STARTED + mission
(pending YES). Approve → run ticks → dossier → memory →
morning. "Wat heb je gevonden?" → morning Research section.

## Run directly (API)

```powershell
# Wikipedia attempt (REAL when reachable, else UNAVAILABLE)
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/research/runs `
  -ContentType "application/json" `
  -Body '{"question":"Onderhoud camper distributieriem"}'

# Explicit URLs (REAL direct fetch, hardened)
... -Body '{"question":"...","source_urls":["https://example.com/..."]}'

# Fixtures (TEST label end to end)
... -Body '{"question":"...","provider":"test",
  "test_pages":{"camper":["Titel","Tekst met feiten."]}}'

# Draft first, execute later
... -Body '{"question":"...","execute":false}'
Invoke-RestMethod -Method Post .../research/runs/{res_id}/execute `
  -Body '{"provider":"test","test_pages":{...}}'
```

## Inspect

- `GET /api/v1/research/runs` / `/runs/{id}` (counts included)
- `GET /api/v1/research/dossiers` / `/dossiers/{id}`
- Pages: `/research` (workshop), `/research/{dossier_id}`
  (dossier), `/world?show=missions,nodes,research` (overlay),
  `/morning` (Research section).
- `GET /api/v1/research/capability?probe=true` (Ollama +
  provider states).

## States you will see

- `unavailable` + "Ik heb geen echte bronnen kunnen
  ophalen." → transport/search down. Check capability,
  retry later, or supply `source_urls`.
- `blocked` → sources fetched but unusable, or budgets hit;
  `error` names the cause.
- `completed` + `execution_state` REAL/TEST → dossier +
  memory stored. Synthesis section says EXTRACTIE when the
  model was down — that is honest, not broken.

## Autonomous research

Research missions may run overnight: bounded (≤6 sources,
≤200KB, ≤300s, retries → REPLAN/BLOCKED), read-only,
no credentials, no approvals issued. Without transport
they end WAITING/UNAVAILABLE — never fake findings.
Bootstrap research missions stay template-based; web runs
start from explicit questions or approved research steps.

## Troubleshooting

- `422 Unknown research provider` → use
  wikipedia|test|unavailable.
- `422 provider 'test' needs test_pages` → supply fixtures.
- `409 Run is completed` → runs execute once; open a new
  run for a fresh question.
- Empty claims → sources too thin: sharper question,
  more/better URLs, then re-run.
- Contradictions listed as unresolved is correct behavior —
  Mycelium reports "A says X while B says Y", never
  arbitrates truth itself.
