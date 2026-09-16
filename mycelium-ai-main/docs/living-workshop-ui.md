# Living Workshop UI (BIG #19) — IMPLEMENTED

From functional dashboard to living digital workshop:
one dark-earth SolarPunk visual system over unchanged
APIs. The UI visualizes and interacts; it duplicates no
domain truth.

## Visual philosophy

Alive, organic, calm, technical without enterprise
gloss. Near-black soil, warm charcoal, moss/forest
tones, muted plant greens, one restrained amber,
warm off-white ink, rare bioluminescent accents
(memory halos, observation pulses). Information first:
every glow means a state, every shape means a kind.

## Design system (`coordinator/app/ui.py`)

Single source of presentation: CSS variables as
design tokens (`--soil`, `--moss`, `--amber`,
`--spore`, spacing, radius, organic easing), one
`shell()` (topbar / world nav / workspace / context
rail / command bar), shared components (status dots,
truth/state chips, grove cards, process paths,
definition tables, empty states). No per-page style
drift, no framework, no client state duplication.

## Information architecture

- `/` Living World: graph at the center, missions,
  tasks, nodes, notifications around it, chat below.
- `/world`: full graph explorer. `/projects`:
  project ecosystems. `/activity`: event stream with
  provenance. `/memory`, `/missions`, `/chat`,
  `/research`, `/devices`, `/watcher`, `/morning`,
  `/workshop`, `/fabrication`, `/workshop/3d`,
  `/cameras`, `/agents`, `/skills`, `/health`,
  `/mobile` (deliberate mobile order, not squeezed
  desktop).
- Legacy `/workshop/graph` renders the same explorer.

## Graph language

SVG, deterministic radial layout, bounded depth 1–2:
object = moss circle, project = double-ring cluster,
idea = seed diamond, memory/mission = breathing halo,
node/device = technical square, observation = pulse,
event = particle, task = amber circle. Solid outlines
are world truth (INVENTory); dashed are Mycelium
overlays; red is conflict. Pan (pointer drag), wheel
zoom, click/Enter select with details + provenance,
type + source filters, reset view, neighborhood
expansion via server round-trip. Touch: pointer
events throughout; simplified labels on small screens.

## Entity visual language

Status dots (online/busy amber pulse, stale dim,
failed/blocked/disabled red, verified green) and
chips (truth tiers, LIVE/MOCK/SIMULATED/TEST/
UNAVAILABLE states) reused on every page. Mission
steps render as a process path — proposed and
approved are visibly not executed. Chat linkifies
`obj_/proj_/idea_/mem_/mission_` ids into world,
memory and mission targets. Health stays scoped:
same data, same gates, no leakage through generic
components.

## Motion principles

Restrained and meaningful: breathing halos, fresh
observation pulses, selected-node expansion, organic
easing on hover. Nothing moves constantly; nothing
decorates without informing. `prefers-reduced-motion`
disables all animation and transitions.

## Responsive behavior

Three columns → two (context rail hides <1080px) →
one (horizontal scroll nav <720px). Graph keeps
full interaction on touch; tables scroll within
cards; command bar stays reachable.

## Accessibility

Semantic landmarks (header/nav/main/aside), one h1
per page, labelled forms, visible amber focus rings,
keyboard-operable graph nodes (Tab + Enter) with
screen-reader labels, contrast-checked ink on soil,
no information carried by color alone (dots pair
with text states).

## Architecture boundary

Pages call the same backend functions as before;
no new endpoints except `/world`, `/projects`,
`/activity` (all read-only projections). Health,
approval, verification and fencing flows untouched.
