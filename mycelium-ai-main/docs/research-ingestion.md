# Research + Ingestion (BIG #11-15, Phase 3) — IMPLEMENTED

Generic pipeline: SOURCE → FETCH → EXTRACT → NORMALIZE →
UNDERSTAND → DEDUPLICATE → RELATE → PROPOSE → APPROVE →
STORE. Sources are adapters (web, GitHub, YouTube,
document, image, camera, RSS, social, Instagram,
manual-export, manual); no source writes to INVENTory
directly — storage lands in research tables or
proposal flows.

## Records

- SourceRecord: type, external id, reference, title,
  author, content (capped), sha256 content hash,
  topics/entities, staged status
  (received → extracted → proposed → approved →
  stored), provenance, captured/published dates.
- Content hashes deduplicate; stages advance one step
  at a time; `approved`/`stored` need a human approver.
- ResearchRecord: QUESTION → cited claims → synthesis.
  Every claim cites ≥1 stored source with evidence,
  confidence and interpretation. Uncited claims refuse.
  Synthesis is labelled interpretation, never fact.

## Instagram — manual-export only (live UNAVAILABLE)

No scraping, no credential use, no session bypass. The
adapter maps user-owned manual exports (collections,
captions, topics, creators) to source records with
`manual-export:` references; references in any other
shape refuse. A deterministic mock export serves
tests/dev, labelled mock everywhere. Related entities
(projects, ideas, skills, topics, recipes, people,
technologies) attach via topics/entities fields.
