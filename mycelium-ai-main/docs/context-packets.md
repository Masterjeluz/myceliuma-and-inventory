# Context Packets (BIG #31: v2 handoff schema)

Mycelium owns state and provenance. External models (ChatGPT,
Claude, Gemini, Codex, OpenCode, Ollama, Google AI Studio,
Antigravity) are advisors — never the database.

## Versions

- v1 (`mycelium-context-packet/1`): goal, project, entities,
  memories, missions, research, constraints, provenance, system
  state. Markdown + JSON. Unchanged, still served.
- v2 (`mycelium-context-packet/2`): everything in v1 (via the
  context engine: bounded, scored, traceable sections) plus
  `task`, `intent`, `current_state` (living state), `decisions`,
  `unresolved_questions`, `suggested_next_actions`, `timestamps`,
  `source_references`, `mycelium_state`, `continuation_instructions`.

## Endpoints

- `GET /api/v1/context/packet` — v1 JSON (unchanged).
- `GET /api/v1/context/packet2` — v2 JSON, or
  `?format=markdown` for text.
- `GET /api/v1/context/packet.md` — v2 Markdown as download
  (`mycelium-context.md`).
- `GET /api/v1/context/continue` — continuation handoff (v1 shape,
  unchanged).

Health stays scoped out unless `include_health=true`. No secrets
ever enter a packet (import redaction happens at the bridge).

## Continue elsewhere

Conversation detail pages render a working **Copy context
(Markdown)** button (clipboard via fetch, honest fallback to the
link), plus download/markdown/relevance links. `/mobile` links the
same download. Flow: packet out → any model → answer back in via
`/conversations` import → analysis → candidates → (human) → memory.
