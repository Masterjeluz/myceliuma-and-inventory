# Living Game Layer (BIG #43)

Terraria-like progression + solarpunk workshop + Ori-like
atmosphere — as a presentation layer over real Mycelium
state. Architecture first: every game concept is a VIEW over
existing stores. No XP, no rewards, no second database.

## Campaigns

`campaigns.py`: a campaign stores only title, description,
and ordered quest ids (`cmp_` + `campaigns` table). All
progress derives live via `quests.quest_detail`:

- per-quest states, completed/total/blocked/waiting counts
- current quest (first non-completed)
- next actionable item (first open step chain-wide, with
  its real href + readiness reason)
- evidence links (quest hrefs + progress)

Creating with an unknown quest id refuses; a deleted quest
renders as MISSING (never silently dropped, never invented).
Refresh audits via `campaign.updated`. API + `/campaigns`
page (trail chain ✓↓●↓○ with links) + morning CURRENT
CAMPAIGN section (only when campaigns exist) + mobile
campaign panel.

## Game state

`game.py::game_state()` composes one read-only view:
world (living state), campaigns, current quest (campaign
first, else first open quest), presence-as-stakes (same
items/hrefs/priority, game framing words, original band kept
on each item), craft (quest-linked entities), symbiosis
(open proposals as seedlings), nodes (awake/quiet),
energy, workshop (fabrication activity), discoveries.
Failing sources degrade to explicit empty. Served at
`GET /api/v1/game/state` (GET only — POST is 405) and
rendered at `/game`. The game layer approves nothing and
executes nothing.

## Symbiosis as progression

Display only: VERIFIED reads strong, SUPPORTED growing,
PROPOSED a seedling (uncertain until reviewed). Strength
bars on the symbiosis page, legend panel, seedling wording
in the game view. States never promote silently.

## Craft as gameplay

The craft tree keeps its evidence-backed states; the page
gains game framing (what ✓/!/○ mean, campaign and game-view
cross-links) and the game view shows quest-linked chains
with stage glyphs.

## Living world

`living_bg()` gains five clamped signals from real stores:
research (flow quickens), fresh candidates (discovery
pulse), verified links (faint mycelium threads), active
fabrication (warm spores), offline nodes (field dims).
Single rAF loop, same reduced-motion early return, subtle
by design. Motion never claims specific events happened.

## Visual identity

Original solarpunk-workshop accents in `ui.py`: pixel-step
corners, solar/leaf marks, quest-trail chain, campaign
cards, strength bars, companion blocks on guide cards.
Warm soil/moss/amber/spore palette (already the house
style). Usability primary; no copied artwork.

## Guide companion

Guide items gain BLOCKED BY / UNLOCKS / EVIDENCE (real
label+href pairs, rendered only when present), plus
campaign-context cards (🗺 WHAT/WHY/NEXT/BLOCKED
BY/UNLOCKS/EVIDENCE over the live chain). No hallucinated
advice — every link opens a real record.

## Labels

Campaigns/quests/craft/symbiosis/stakes: REAL derived
state. Background motion: ambient, not data. Printer
transport: UNAVAILABLE. Fab execution: SIMULATED. WEB_PUSH:
UNAVAILABLE. Energy-aware routing: FUTURE.
