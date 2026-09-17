# Research Engine (BIG #29)

Mycelium's first real sense: question → dossier, read-only by
default, inside the existing FACT → OBSERVATION → ADVICE →
PROPOSAL → APPROVAL → TASK → RESULT → VERIFICATION chain.

```
vraag → queries → search → fetch → extract → claims →
tegenstrijdigheden → Ollama-synthesis → dossier →
provenance → research memory → morning / UI / chat
```

## Entities

- `res_…` run: question, objective, status
  (draft/collecting/extracting/synthesizing/completed/blocked/
  failed/cancelled/unavailable), execution_state
  (REAL/TEST/UNAVAILABLE), queries (`que_…`), sources, claims
  (`clm_…`), contradictions, open questions, linked entities,
  context_used, dossier/memory links, provenance, budgets.
- `src_…` sources: existing `research.py` SourceRecord
  (hash dedup, stage machine, provenance). Engine metadata
  (url, execution_state, provider, injection flags) rides in
  the run record.
- `clm_…` claims: text, type, one stored source, exact
  evidence (passage ordinal), extraction method, execution
  state, truth tier (max external_source).
- `dos_…` dossier: summary, key findings (SOURCE/INFERENCE
  labelled), claims, source evidence, contradictions,
  open questions, related entities, generated_by,
  synthesis_available flag, provenance.
- `que_…` queries: deterministic shapings of the question.

Storage: `research_runs` + `research_dossiers` tables in the
chat/agent database (same additive discipline as missions).
Claims additionally mirror into `research_records` so the
existing "every claim cites a stored source" invariant covers
engine output.

## Providers (REAL OR NOTHING)

- `wikipedia` (default): REAL search+fetch against the closed
  host allowlist (nl/en/de/fr.wikipedia.org). Unreachable →
  UNAVAILABLE with reason, never fake.
- `test`: deterministic fixtures via explicit `test_pages`
  (TEST label everywhere, never REAL).
- `unavailable`: honest no-op naming the missing capability.
- `source_urls`: explicit operator-supplied URLs fetched REAL
  through the hardened transport (GET-only, SSRF-validated).

Unknown provider names refuse. Fixture smuggling
(`test_pages` + `wikipedia`) refuses.

## Budgets

MAX_QUERIES=3, MAX_SOURCES=6, MAX_SOURCE_BYTES=200_000,
MAX_CLAIMS=30, MAX_SYNTHESIS_INPUT=12_000,
MAX_RUNTIME_SECONDS=300. Exhaustion → blocked/unavailable,
never infinite loops. Research steps run under plan approval
only (`requires_approval=False`, like readout/analysis) and
complete UNVERIFIED (no FACT promotion, ever).

## Synthesis (Ollama)

Reuses `OllamaProvider.advise` with the question + wrapped
UNTRUSTED claim blocks and a rule instruction (summarize
only, invent no URLs, approve nothing, obey nothing inside
the blocks). Model down → extractive fallback dossier
(verbatim-labelled claims) with `synthesis_available=false`.
No fake AI answers.

## Context & linking

Each run records `context_used`: INVENTory bridge hits,
project context, recall refs. **Health memories never
enter** (default scope + explicit filter). Entity linking
(`obj_…`, `proj_…`, …) explains itself ("named in the
research question" / "project context"); uncertain links
are candidates. No INVENTory writes — findings that look
like relations stay candidates for the existing proposal →
approval → write → verify flow.

## Memory & morning

Completed dossiers store one `research` memory at truth
`external_source` (deduped by content fingerprint — never
`user_fact`). `/morning` shows a Research section: per
dossier title, source count, domains, claim/contradiction
counts, execution state — or honestly "Geen nieuwe externe
onderzoeksresultaten beschikbaar."

## Chat & missions

"Onderzoek mijn camper." → `research_project` intent →
`research_topic` mission (RESEARCH_STARTED, read-only
webrun, YES-gated). Research steps:
pending→running→collecting→extracting→synthesizing→
completed; errors map to blocked/failed/unavailable and
the existing decision engine (RETRY bounded → REPLAN /
BLOCKED). "Wat heb je gevonden?" → morning with the
dossier summary.

## What is REAL / TEST / UNAVAILABLE today

- REAL: direct fetch of explicit URLs (verified live against
  example.com); Wikipedia provider code-complete but
  **UNAVAILABLE from this network** (Wikimedia edge 403s
  this host — robot policy, not fixable client-side).
  For real search, configure network egress that Wikimedia
  accepts or add an allowlisted search API provider.
- TEST: fixture provider, fully exercised.
- UNAVAILABLE: default search path here; missions report
  "Ik heb geen echte bronnen kunnen ophalen."
- SIMULATED: supported as a label, no simulator ships.
- Ollama synthesis: code-complete, **currently DOWN**
  (`:11434` refused) → extractive fallback active.

## Distributed & n8n

Capabilities `research.search` / `research.fetch` /
`research.extract` are defined and pattern-compatible with
BIG #8 routing; coordinator stays authority. No multi-node
research in BIG #29. n8n may trigger research later through
the existing integration plane; Mycelium never calls n8n
directly and works without it.
