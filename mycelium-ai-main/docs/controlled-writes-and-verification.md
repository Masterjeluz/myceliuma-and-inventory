# Controlled Writes & Verification (BIG #5)

Hoe Mycelium de wereld mag veranderen — en hoe het bewijst dat
het gebeurd is. Eén keten, geen shortcuts:

```
FACT / OBSERVATION
        ↓
ADVICE
        ↓
PROPOSAL        (inert, gevalideerd, nooit automatisch waar)
        ↓
APPROVAL        ("de mens staat deze actie toe" — exact YES)
        ↓
CONTROLLED ACTION / WRITE   (allow-list, revalidatie, before/after)
        ↓
RESULT          (executed/failed/blocked — nooit automatisch verified)
        ↓
VERIFICATION    (onafhankelijke readback: passed/failed/inconclusive)
        ↓
WORLD MODEL UPDATE  (alleen passed telt als geverifieerd)
```

## Approval ≠ verification

|                      | APPROVAL                          | VERIFICATION                              |
|----------------------|-----------------------------------|-------------------------------------------|
| Vraag                | Mag deze actie plaatsvinden?      | Is het verwachte resultaat ontstaan?      |
| Wie                  | Mens (exact `YES`)                | Onafhankelijke readback (+ eventueel mens)|
| Wanneer              | Vóór uitvoering                   | Na uitvoering                             |
| Zet `human_verified` | Nooit                             | Nooit automatisch (alleen echte menselijke verificatie) |
| Herbruikbaar         | Nee (binding op exacte inhoud)    | Nee (binding op exact resultaat)          |

Een approval zet nooit `human_verified=true`. Een geslaagde
mutatie betekent nooit `verified=true`. `human_verified=True`
komt uitsluitend uit een menselijke handeling of een
INVENTory-rij die al zo was opgeslagen — nooit uit AI-output.

## Controlled-write laag (`controlled_writes.py`)

Generiek en domein-onafhankelijk. Gesloten mutatietypen:

- `inventory.create`, `inventory.update`,
  `inventory.create_relationship`
- `git.commit`

Vrije SQL, shell, code en arbitraire HTTP-writes zijn hierin
niet uit te drukken. Elk voorstel draagt type, target, payload,
provenance (`human_verified=False`), actor en timestamps, plus
een sha256-fingerprint over de canonieke inhoud. Voorstellen
verlopen na 1 uur (staleness). Uitvoerders roepen `revalidate()`
direct vóór het handelen aan: verkeerde binding, gewijzigde
inhoud of verlopen voorstel weigert fail-closed.

## INVENTory writes (`inventory_writes.py`)

De enige schrijfweg naar INVENTory; de read-bridge
(`inventory_read.py`) blijft GET-only en onaangeroerd. Alleen
`object`/`project`/`idea` (create/update) en relaties — de
entiteiten waarvan de API/database-semantiek is geverifieerd
tegen `inventory/app/main.py` + `schemas.py`. Deletes, events
en M3+-typen weigeren (fail-closed, geen gokken over schema's).

Per mutatie: loopback-only POST/PATCH (timeout ≤ 5s, geen
redirects), onbekende velden/enums geweigerd,
`human_verified=True` uit AI-output geweigerd, `before`/`after`
via onafhankelijke reads. Capabilities in bestaande
punt-notatie: `inventory.objects.write`,
`inventory.projects.write`, `inventory.ideas.write`,
`inventory.relationships.write`.

## Verification (`verification.py`)

Eersteklas abstractie: `VerificationRequest` (wat werd
verwacht, methode, binding op resultaat) → `VerificationResult`
(wat werd geobserveerd, OBSERVED vs INFERRED, methode, bron,
timestamp, provenance). Methoden: `inventory.readback`,
`inventory.graph_readback`, `git.readback`.

- `passed` — onafhankelijke readback komt overeen.
- `failed` — uitgevoerd maar wereld komt niet overeen → NIET
  geverifieerd, geen FACT-promotie.
- `inconclusive` — wereld onleesbaar → NIET geverifieerd.

Alleen `outcome == "passed"` telt (`is_verified()`). Het
resultaat-payload wordt nooit vertrouwd: er wordt altijd
opnieuw gelezen. Een model-analyse mag in `inferred` als
label, maar beslist nooit.

## Git capability (`git_commit.py`)

Eén schrijfbewerking naast de read-only `git_context.py`:
commit aanmaken. Geen push/fetch/force/checkout/merge, geen
shell (alleen vaste argv, `shell=False`, 10s timeout), geen
credentials. Repository moet op de operator-allow-list
(`MYCELIUM_GIT_WRITE_REPOS`; leeg = alles weigert). Checks:
branch, `expected_head`, file-allow-list zonder traversal,
géén onverwachte worktree-wijzigingen (BLOCK bij verschil).
Verificatie leest HEAD/parent/branch terug — een returncode
alleen verifieert nooit. Capability: `git.write.commit`.

## Project-aware context (`project_package.py`)

`GET /api/v1/project/package?q=…` geeft een begrensd,
alleen-lezen pakket: project-identiteit, ≤ 10 entiteiten
(hybride retrieval met lexicale fallback), ≤ 5 missies, ≤ 10
events, git-status zonder diff-inhoud, bestandsnamen zonder
inhoud. Geen secrets, absolute paden geredigeerd naar
`$PROJECT`/`$HOME`, provenance behouden. Het pakket is context,
nooit toestemming. Missies uit chat krijgen één
project-identiteitsrecord als context mee.

## Missie-integratie

Nieuwe stap-soort `write` (naast readout/desktop/analysis/
proposal): bindt aan exact één write-`proposal_id`, draagt
geen eigen approval (die leeft op het write-voorstel zelf) en
voert nooit zelf uit — de geïnjecteerde `run_write`-capability
doet voorstel → approval-check → uitvoering → verificatie.
Zonder gekoppelde capability BLOCKt de stap. Nieuwe events:
`write_proposed/approved/executed/result` en
`verification_started/passed/failed`.

## API

- `POST /api/v1/writes/inventory` — voorstel (inert)
- `POST /api/v1/writes/git-commit` — voorstel (inert)
- `GET /api/v1/writes/{id}` — voorstel + fingerprint + status
- `POST /api/v1/writes/{id}/approve` — exact YES/NO (eenmalig)
- `POST /api/v1/writes/{id}/execute` — revalidatie + uitvoering
- `POST /api/v1/writes/{id}/verify` — onafhankelijke verificatie
- `GET /api/v1/project/package` — bounded project-context

## Vision-keten (BIG #6)

Vision-voorstellen (`POST /api/v1/vision/propose`) landen als
inerte records in dezelfde store en volgen exact dezelfde
approve/execute/verify-routes hierboven — er bestaat geen
apart vision-schrijfpad. File-media registreert via
`inventory.create`/`file` met dezelfde binding en readback
(methode `inventory.readback`). Observatie-verificatie
(`camera.readback`) bevestigt het capture-record, nooit de
afgebeelde identiteit. Zie `docs/vision-architecture.md`.

## Security-regels (getest in `test_write_security.py`)

Geen shell/RCE · geen SQL · geen directe DB-writes (alleen
HTTP) · geen push/force · geen credential-handling · AI kan
geen `human_verified` zetten · approval ≠ verified · staleness
en fingerprint-mismatch blokkeren · onverwachte Git-changes
blokkeren · verificatie niet te smeden via resultaat-payload.
