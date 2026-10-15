# INVENTory and knowledge

INVENTory is the canonical world-model service. Its records can describe objects, projects, ideas, relationships, events, hardware, sensors, cameras, locations, models, tasks, actuators, and files. The coordinator can read through a constrained HTTP bridge and can submit gated write proposals.

## Data rules

- INVENTory and coordinator have separate SQLite databases. Do not merge them or query one from the other directly.
- AI/sensor observations remain unverified until a human verifies them.
- Canonical entity tables are the source of truth; search indexes are derived.
- CRUD mutations append events.
- Hardware/device records are descriptions; their presence does not mean the device is controlled.

## Where Obsidian fits

Use this vault for explanations, architecture diagrams, operating procedures, decisions, and handoff notes. Use the runtime APIs for live entities, tasks, approval state, and device telemetry. The vault is not the new canonical store for those records.

Future integration should be a one-way, explicit export or context packet into the vault, with provenance and human review. Avoid an implicit bidirectional sync between notes and live operational records.
