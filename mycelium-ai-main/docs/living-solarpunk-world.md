# Living Solarpunk World (BIG #44)

The workshop as a place: original pixel-solarpunk visuals
over real Mycelium state. Architecture stays authoritative;
every visual object maps to a real record or derived state,
every object links somewhere real, empty stores render
empty. No XP, no scores, no invented activity.

## World objects

`world.py`: NODE, PROJECT, MACHINE, ENERGY, CAMPAIGN,
CRAFT, DISCOVERY, SYMBIOSIS, RESEARCH, PRESENCE — each with
glyph + words (never icon-only), state, activity,
attention, trust where applicable, href, and an accessible
text line. Collectors are bounded and best-effort; unknown
kinds fall back to PRESENCE rather than inventing a shape.

- Nodes: awake/quiet, connected hardware counts, VERIFIED /
  OBSERVED / ADVERTISED trust (quiet nodes never read
  verified), current task or idle/quiet activity, telemetry
  freshness.
- Campaigns: live counts, current quest, next action,
  blocked marker.
- Energy: only with records; solar ☀ flow, battery 🔋
  store, machine ⚙ activity, grid 🔌 link; UNKNOWN stays
  a word, never a zero.
- Discoveries: open proposals as seedlings (uncertain until
  reviewed). Research: dossiers with open-question counts.

## HUD

`world_hud()`: campaign, quest, attention counts, nodes
awake/total, busy nodes, open discoveries — live store
counts, never scores. Rendered on `/world` (hud-cell row)
and `/mobile` (World block, shared NOW/WAITING/AVAILABLE/
DISCOVERED/OFFLINE vocabulary).

## Symbiosis network

`symbiosis_network(entity)`: PROJECT root with branch
children grouped ENERGY/MACHINE/MATERIAL/FINANCE/…,
each with state, strength (established/growing/seedling),
predicate and world href. Without a focus entity the world
shows open seedlings. Display only — statuses never change
here.

## Craft world

Vertical IDEA→…→PROJECT chain for the focused entity with
✓/●/○/! evidence states from `stage_states`. Completion is
never invented.

## Living background

Two new clamped signals join the existing five: solar
production records lift bright energy spores; presence
NEEDS tint a few spores amber as subtle world emphasis.
One rAF loop, same reduced-motion early return, same
ambient honesty.

## Graph glow

Hardware overlay nodes already carry `verified` from the
human-link store (BIG #43); the graph renderer now draws
them with a thicker stroke, glow ring and `verified-glow`
class. Verified connections read stronger; advertised ones
never do.

## Guide as explanation

Quiet/offline node cards carry last heartbeat, last known
task, what restores availability, and evidence links (node
reality + /nodes). The world links "Why? Ask the guide";
reasoning lives in the guide, not the world.

## Labels

World objects/HUD/network/craft/energy/stakes: REAL derived
state. Background motion: ambient, not data. Printer
transport: UNAVAILABLE. Fab execution: SIMULATED. WEB_PUSH:
UNAVAILABLE. Energy-aware routing: FUTURE (explicitly not
implemented here).
