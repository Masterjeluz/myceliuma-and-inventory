# Mycelium, in one place

> A living field guide to the Mycelium AI coordinator, INVENTory, and the devices that may join them.

Mycelium is a local-first workshop for people and AI agents to observe, organise, and carry out useful work. The goal is a connected homelab where local models and small computers cooperate, while people stay in charge of consequential actions.

## Navigate

- [[Vision and principles]] — why this exists and what good should feel like.
- [[System map]] — the actual services, boundaries, and data flow.
- [[What works today]] — usable features and honest limitations.
- [[Nodes and devices]] — what a node is and how onboarding should evolve.
- [[INVENTory and knowledge]] — what the world model stores and how it is protected.
- [[Obsidian LiveSync]] — the planned self-hosted vault sync setup.
- [[Roadmap]] — a sequenced path from the current build to the homelab vision.
- [[Recurring goals and blockers]] — what has been revisited, what stopped integration, and what is now fixed.
- [[Decisions and questions]] — choices we have made and questions still open.

## A useful mental model

**INVENTory describes the world. The coordinator routes work. Nodes volunteer bounded capabilities. Views help a person understand and steer the system.** They are separate services connected through deliberate APIs; this vault documents them and does not replace their databases.

## Current status

- Coordinator: `mycelium-ai-main/`, local web UI on port 8000.
- INVENTory: `inventory/`, independent world-model API on port 8080.
- Desktop scanner: `Mycelium/agent/`, separate local scanner/UI on port 8787.
- Local start scripts: `tools/start-local.ps1` and `tools/install-autostart.ps1`.
- Coordinator scheduler: four bounded read-only checks; status at `/system` and `/api/v1/jobs/scheduler`.
- Node worker: pull-only client; Windows/Linux core support exists, but onboarding is uneven. Android is not yet a supported background node.

## The one active outcome

Make this project vault usable on your devices before adding another integration:

1. Open `Mycelium-Knowledge-Vault/` as its own Obsidian vault. The currently open vault is **Solarlab**; it is configured for CouchDB database `solarlab`. This project folder is separate and has not been configured for LiveSync.
2. Configure this project vault with its own CouchDB database and verify one harmless note syncs from desktop to CouchDB and back.
3. Add the private NetBird HTTPS route, then verify that same note reaches Android and returns to desktop.

Keep Solarlab separate. This avoids accidentally mixing or syncing its files with the Mycelium project notes. The local CouchDB endpoint is answering; the note round-trip and Android route are the remaining sync checks.

See [[What works today]] for current boundaries. This vault is a project guide, not a live status dashboard.
