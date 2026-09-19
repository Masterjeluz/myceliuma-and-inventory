# BIG #37 — eindrapport

## 1. Status

DONE — built, tested, smoked, screenshotted, documented,
committed, pushed.

## 2. Commit SHA

`BIG #37 - build conversation intelligence` (SHA verified
against remote HEAD after push; see git log).

## 3. Files changed

New: `coordinator/app/conversation_intel.py`,
`tests/test_big37_conversation_intel.py`,
`scripts/b37_smoke.py`, `docs/r37-shots/` (6 PNGs),
`docs/conversation-intelligence.md`,
`docs/BIG37-final-report.md` (this file). Extended:
`coordinator/app/main.py` (7 API + 2 web routes, archive
and detail UI, mobile threads, graph flag),
`coordinator/app/worldgraph.py` (intel overlay + node
types), `coordinator/app/context_packet.py` (intelligence
section), `coordinator/app/guide.py` (intel items),
`coordinator/app/mobile.py` (intel panel),
`docs/NEXT-AI-CONTEXT.md`, `docs/ROADMAP-V2.md`.

## 4. Conversation intelligence

Deterministic extractive engine over the existing bridge:
themes, decisions, promises, contradictions, categorized
missed items, research proposals, entity links, symbiosis
discoveries — all OBSERVATION/CANDIDATE with evidence,
confidence, fingerprints; stored idempotently in an
additive `conversation_intel` table.

## 5. Themes

Term frequency with NL/EN stopwords, supporting messages,
related entities/projects, high/medium confidence. Derived
from content, never hardcoded.

## 6. Decisions

Explicit-marker confidence, UNRESOLVED resolution;
CONFIRM/REJECT/IGNORE through candidate support/promote/
reject. Tested end to end.

## 7. Promises

Role-derived owners only, UNKNOWN default, mission/event
evidence correlation (IN_PROGRESS with proof, never
claimed from mention).

## 8. Contradictions

A/B sides with sources, UNRESOLVED, no winner picked;
human resolves. Bridge findings extended with a
Dutch-aware cross-check.

## 9. Missed items

13 categories with evidence; the WHAT-DID-WE-MISS answer
stays evidence-backed and candidate-gated.

## 10. Research

Question candidates + queue-ready payloads; RESEARCH posts
to the existing queue (drafts; execution needs mission
YES). No invented findings.

## 11. Entity linking

Mentions matched over a bounded inventory browse; LINK
CANDIDATE connection candidates; never silent merges.

## 12. Symbiosis

Co-mention pairs → PROPOSED connection candidates,
visible in `/symbiosis`; guarded YES stays authoritative.

## 13. Timeline

Message-ordered with real import stamps; unknown stays
unknown. Rendered with the living timeline style.

## 14. Guide

Fresh-intel items (missed/research/contradictions),
REVISIT observations, contradiction resolution prompts —
all backed by records.

## 15. World graph

Opt-in `intel` overlay (theme/decision/promise/question/
research/candidate nodes, `surfaces` edges, dashed
provenance), filterable, off by default.

## 16. Mobile

Threads section (open threads, decisions awaiting
CONFIRM, research proposals) + quick actions (IMPORT
CHAT, WHAT DID WE MISS, OPEN THREADS, DECISIONS,
RESEARCH THIS, CONTINUE ELSEWHERE).

## 17. Packets

Optional bounded `intelligence` section in the existing
packet (counts, kinds, top items) — no v3, no dumps.

## 18. UI

Archive overview + per-conversation detail with every
section, materialize buttons, DISCOVERY banner with real
counts, timeline, existing packet links. Living SolarPunk
 styling reused; reduced-motion respected.

## 19. Security

Prompt injection, fake system/assistant messages, HTML
injection (escaped), malicious markdown, fake entity/
mission IDs, fake URLs, oversized/refused imports,
duplicate imports (content-hash refuse), conflicting
timestamps tolerated, hostile filenames, embedded
scripts, credential-like text (redacted at import,
never auto-candidated). Imported content cannot approve,
execute, verify, or change truth. Lesson: notification
`type` stores severity, not kind — assert on titles;
entity links need ≥2 valid entities for symbiosis
visibility; `list_intel` takes `limit` positionally.

## 20. Tests

New: 16 (`test_big37_conversation_intel.py`), all green.
Regression: affected suites green, 0 failures. Full suite:
1215 + 16 = 1231 collected. INVENTory: 179 + 1
pre-existing, code untouched.

## 21. Smoke

`scripts/b37_smoke.py` on tmp DBs: 17/17 OK (import
through idempotency + cross-conversation aggregate).

## 22. Screenshots

`docs/r37-shots/`: conversations-1440, conversation-detail
(Discovery, missed, analysis, themes), conversation-390,
world-conversation-overlay (intel nodes live), guide +
mobile views — Edge headless, real seed data, reviewed.

## 23. REAL / TEST / SIMULATED / UNAVAILABLE

REAL: deterministic intel, candidates, queue drafts,
links, overlay, guide, notifications. TEST: synthetic
adapters (unchanged). SIMULATED: printers (unchanged).
UNAVAILABLE: LLM enrichment (documented future), web push,
Insta360 live, native upload.

## 24. Limitations

No LLM enrichment (extractive only, labeled); theme
quality follows wording (stopword list grows empirically);
promise evidence is keyword correlation (shown as such);
overlay needs an entity focus + flag; full suite needs
batching; camera-ctypes noise pre-existing.

## 25. What Jelles can do tomorrow

Import a Claude/ChatGPT chat → Analyze intelligence →
read themes/decisions/promises/contradictions → CONFIRM a
decision, queue a research question, link an entity → watch
symbiosis, guide, craft and morning pick it up; copy the
packet (now with intelligence) to continue anywhere.

## 26. Recommended BIG #38

Living automation (observe → research → propose → act →
observe loops inside approved plans only, mission
templates chaining queue + candidates + writes, human
gates at every consequential step).
