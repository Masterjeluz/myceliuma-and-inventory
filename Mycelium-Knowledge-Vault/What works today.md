# What works today

This is a code-informed orientation, not a promise that every optional dependency is online at all times.

## Usable surfaces

- Coordinator web UI and API on port 8000. The `/solarpunk` view links out to work areas, displays resident status, camera scan controls, a town message field, proposal/activity feed, and a gated delegation form.
- The visible task system can queue bounded work, and a pull-only node can claim supported work when registered and online.
- Local model and vision paths can operate through Hermes/Ollama when those services and the selected model are available.
- The coordinator now starts a bounded background scheduler for read-only watcher, device-health, queue-summary, and research-source checks. These checks do not create tasks or call models/hardware.
- Solar Punk City now refreshes NPC activity/status every five seconds while the tab is visible, reports the last successful connection, and avoids an overlapping request when a slower response is still in flight.
- Mos's chat has an opt-in **Scherm betrekken** checkbox. It sends a text-only summary from the latest saved screen observation through the local vision model; the raw image does not enter Hermes chat. A synthetic end-to-end observation returned `REAL` using `qwen3.5:4b` on 2026-10-14.
- INVENTory on port 8080 stores world-model records independently.
- The desktop scanner is a separate app on port 8787.
- The per-user startup shortcut runs `tools/start-local.ps1`, which attempts the coordinator, INVENTory, Ollama, Hermes, Docker Desktop, and loopback CouchDB without stopping the remaining startup attempts when one service is unavailable.

## Live service snapshot — 2026-10-15

- Coordinator `/api/v1/health`: healthy; background scheduler: enabled and running.
- The live `/api/v1/models/routes` returns HTTP 200 and shows local chat, summary, vision, and embedding routes. Code routes are honestly marked unavailable because the running environment cannot import `code_worker`; package discovery now includes it, but the live environment has not been reinstalled or restarted since that packaging fix.
- Hermes gateway: `REAL` (v0.21.5). Ollama: reachable with five models, including `qwen3.5:4b`.
- Node registry: one node is registered but stale; no online worker can claim queued work right now.
- The live API reports five task records, matching the root `data/mycelium.db`; `mycelium-ai-main/data/mycelium.db` has zero. This suggests the running process resolves its relative DB path from a different working directory or explicit environment. I have not restarted it or changed either database, because that could switch which records the UI sees.
- Coordinator, INVENTory, Hermes, and Ollama answered their local health/API checks. The scheduler reports enabled and running; Ollama exposes five installed models, and vision reports the local Qwen3.5:4b model. This confirms reachability, not that every workflow or hardware path works.
- CouchDB `/_up` answered `ok`; a metadata-only check found database `solarlab` with seven documents. Document contents were not read. Docker CLI access to the Desktop named pipe was denied, so container state was not independently confirmed.
- Obsidian 1.14.4 is open on the **Solarlab** vault. Self-hosted LiveSync reports E2EE enabled and active connection to `127.0.0.1:5984`, database `solarlab`. The prepared `Mycelium-Knowledge-Vault/` folder is not open and has no `.obsidian` settings; it is not syncing yet.
- NetBird reports connected on this PC. One remote peer is connected through a relay and five of six peers show as not connected; the connected peer hostname looks like the Android phone, but the service route is still missing. CouchDB is bound to this PC's `127.0.0.1`, and no private HTTPS proxy is configured. Android LiveSync therefore cannot reach CouchDB yet. No controlled note round-trip or second-device sync has been verified.
- The VLM verification used a synthetic gradient image and temporary database; it did not inspect the user's live screen or camera.

## Earlier UI inspection: `/solarpunk`

The page is understandable as a workshop: navigation, residents, room scan, activity, and proposal controls are all visible. It currently showed **0 districts**, six residents marked awake, one offline item in the header, two old queued research tasks, and a camera marked ready with zero stored frames. The “working” header reflects the displayed app state; the page itself explains that resident work follows real queue tasks. That is a good honesty cue, but the current scene has little evidence of a living, connected city yet.

## Current limits

- The UI is server-rendered and has mixed interaction patterns. The `/solarpunk` page has some live polling, but not a unified real-time event stream across the product.
- Node setup is uneven: Linux has an installer, Windows is mostly manual, and Android has no supported background worker.
- A coordinator restart needs a database-path check first: the active instance and the documented project-local database appear to point at different files.
- The live coordinator currently has one registered node, but it is stale; the queued research task has no active worker to claim it. No all-purpose node-to-node file transfer exists.
- Node operations are not arbitrary remote control. Remote desktop actions are a separate opt-in capability family; they should not be confused with basic node onboarding.
- Hardware and printing paths fail closed when adapters or dependencies are absent. A real printer/camera run is not part of normal automated verification.
- Obsidian LiveSync currently connects the separate Solarlab vault to local CouchDB. The Mycelium project vault still needs its own configuration and database, then a harmless note round-trip.
- Android still needs the selected NetBird-only HTTPS route to CouchDB. The port is loopback-only; do not expose 5984 directly.

## How to try safely

1. Start local services with `tools/start-local.ps1` and check coordinator `/api/v1/health`, `/api/v1/jobs/scheduler`, Hermes `/api/v1/hermes/status`, Ollama `/api/tags`, and `/api/v1/vision/capabilities`.
2. Open `http://127.0.0.1:8000/solarpunk`; inspect the nodes and activity views before delegating work.
3. Keep tests on temporary databases; do not send live hardware actions through tests.
4. For remote nodes, use a private network and only the capability list required for that device.
