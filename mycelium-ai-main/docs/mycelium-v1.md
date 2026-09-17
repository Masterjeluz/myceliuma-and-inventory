# Mycelium V1 (BIG #23–#28)

First genuinely usable Mycelium: open it, ask in plain Dutch,
watch it work safely until it needs you.

## What Jelles can do from the Command Center (/world)

Type plain language. Deterministic routing (never the LLM)
maps it to one brain — the existing chat endpoint — plus safe
actions:

| Say | Happens |
|---|---|
| “Onderzoek mijn camper.” | Research mission (read-only template) → pending YES → runs to next gate |
| “Kijk wat er nog openstaat voor INVENTory.” | INVENTory research mission |
| “Maak een overzicht van mijn lopende projecten.” | Project-overview mission |
| “Wat heb je vannacht gevonden?” | Morning report (did / discoveries / waiting / agenda / health) |
| “Controleer mijn openstaande missions.” | Mission cards with exact wait reasons |
| “Wat staat er vandaag op mijn agenda?” | Upcoming ICS events |
| “Stop.” | Pauses/cancels running missions safely |
| “Ga verder…” | Resumes read-only-safe missions via the bounded loop |

API twin: `POST /api/v1/command`.

## What Mycelium does automatically

Read-only plan steps (project/git/INVENTory readouts, local
analysis when Ollama answers), bounded retries with backoff,
explicit CONTINUE/RETRY/REPLAN/WAIT decisions, episodic
memories on terminal states, startup recovery scan,
research-candidate follow-ups. Morning report summarizes it
all in a warm tone.

## What still requires Jelles

Every YES: plan approval, desktop input (per action),
writes, proposals, prints, robot/drone moves, credentials,
publishing, purchases, outreach. Voice never approves
physical actions. Stale approvals never reused after restart.

## Status honesty

REAL: chat→mission→tick→observe→decide→memory chain,
screenshot observations (approved), ICS agenda import,
bootstrap idempotency, recovery scan, mission cards.
SIMULATED: printer pipeline (metadata only). TEST: camera
fixtures. UNAVAILABLE: Garmin (no OAuth, honestly reported),
live web research (no transport — missions wait instead of
faking), n8n auto-install (disk-space discipline; system
useful without it). FUTURE: UI grounding/OCR layer,
research-node routing, voice/vision wearables.

## Pages

/world (Command Center) · /missions (+ cards) · /projects ·
/memory · /research · /morning · /agenda · /devices ·
/workshop · /fabrication · /physical (via API matrix) ·
/integrations (n8n plane) · /mobile
