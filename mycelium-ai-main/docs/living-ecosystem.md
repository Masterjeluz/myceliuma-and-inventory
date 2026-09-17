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
- `coordinator/app/context_packet.py` — universal + continuation packets
- `coordinator/app/ecosystem.py` — entity CONNECTED TO, summary, voice
- `coordinator/app/notify_center.py` — IN_APP real, WEB_PUSH unavailable
- `coordinator/app/linux_node.py` — starter capabilities + checks
- `coordinator/app/routes_conversations.py` — real import route (mounted)

## Mycelium is the world + orchestration layer

ChatGPT / Claude / Gemini / Ollama / OpenCode / Antigravity are
ADVISORS / CLIENTS / TOOLS. They never approve, never verify, never
touch hardware. Advisor loop: Jelles → Mycelium → external advice →
import → analysis → candidate plan → approval → execution →
verification.
