# Living Ecosystem (BIG #30)

Mycelium is one workshop, not loose pages:

Jelles ↔ chat ↔ mobile ↔ brain ↔ missions ↔ research ↔ memory ↔
INVENTory ↔ cameras ↔ 3D ↔ projects ↔ files ↔ nodes ↔ fabrication ↔
verification.

## What changed

- `/world` is the cockpit: ecosystem links, live graph (real data only),
  context rail on select (no page jump), "do something with this" actions
  pointing at real endpoints (`/research`, `/missions`, `/conversations`,
  `/agents`).
- `/conversations` is the import surface for external AI chats (ChatGPT,
  Codex, OpenCode, Ollama, Claude, Gemini, Antigravity, Google AI Studio).
  See `conversation-bridge.md`.
- `/mobile` is the remote input surface: INPUT → PROCESSING → NODE →
  RESULT, quick actions on existing routes, "how do I use Mycelium" help.
  See `mobile-node-flow.md`.
- `/nodes` shows the fleet as small machines (ONLINE/STALE/OFFLINE/
  DISABLED) with WHAT IT CAN DO. Linux onboarding: `linux-node-setup.md`.
- `/cameras` shows the honest workflow (see `camera-workflow.md`):
  Insta360 = REGISTERED possible, CONNECTED only with a real adapter,
  otherwise UNAVAILABLE.
- `/3d` shows the photo→verified-object pipeline with stage chips
  (see `3d-workflow.md`). Procedural/test mesh is REAL; true
  reconstruction transport is UNAVAILABLE — no fake meshes.
- `/activity` speaks Mycelium voice ("Ik heb iets gevonden.", "Hier
  wacht ik op jou.") with links to real context.

## Honesty labels

REAL = works here. TEST = test double. SIMULATED = simulated device.
UNAVAILABLE = explicitly missing, with what Jelles must do. Imported
analysis is always OBSERVATION or CANDIDATE — never FACT. Promotion to
memory runs through the existing provenance flow (`memory.py`).

## Modules

- `coordinator/app/conversation_bridge.py` — import/analysis/missed
- `coordinator/app/context_packet.py` — universal + continuation packets (v1) + v2 handoff schema
- `coordinator/app/context_engine.py` — one dynamic composer (intent → bounded, scored, traceable sections)
- `coordinator/app/living_state.py` — global indicator (QUIET/RESEARCHING/THINKING/CONNECTING/DISTRIBUTED/WAITING/COMPLETE/BLOCKED) in every topbar
- `coordinator/app/ecosystem.py` — entity CONNECTED TO, summary, voice, node roles, discoveries
- `coordinator/app/notify_center.py` — IN_APP real, WEB_PUSH unavailable
- `coordinator/app/linux_node.py` — starter capabilities + checks
- `coordinator/app/routes_conversations.py` — real import route (mounted)
- `node_client/bootstrap.py` — one-command onboarding generator + systemd unit

## Activation (BIG #31)

- Global `/search` across inventory/memory/conversations/missions/research/nodes/agenda.
- Command traces: every Command Center run persists INTENT → CONTEXT → RESULT; `/world` shows the last flow.
- `/writes` inbox: propose links/objects, decide with exact YES; approval ≠ verification.
- Camera file ingest (REAL) + `/cameras/{id}` detail; direct transport stays UNAVAILABLE.
- Node roles (RESEARCH/ANALYSIS/INVENTORY/CAMERA/3D/INPUT/GENERAL) derived from advertised capabilities.
- Overnight mode + research queue (`/api/v1/research/queue`, run-once); morning opens with GOOD MORNING + overnight + mode switch.

## Mycelium is the world + orchestration layer

ChatGPT / Claude / Gemini / Ollama / OpenCode / Antigravity are
ADVISORS / CLIENTS / TOOLS. They never approve, never verify, never
touch hardware. Advisor loop: Jelles → Mycelium → external advice →
import → analysis → candidate plan → approval → execution →
verification.
