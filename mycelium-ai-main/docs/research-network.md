# Research network & capability honesty

Research missions are read-only plans (readout + analysis
steps from the existing safe templates). They run only when a
real transport exists — otherwise they wait, honestly.

## Capability status

`GET /api/v1/research/capability` reports the local analysis
transport (`ollama`, base URL, model) as `unprobed` until you
ask for `?probe=true`, which runs one tiny bounded (10s)
local-model call. States: `true` (model answers), `false`
(unreachable, with reason), `unprobed`.

Rule: **no probe, no claim.** A bootstrap mission that cannot
run reports `WAITING_FOR_RESEARCH_CAPABILITY` (via the normal
waiting machinery) instead of pretending research happened.
Every external claim needs source provenance (`research.py`:
sources → claims → records, confidence-labelled); uncited
claims never promote to `user_fact`.

## Result model

Each research mission records: project, question, scope,
sources, findings, claims, confidence, provenance, date,
follow-ups. Results distinguish FACT / OBSERVATION /
EXTERNAL_SOURCE / AI_INFERENCE / AI_SUGGESTION. Follow-up
missions are proposed as candidates, never auto-executed.

## Research nodes (future)

A node may advertise a `research` capability through the
existing distributed queue, but jobs stay structured
(`ResearchTask`: question, scope, sources, max_results,
allowed_domains, time_limit). No arbitrary code, no shell, no
arbitrary URLs — the coordinator stays the authority that
validates every result before it lands in memory.
