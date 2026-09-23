# Mycelium OpenCode worker

External executor for code tasks. Registers as a normal Mycelium
node, polls the task queue, runs local OpenCode for `code.*` tasks
and reports results. Executor, never authority: it cannot approve,
write, execute physically, verify, or create tasks.

## Start

```powershell
python -m code_worker.main --coordinator http://127.0.0.1:8000 --workdir C:\path\to\repo --poll-seconds 10
```

Single iteration (no loop):

```powershell
python -m code_worker.main --coordinator http://127.0.0.1:8000 --workdir C:\path\to\repo --once
```

## Environment variables

| Variable | Use |
|---|---|
| `MYCELIUM_NODE_TOKEN` | Node credential (or `--node-token`). Bound on first register, required afterwards. Never hardcoded. |
| `PATH` | Must contain the `opencode` binary (or `--opencode-bin`). |

No other secrets are read. Task results sent to the coordinator
contain only `files_changed`, `tests`, `summary` and a tail of
OpenCode output — never tokens or credentials.

## Node identity

- `node-id`: `opencode-<hostname>` by default (override with `--node-id`).
- `tier`: `worker` (override with `--tier seed|worker|core`).
- Capabilities: `code.patch`, `code.review`, `code.test` (override with `--capability`, repeatable).
- Executors: `exec:code` (override with `--executor`, repeatable).
- Heartbeat every poll with `available: True`; a node unseen for
  60s is stale and gets no work until it heartbeats again.

## Allowed task kinds

Only the `code.*` prefix executes (`code.patch`, `code.review`,
`code.test`, …). Any other kind is reported back as
`failed/unsupported` without running anything, never silently.

The worker calls exactly these coordinator endpoints (anything
else is refused locally before any network I/O):

- `POST /api/v1/nodes/register`, `POST /api/v1/nodes/{id}/heartbeat`
- `POST /api/v1/tasks/claim/{id}`, `POST /api/v1/tasks/{id}/complete`
- `GET /api/v1/context/packet`, `GET /api/v1/project/package`
- `GET /api/v1/tasks`, `GET /api/v1/presence`, `GET /api/v1/guide`

## Safety policy

- Task payloads are goal descriptions, never commands: payload
  strings never become shell, paths, or Python. The fixed local
  test command comes only from `--test-cmd`, never from a task.
- Local OpenCode runs as `opencode run <prompt> --format json
  --dir <workdir>`, **never with `--auto`**: the local OpenCode
  permission system stays in charge on the worker machine.
- The worker never calls mission-approve, write-approve/execute/
  verify, printer/robot/drone, desktop-dispatch, or task-create
  endpoints, and never sends a human YES. Existing gates stay the
  sole owners of human approval.
- Changed files are detected with read-only `git status`
  (non-git folders simply report none).

## Multiple workers

Run one process per machine with a distinct `--node-id`. The
coordinator distributes by capability subset + tier + priority;
claims are atomic, so two workers never get the same task. A
crashed worker's lease expires on the next claim (requeue below
3 attempts, failed at the limit, blocked for uncertain physical
work) — no coordinator action needed.

## Going offline

Stop the process or let heartbeats lapse: after 60s without a
heartbeat the node is stale and receives nothing. Assigned work
returns to the queue via lease expiry; nothing blocks the
coordinator.
