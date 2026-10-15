# Nodes and devices

## What a node is today

A node is a worker process that registers, sends heartbeats, and pulls supported tasks from the coordinator. It does not open an inbound port for the coordinator. The current worker is Python-based and already uses cross-platform APIs for much of its telemetry, but the setup experience is not equally easy on every platform.

## Platform readiness

| Platform | Today | Sensible next step |
|---|---|---|
| Linux | CLI installer, diagnostics, optional user `systemd` unit | simplify the documented path and keep least-privilege defaults |
| Windows | worker code can run, but setup is mostly manual | guided per-user PowerShell installer, diagnostics, and optional Scheduled Task |
| Android | no supported persistent worker | start with the mobile web UI; investigate a limited Termux worker only after lifecycle and permission tests |

## Safe starter configuration

- Pick a unique node ID; reusing one overwrites its registration identity.
- Use a private connection such as a trusted LAN or tailnet; do not expose the coordinator publicly as a shortcut.
- Start with the narrow, documented capability set. Never grant wildcard, shell, or generic command execution.
- Store node tokens locally with OS-appropriate protection. Do not paste them into chat, commits, screenshots, or a shared vault.
- Remote-input capabilities are separate and must be explicitly enabled and probed on the node.

## Not yet delivered

- A polished Windows “two click” installer and managed restart flow.
- An Android-native/Termux node with a reliable foreground lifetime.
- General drag-and-drop files/tabs between nodes.
- A robust cross-device coauthoring protocol for simultaneous edits.
