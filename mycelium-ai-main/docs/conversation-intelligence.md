# Conversation Intelligence (BIG #37)

Conversations are traces of thought. Mycelium reads them as
structure — themes, decisions, promises, contradictions,
missed items, research questions, entity links, possible
symbioses — and routes everything through the existing
truth flow. Analysis is OBSERVATION or CANDIDATE, never
fact. Jelles decides.

## Pipeline (no second import system)

IMPORT (bridge) → NORMALIZE → SEGMENT → THEMES →
DECISIONS → PROMISES → QUESTIONS → CONTRADICTIONS →
MISSED → RESEARCH → ENTITY LINKS → SYMBIOSIS → HUMAN
REVIEW → ECOSYSTEM. All computation is deterministic and
extractive (`method: extractive-local`, no LLM involved),
stored as `conversation_intel` records keyed by sha256
fingerprint for cross-conversation dedupe.

## What each layer yields

- **Themes**: term frequency over content words (NL/EN
  stopwords), supporting messages, related entity mentions
  and inventory projects, heuristic confidence. OBSERVATION.
- **Decisions**: decision-marker findings with confidence
  (explicit markers = high), resolution UNRESOLVED.
  CONFIRM/REJECT/IGNORE run through candidate
  support/promote/reject — never silent truth.
- **Promises**: commitment markers with owner from role
  only (`user` → Jelles, else assistant — never invented
  names). Status UNKNOWN unless a mission/event mentions
  the same terms (then IN_PROGRESS with evidence).
  Completion is never claimed from mere mention.
- **Contradictions**: A/B sides with sources, status
  UNRESOLVED. No winner is picked; humans resolve via the
  knowledge flow.
- **Missed items**: bridge findings mapped to categories
  (PROJECT/TASK/QUESTION/RESEARCH/RELATIONSHIP/OBJECT/
  MATERIAL/MACHINE/DOCUMENTATION/DECISION/PROMISE/RISK/
  DEPENDENCY), each with evidence.
- **Research proposals**: open/investigative statements
  become question candidates plus queue-ready payloads; the
  RESEARCH button posts to the existing research queue
  (draft runs — execution still needs a mission YES).
- **Entity links**: entity mentions matched against a
  bounded inventory browse → LINK CANDIDATE connection
  candidates. Never silent merges.
- **Symbiosis**: co-mentioned entities/projects →
  PROPOSED connection candidates for the guarded YES flow.

## Materialize (explicit, idempotent)

`materialize(conversation_id, fingerprint, action)` with
actions `candidate` | `research-queue` | `link`. Replay
returns `already-materialized`. Health-flagged text
refuses. Wrong kind/action combinations refuse.

## Cross-conversation reasoning

`cross_conversation()` aggregates by fingerprint (no
duplicate observations), surfaces repeated themes, and
flags REVISIT observations when a theme recurs across
imports without mission/event progress. Timeline orders
intel by message index with real import stamps; unknown
stays unknown.

## Truth model + security

Imported content is untrusted: escaped data at render,
health-isolated, secrets redacted at import, oversized and
duplicate imports refused, fake IDs 404/422. Nothing
imported can approve, execute, verify, or change truth
tiers. No shell/RCE/eval; no URLs fetched; no credentials.

## UI + ecosystem wiring

- `/conversations` is the AI ARCHIVE (recent, themes,
  threads, decisions/promises, contradictions, missed,
  research, project links).
- Detail pages show every section with materialize buttons,
  a DISCOVERY banner (real unmaterialized counts), timeline,
  and the existing continue-elsewhere packet links.
- Packets carry an optional `intelligence` section
  (bounded, no history dumps).
- World graph gains an `intel` overlay (opt-in flag,
  dashed provenance, filterable).
- Guide, mobile Threads, and IN_APP notifications
  (`conversation_analyzed`) surface intel; craft and
  symbiosis consume materialized candidates.
