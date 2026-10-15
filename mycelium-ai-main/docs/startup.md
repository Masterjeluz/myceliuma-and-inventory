# Mycelium startup, recovery & safe mode (Windows 10)

Target: Windows 10, no administrator privileges required.

## What the combined Windows launcher starts

Run `tools/start-local.ps1` from the repository root to start the
local stack. It checks each loopback service first and leaves services
that already answer in place:

1. **INVENTory API** on `127.0.0.1:8080`.
2. **Mycelium coordinator** on `127.0.0.1:8000`.
3. **Ollama** on `127.0.0.1:11434`, if installed.
4. **Hermes gateway** on `127.0.0.1:8642`, if installed.
5. **Obsidian LiveSync CouchDB** on `127.0.0.1:5984`, when Docker
   Desktop's engine is available.
6. **Bounded coordinator scheduler** — starts with the API and
   periodically runs four read-only summaries: watcher scan,
   device health, queue-state reconciliation, and research-source
   counts. It never creates queue work, dispatches nodes, calls a
   model, accesses hardware, resumes missions, or approves actions.
   Set `MYCELIUM_BACKGROUND_SCHEDULER=0` before startup to disable
   it. See `/system` and `GET /api/v1/jobs/scheduler` for status.
   Finished and interrupted missions are still *inspected*, never
   blindly executed (see `recovery.md`).

The launcher uses a project's `.venv` only when FastAPI, Uvicorn, and
the app module import successfully. It then tries the system Python.
If neither interpreter works, it reports a startup warning. Rerun the
launcher to bring back a service that was stopped; it is not a
continuous watchdog. It does not start the desktop agent.

## Install the complete stack at Windows sign-in

Run once from the repository root (no administrator privileges needed):

```powershell
.\tools\install-autostart.ps1
```

This creates a shortcut in the current user's Startup folder. At sign-in,
it opens Docker Desktop and runs `tools/start-local.ps1` hidden. To start
the stack immediately, run that script directly. To disable sign-in startup,
open `shell:startup` and remove `MyceliumLocal.lnk`.

The coordinator-only Task Scheduler scripts remain available in
`mycelium-ai-main/scripts/` for a coordinator-only setup. Do not register
that task alongside the combined stack shortcut; both would try to start
the coordinator at sign-in.

## Coordinator-only startup controls

```powershell
# Install the coordinator-only scheduled task:
.\scripts\register-startup.ps1
# Remove that task:
.\scripts\unregister-startup.ps1
```

## Manual coordinator start / status / stop (Windows)

```powershell
cd mycelium-ai-main
.\scripts\start-mycelium.ps1        # coordinator :8000 (start)
.\scripts\start-mycelium.ps1 -Agent # + desktop agent (safe mode)
# status:
Invoke-WebRequest http://127.0.0.1:8000/api/v1/health          # coordinator
Invoke-WebRequest http://127.0.0.1:8000/api/v1/status          # nodes/leases/approvals
Invoke-WebRequest http://127.0.0.1:8000/api/v1/mode            # DAY / OVERNIGHT
# stop: Ctrl+C in each window, or per task:
Get-ScheduledTask -TaskName MyceliumCoordinator | Stop-ScheduledTask  # scheduled task only
# restart: stop, then start again (missions resume via recovery scan, read-only)
```

## Linux: coordinator as a user service (no root)

Same pattern as the node unit (`node_client/mycelium-node.service`):

```ini
[Unit]
Description=Mycelium coordinator (local-first)
After=network-online.target
[Service]
Type=simple
WorkingDirectory=%h/mycelium-ai-main
ExecStart=%h/mycelium-ai-main/.venv/bin/python -m uvicorn coordinator.app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
NoNewPrivileges=true
[Install]
WantedBy=default.target
```

```bash
# save as ~/.config/systemd/user/mycelium-coordinator.service, then:
systemctl --user daemon-reload
systemctl --user enable --now mycelium-coordinator  # start
systemctl --user status mycelium-coordinator        # status
systemctl --user restart mycelium-coordinator       # restart
systemctl --user stop mycelium-coordinator          # stop
```

## Overnight mode

Set `OVERNIGHT` from `/morning` (or `POST /api/v1/mode`) to let
safe research, analysis and reports proceed; queue work via
`POST /api/v1/research/queue`, run it via
`POST /api/v1/research/queue/run-once` manually or through n8n
cron. The built-in scheduler does not execute queued research.
See `overnight-research.md`.
BOOT ≠ APPROVAL still holds: physical, desktop input, publishing
and approvals never run overnight.

## What startup NEVER does

- click / type / publish / print
- move printers, robots, drones, actuators
- send mail, purchases, outreach, bookings
- approve anything (approvals are human-only, always)

Startup MAY: start the coordinator and its four read-only periodic
summaries, start a read-only desktop agent, scan unfinished missions
(report-only), prepare plans, run *explicitly resumed* read-only
research, report findings.

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
