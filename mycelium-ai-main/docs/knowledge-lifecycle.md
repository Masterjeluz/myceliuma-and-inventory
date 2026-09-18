# Knowledge Lifecycle (BIG #32)

Information matures visibly instead of appearing as fact:

OBSERVATION → CANDIDATE → SUPPORTED → PROMOTED MEMORY
(and REJECTED as an explicit terminal state).

## Store

`coordinator/app/knowledge.py`, table `knowledge_candidates`
(additive). IDs `cand_...`. Types: idea, observation, claim,
question, connection, task, note. States: observation,
candidate, supported, promoted, rejected.

No numeric confidence is invented: support is a count of
distinct supporters/sources, shown as-is (`♥ n`).

## Intake (all provenance-backed, health refuses)

- Conversation finding → candidate (`POST
  /api/v1/conversation-imports/{id}/findings/{i}/candidate`,
  "Remember as candidate" buttons, `candidate_from_finding()`).
  Health-flagged text refuses — health stays scoped.
- Research open question → candidate (dossier buttons,
  `POST /api/v1/research/dossiers/{id}/questions/{i}/candidate`).
- Camera observation → candidate ("Review as candidate" buttons,
  `POST /api/v1/observations/{id}/candidate` and
  `/web/observations/{id}/candidate`).
- Manual: `/knowledge` form, mobile "Remember this",
  `POST /api/v1/candidates`.

## Support

`POST /api/v1/candidates/{id}/support {supporter, rationale}`.
Same supporter twice is a no-op. Two distinct supporters move
observation/candidate → supported. Terminal states refuse.

## Promotion (explicit, conflict-safe, idempotent)

`POST /api/v1/candidates/{id}/promote {truth?, verified_by?,
importance?}`:

- Default truth per type (observation→observed,
  claim/connection→ai_inference, rest→ai_suggestion).
- Fact tiers (`verified`, `user_fact`) require `verified_by` (a
  human) and go through `verify_memory()` semantics.
- Overlapping `verified`/`user_fact` memories refuse with the
  conflict list — never overwritten.
- Provenance, source refs, evidence, counter-evidence,
  contradictions and origin survive in the memory
  (`data.origin`, `derived_from=[candidate_id]`).
- Idempotent: re-promoting returns the existing memory
  (`deduped: true`); fingerprint dedupe included.
- Revision fencing on every mutation (`expected_revision`).
- Emits `candidate.promoted` (also `.supported`, `.observed`,
  `.rejected`); visible in `/activity` and the morning.

The AI may recommend promotion. The human remains authority.

## UI

`/knowledge`: pipeline counts, filters (state/type), candidate
cards (title, summary, type, provenance, sources, evidence,
counter-evidence, entities, origin, supporters, truth, next
action) with Inspect (card) / Find evidence (search link) /
Research (queue) / Link (writes) / Promote / Reject / Keep.
Empty state explains the lifecycle with actions.
