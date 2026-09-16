# Memory (BIG #11-15, Phase 1) — IMPLEMENTED

Ten typed memories over the event/state architecture, never
one text blob: fact, episodic, project, preference, skill,
health, observation, research, relationship, derived.

## Truth tiers

`user_fact > verified > observed > external_source >
ai_inference > ai_suggestion`. AI output enters at the
bottom and never auto-promotes: `verify_memory` needs a
human approver plus human_verified provenance. Deletion is
a tombstone (row + links preserved).

## Retrieval

Lexical + recency + importance + project relevance, with an
optional semantic re-rank over the shortlist through the
existing Ollama embedding provider (lexical stays the
fallback; no second search engine). Bounded, budgeted.

## Consolidation — PARTIAL (proposal only)

`propose_consolidation` returns candidates + dedup count +
structural contradiction flags and stores nothing.
Contradictions stay side by side for human review. The
periodic scheduled run exists as a job (`memory_
consolidation`) but proposes; automatic merging is FUTURE
and must keep the no-silent-overwrite rule.
