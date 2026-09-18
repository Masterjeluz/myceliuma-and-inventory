# Conversation Bridge (BIG #30)

External conversations come IN; universal context goes OUT. Both
directions are model-agnostic (no platform lock-in).

## Import (conversation_bridge.py)

Supported: pasted text, TXT, Markdown, JSON (`messages/turns/
conversation` lists with `role/content`), safe HTML export
(stripped to text — no scripts, forms, or `javascript:` URLs).

`POST /api/v1/conversations/import` (`routes_conversations.py`,
also mounted in `main.py`) stores:

- `conv_...` id, `source_platform` (any `[A-Za-z0-9 _.-]{1,40}` —
  `chatgpt/codex/opencode/ollama/claude/gemini/google-ai-studio/
  antigravity/chatgpt-live/other` suggested), `imported_at`, title,
  participants, `message_count`, sha256 `content_hash` (exact
  re-import refused as duplicate), `execution_state=IMPORTED`,
  provenance `imported / human_verified=false`.

Limits: raw ≤ 200k chars, ≤ 200 messages, each ≤ 4000 chars
(longer turns are split, never dropped silently).

## Analysis (deterministic, no LLM)

`POST /api/v1/conversations/{id}/analyze` extracts ideas, decisions,
open questions, TODOs, project mentions, people/orgs (heuristic),
technical claims, proposed actions, source references (URLs noted,
NEVER fetched), repeated topics, possible contradictions.

Every finding carries `state` (OBSERVATION or CANDIDATE), message
index/id/role, and an `evidence` quote. Nothing is stored as fact;
promotion to memory uses the existing `memory.py` truth-tier flow.

## What did we miss?

`GET /api/v1/conversations/{id}/missed` returns only evidence-backed
suggestions (unlinked topic, idea without task, claim without source,
inventory gap, 3D-workflow gap, open question). Each references the
conversation/message/entity/evidence it came from.

## Context packets (context_packet.py)

`GET/POST /api/v1/context/packet` builds the portable packet: goal,
project, entity IDs (they persist across models; prose drifts),
memories (health scoped OUT unless `include_health=true`), open
missions, research dossiers, conversation excerpt, files, constraints,
provenance, live system state. Rendered as Markdown + JSON metadata.

`GET /api/v1/context/continue` builds the "Continue this work"
handoff: CURRENT STATE / DONE / IN PROGRESS / REMAINS / DECISIONS /
ENTITIES / NEXT STEP + USER MESSAGE block to paste into any model.

## Archaeology depth (BIG #31)

- `GET /api/v1/imports-compare` — repeated topics across imports
  (evidence per conversation/message), shared platforms, shared
  entity candidates.
- `GET /api/v1/conversation-imports/{id}/relevance` — read-only
  bridge search over finding keywords → CANDIDATE links to
  existing INVENTory records (creating relations needs a write
  proposal + YES).
- `GET /api/v1/discoveries` — "Te tonen aan Jelles": missed items
  + open research questions across imports, surfaced on
  `/conversations` and `/morning`.
- `GET /api/v1/conversation-imports/{id}/markdown` — the import as
  portable Markdown (open/download elsewhere).

## Findings become candidates (BIG #32)

`POST /api/v1/conversation-imports/{id}/findings/{i}/candidate`
(and "Remember as candidate" buttons) turn one finding into a
knowledge candidate with provenance, evidence and entity refs.
Health-flagged findings refuse. The candidate then matures
through `/knowledge`: support → promote → memory. See
`docs/knowledge-lifecycle.md`.

## Security

Imported text is data, never instructions (prompt-injection safe by
construction). Secrets (`token/bearer/api-key/...`) are redacted
before storage. Fake `xxx_...` IDs become `entity_mention`
CANDIDATES, never resolved truth. Health content is flagged and
excluded from packets unless explicitly scoped. No credentials ever
touch the database.
