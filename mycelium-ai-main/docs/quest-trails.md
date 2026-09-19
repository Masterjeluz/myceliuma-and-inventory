# Quest trails (BIG #42)

The first real quest-trail abstraction over missions, craft
states, symbiosis and presence. A quest references real work.

## Model

- A quest def (chat DB `quests` table) holds ONLY title +
  ordered step refs: `{key, label, kind, ref}` with closed
  kinds `mission | task | entity | finance | energy |
  hardware | note`.
- **No stored state.** Every read derives step state live:
  ✓ COMPLETE (record reached its done state), ● ACTIVE,
  ! BLOCKED/FAILED, ○ MISSING/WAITING — each with the
  underlying detail and an href to the real record.
- Progress is done/total over real records. No XP, no fake
  accomplishments.
- Quest states (closed): READY | ACTIVE | WAITING | BLOCKED |
  COMPLETED | FAILED.

## Hardware-aware readiness

Each step also carries readiness from actual node/device
state: READY (eligible node named), WAITING (camera node
offline, no eligible researcher), BLOCKED (underlying record
failed), UNAVAILABLE (printer transport). Offline hardware is
never pretended available.

## Example

Build Solar Upgrade 3/4: ✓ budget (finance CONFIRMED) →
✓ panels producing (energy recorded) → ✓ GPU verified
(human link) → ○ roof mounting (no linked record yet).

## Surfaces

`/quests` page (every step links to its record), quest JSON
API + `POST /{id}/refresh` (re-derives + audits),
presence `quest_blocked` (needs band), guide quest items,
morning QUESTS section (only when quests exist), overview
`quests`, packet-v2 quest block, mobile quests panel.
