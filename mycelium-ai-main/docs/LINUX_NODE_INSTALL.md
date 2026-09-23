# Mycelium Linux Node

Turn a Debian/Ubuntu-style laptop into a pull-only Mycelium node.
No root, no Docker, no cloud account, no inbound ports.

## Install

```bash
git clone <repo-url> mycelium-ai-main
cd mycelium-ai-main
./scripts/install_linux_node.sh --node-id linux-laptop-1
```

(If the execute bit got lost in transit: `bash
scripts/install_linux_node.sh --node-id linux-laptop-1`.)

This checks Python (>= 3.11) and git, creates `.venv`, installs the
project, probes Ollama/NVIDIA (both optional), and writes the local
config to `~/.config/mycelium/node.env` (chmod 600). Re-running is
safe: existing node id and token are always preserved.

Useful flags (all optional):

```bash
./scripts/install_linux_node.sh --node-id linux-laptop-1 --tier worker \
  --coordinator http://127.0.0.1:8000 --poll-seconds 5 \
  --capability node.status --capability inventory.read
./scripts/install_linux_node.sh --node-id linux-laptop-1 --with-systemd
./scripts/install_linux_node.sh --node-id linux-laptop-1 --bootstrap
```

`--bootstrap` performs the one-time registration + heartbeat against a
running coordinator. Without it, nothing touches the network.

## Configure

The installer owns `~/.config/mycelium/node.env`:

```text
MYCELIUM_COORDINATOR_URL=http://127.0.0.1:8000
MYCELIUM_NODE_ID=linux-laptop-1
MYCELIUM_NODE_TIER=worker
MYCELIUM_NODE_TOKEN=<generated, never shown>
MYCELIUM_NODE_CAPABILITIES=node.status,research.fetch,inventory.read
MYCELIUM_NODE_POLL_SECONDS=10.0
```

First run generates the token (64 hex chars, same format as
`coordinator/app/nodes.py::generate_token`); later runs keep it.
First registration binds it server-side; afterwards the same token is
required for heartbeat and task claims. Rotate via the existing
`POST /api/v1/nodes/{id}/rotate-token` flow, never by reinstalling.

## Start

Manual:

```bash
source ~/.config/mycelium/node.env
.venv/bin/python -m node_client.main --coordinator "$MYCELIUM_COORDINATOR_URL" \
  --node-id "$MYCELIUM_NODE_ID" --tier worker \
  --capability node.status --capability research.fetch \
  --capability inventory.read --poll-seconds 10
```

As a user service (survives reboot, logs via journalctl):

```bash
./scripts/install_linux_node.sh --node-id linux-laptop-1 --with-systemd
systemctl --user daemon-reload
systemctl --user enable --now mycelium-node
journalctl --user -u mycelium-node -f
```

## Check

```bash
.venv/bin/python -m node_client.install doctor
```

Shows OS / Python / Git / Config / Identity / Coordinator /
Registration / Heartbeat / Ollama / NVIDIA / Capabilities. Secrets are
never printed. The node is healthy when it appears under **Nodes** in
the coordinator UI (`http://127.0.0.1:8000/`) with status ONLINE.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Coordinator unreachable` | Start the coordinator first: `python -m uvicorn coordinator.app.main:app --host 127.0.0.1 --port 8000` |
| `not registered yet` | Run install once with `--bootstrap`, or just start the node (it registers itself) |
| Node `STALE` in UI | No heartbeat for 60s: check the node process / `journalctl` |
| No tasks claimed | Task `required_capabilities` must be a subset of the node's; check `Capabilities` in doctor |
| `Ollama OPTIONAL` | Normal without Ollama; node still does status/inventory/fetch work |

Uninstall locally (server-side identity and audit are always kept):

```bash
.venv/bin/python -m node_client.install uninstall
systemctl --user disable --now mycelium-node  # if enabled
```

## Security

- Outbound-only: the node polls (`register → heartbeat → claim →
  complete`); the coordinator never connects to the node, never sends
  shell commands. Only `system_inventory`, `desktop_screenshot` and
  `research.fetch_url` auto-execute; desktop input always needs explicit
  human approval and never runs in the claim loop.
- The token lives in one chmod-600 file and the process environment.
  It is never logged, never returned by any API, and only its salted
  hash is stored coordinator-side. Never commit it.
- Capabilities are fail-closed against the starter set
  (`coordinator/app/linux_node.py`): no wildcards, no shell, nothing
  the local executors cannot actually do.
