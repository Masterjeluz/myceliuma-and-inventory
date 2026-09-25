# INVENTory Infinite Canvas — future direction (NOT in scope)

Status: **FUTURE / ARCHITECTURAL DIRECTION ONLY.**
Date recorded (UTC): 2026-09-25.
Priority rule: this canvas must NOT restructure the roadmap. Current priority stays: close existing backend/UI gaps and make the end-to-end journey (HOME → READY → WORLD → CHAT → ADVISE → MISSION → APPROVAL → TASK → EVENT) genuinely usable.

## Concept (one paragraph)

A future additive UI layer: an interactive digital workshop for projects, ideas, research, inventory, missions and knowledge — inspired by Obsidian-style graphs, infinite-canvas tools and Terraria-like spatial exploration. It visualizes the existing world model; it never becomes a second source of truth.

## What the investigation found (CODE > TESTS > DOCS, read-only 2026-09-25)

- **Nodes ready:** all 11 INVENTory entities carry `name` + `description` + `provenance` (`inventory/app/schemas.py`); all 16 Mycelium overlay types already emit `{id, type, label, source, metadata}` (`mycelium-ai-main/coordinator/app/worldgraph.py:50-62`).
- **Edges ready:** 10 directed relationship predicates incl. `part_of/contains/became/led_to/produced_by/stored_in` (`inventory/app/schemas.py:535-546`); overlay edges (`uses_context, researches, remembers, may_relate_to, captured, HAS, PROVIDES`, …); mission→task binding via `tasks.mission_id`; research claim/source/contradiction links; events are timeline markers, not edges.
- **Spatial gap:** zero coordinate/position fields anywhere (locations explicitly "no GIS, no 3D, hierarchy via relationships"). Layout must stay client-side ephemeral until/unless a persisted-layout step is approved.
- **UI starting point:** world-graph SVG in `coordinator/app/ui.py` (`graph_panel`, `GRAPH_JS`) already pans/zooms/selects/filters over `build_world_graph` data (depth 1–2, 200 nodes/400 edges). Missing only: unbounded viewport + node dragging + search-to-focus. No `<canvas>` graphs, no JS graph libs anywhere.

## Guardrails (binding)

1. Additive only — builds on the existing world graph, relationships, overlays, project/workspace data.
2. Do NOT replace `/world`. Do NOT redesign the backend for the canvas now. Do NOT build the canvas until the current journey is genuinely usable.
3. Canvas stays read-only with deep links to existing `/web/*` gates; existing approval/provenance model unchanged.
4. No new frontend framework when it happens (extend the existing SVG approach first).
5. Persisted layout is the first and only backend-adjacent step, and only after ephemeral dragging proves valuable.

## Roadmap placement (when it happens, max 8 steps)

1. `GET /canvas` read-only page reusing `_graph_data` + `graph_panel`, unbounded viewport.
2. Client-side node dragging + search-to-focus. (MVP ends here.)
3. Workspace/area grouping (`project_ref`, `loc_`/`contains` rings).
4. Mission quest-trails + task delegation edges.
5. Research/memory/candidate overlay layers.
6. In-canvas gate buttons posting to existing `/web/*`.
7. Persisted layout (only backend-adjacent step).
8. Terraria skin (tiles/sprites/ambient) over unchanged node data.

Ladder it grows into: World → areas → objects → projects → machines → materials → missions → crafting → real-world actions — each rung a rendering rule over existing predicates/overlays, never a migration.

## Explicitly out of scope

New node/edge tables, position columns, framework additions (React/d3/cytoscape), realtime collaboration, world-gen/sprites/game loop, canvas-resident editing, 3D merge, live camera streams, offline/PWA, touching `/world`.
