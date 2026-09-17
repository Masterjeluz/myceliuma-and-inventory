# Linux Node Setup (BIG #30)

Old Linux laptop → Mycelium node → coordinator. Pull-only: the node
polls; the coordinator never opens connections into your network and
never sends shell commands.

## 10 steps

1. Check Python: `python3 --version` (need >= 3.11).
2. Install the node: from `mycelium-ai-main/`,
   `pip install -e .` (pytest only needs `pip install pytest httpx`).
3. Pick a node id: `linux-laptop-1` (fresh ids avoid stale-registration
   confusion; re-registering the same id upserts).
4. Capability config — starter set ONLY (see below).
5. Token: `export MYCELIUM_NODE_TOKEN=...` (never in git, never in DB).
6. Coordinator URL: `http://127.0.0.1:8000` (loopback; start the
   coordinator first: `python -m uvicorn coordinator.app.main:app
   --host 127.0.0.1 --port 8000`).
7. Heartbeat: register, then watch the coordinator log for
   `node_registered` and the `/nodes` page for ONLINE.
8. Start: `python -m node_client.main --coordinator
   http://127.0.0.1:8000 --node-id linux-laptop-1 --tier worker
   --capability inventory.read --poll-seconds 5`
   (repeat `--capability` per starter capability).
9. Test: claim a safe task (`tasks/claim`), complete it, check the
   result on `/mobile` and `/activity`.
10. Troubleshoot: node STALE after 60s without heartbeat; task lease
    300s × max 3 attempts; physical tasks block instead of silently
    re-routing; check `GET /api/v1/nodes/{id}` for derived status.

Pre-flight (no installs, no connections):
`POST /api/v1/linux-nodes/check` with `{python_version,
coordinator_url, node_id, capabilities}` runs the same checks as
`linux_node.bootstrap_check()`.

## Starter capabilities (contract: `linux_node.py`)

`node.status, research.search, research.fetch, analysis.ollama,
inventory.read, file.inspect`

Only what is really implemented. No wildcard, no `shell`/`exec`/
`command.run` — refused fail-closed. Contract:
`GET /api/v1/linux-nodes`.
