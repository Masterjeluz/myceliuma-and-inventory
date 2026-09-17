# Mycelium startup, recovery & safe mode (Windows 10)

Target: Windows 10, no administrator privileges required.

## What starts

1. **Mycelium coordinator** — `uvicorn coordinator.app.main:app`
   on `127.0.0.1:8000`.
2. **Desktop agent** — safe/default mode: observes (screenshots on
   explicit mission steps only), never clicks/types without an
   exact human YES.
3. **Local Ollama-dependent services** — only if Ollama answers;
   otherwise everything degrades to honest WAITING states.
4. **Safe research scheduler** — nothing runs by itself. Finished
   and interrupted missions are *inspected*, never blindly
   executed (see `recovery.md`).

## Install startup (Task Scheduler, user-level)

Run once from the repo (no admin needed):

```powershell
cd mycelium-ai-main
.\scripts\register-startup.ps1
```

This creates a user-level scheduled task `MyceliumCoordinator`
that runs at logon:

- `python -m uvicorn coordinator.app.main:app --host 127.0.0.1 --port 8000`
- working directory: the `mycelium-ai-main` folder
- starts only on AC power, stops gracefully at logoff

Disable:

```powershell
.\scripts\unregister-startup.ps1
# or: Task Scheduler → MyceliumCoordinator → Disable
```

## Manual start / stop

```powershell
cd mycelium-ai-main
.\scripts\start-mycelium.ps1        # coordinator :8000
.\scripts\start-mycelium.ps1 -Agent # + desktop agent (safe mode)
# stop: Ctrl+C in each window, or:
Get-Process python | Stop-Process   # last resort
```

## What startup NEVER does

- click / type / publish / print
- move printers, robots, drones, actuators
- send mail, purchases, outreach, bookings
- approve anything (approvals are human-only, always)

Startup MAY: start the coordinator, start a read-only desktop
agent, scan unfinished missions (report-only), prepare plans,
run *explicitly resumed* read-only research, report findings.

## Recovery on boot

On every coordinator start, `lifespan` runs `_v1_startup_scan()`:

- lists non-terminal missions
- assesses each via `recovery.assess()` (pure, no mutation)
- logs `safe_to_resume` / `needs_reapproval` / `waiting_agent`
- executes nothing

Continue explicitly afterwards:

- `POST /api/v1/missions/recover` — report only
- `POST /api/v1/missions/recover {"resume_safe": true}` — ticks
  read-only missions through the bounded loop
- Command Center: “Ga verder met het belangrijkste veilige onderzoek.”

Stale approvals are never reused: any gated step that survived
a restart needs a fresh human YES.

## Health checks

- `GET /api/v1/health` — coordinator alive
- `GET /api/v1/status` — nodes, leases, approvals overview
- `GET /api/v1/research/capability` — `unprobed` until you pass
  `?probe=true` (one tiny bounded local-model call)
- `GET /api/v1/physical/status` — honest matrix, never fake LIVE
- `GET /morning` — what Mycelium did, what waits for you

## Logs

Uvicorn stdout (the console window) carries `coordinator_started`,
`startup_scan …`, `node_registered`, `chat_turn`, mission events.
Persistent history lives in the databases:

- `data/mycelium.db` — nodes/tasks queue
- chat/agent database (`MYCELIUM_CHAT_DATABASE_PATH`, default
  next to it) — conversations, missions, memories, agenda

Point both at tmp files when experimenting; never touch real
data for tests.

## Safe mode / read-only mode

- Desktop agent default = observe only; input actions stay
  `pending_approval` until an exact YES.
- Coordinator has no kill-switch dependency: stopping uvicorn
  freezes everything mid-step; missions resume safely via the
  recovery scan (read-only steps) or wait for re-approval.
- If Ollama is down: advice turns fall back to retrieval-only
  replies, analysis steps fail bounded and missions report
  `WAITING_FOR_RESEARCH_CAPABILITY`-style waits instead of
  pretending.
