# Roadmap

## Priority 1 — Make it understandable and recoverable

- **Ready locally:** the project documentation vault exists, CouchDB answers on loopback, and Obsidian's separate Solarlab vault has an active encrypted connection to database `solarlab`.
- **Not yet proven:** a note round-trip in the Mycelium documentation vault. `Mycelium-Knowledge-Vault/` is not the currently open Solarlab vault and has no Obsidian settings.
- Finish one vertical slice: open the project folder as its own vault, configure a distinct `mycelium` LiveSync database, verify a desktop note round-trip, then connect Android through a private NetBird HTTPS route.
- **Proven locally:** Mos can receive an opt-in, text-only screen summary through `qwen3.5:4b`; a parser fix preserves descriptions when the model combines a label and sentence on one line.
- Keep runtime databases separate and backed up.

## Priority 2 — Easy, trustworthy node onboarding

- Windows guided installer and diagnostics; optional per-user Scheduled Task.
- Bring Linux scripts and docs into one canonical path.
- Show exact capabilities and connection scope before starting a node.
- Android remains a dashboard until a bounded background worker can be supported and tested.

## Priority 3 — Make the interface feel alive through real signals

- Improve `/solarpunk` district population and clarify active/idle/blocked/offline evidence.
- Connect activity, node presence, pending approvals, and model availability to visible status with timestamps.
- Improve responsive/mobile navigation and simple cross-linking to the relevant action.
- Keep `/side` frozen unless that boundary changes explicitly.

## Priority 4 — Real homelab workflows

- Define device identity, capability grants, revocation, and tailnet connection policy.
- Deliver safe remote file/tab handoff only after protocol, authentication, audit, and user-visible consent are designed.
- Build the print queue workflow in simulation first; require printer state, filament/bed conditions, camera verification, and fail-closed human escalation before any real automation.
- Test local webcam/vision flows with clear recording indicators and bounded retention.

## Priority 5 — Agent collaboration and swarms

- Persist scheduler/automation state in the existing canonical coordinator model after schema reality is verified.
- Use bounded small-agent jobs and explicit resource budgets, not uncontrolled background model fan-out.
- Show provenance, parent/child tasks, model, cost/latency, and stop/cancel controls.

## Not a near-term goal

Merge the coordinator and INVENTory databases, launch a general shell-capable agent, or make all nodes fully remotely controllable. Those choices increase coupling and risk without solving the first usability gaps.
