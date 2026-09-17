# Mobile ↔ Node Flow (BIG #30)

Mobile is the remote input surface, not a squeezed desktop.

## The flow

PHONE → coordinator → routing → node → result → mobile, shown on
`/mobile` as INPUT → PROCESSING → NODE → RESULT.

1. Jelles types ("Onderzoek dit.", "Maak hier een project van.",
   "Wat staat er nog open?", "Laat node laptop-2 dit verwerken.").
2. The coordinator routes text through the existing command/chat
   path (`POST /web/chat`, `POST /api/v1/command`).
3. A safe mission or task is proposed; anything physical waits for
   exact-YES approval (`/agents`, `/missions`).
4. A pull-only node claims the task (`tasks/claim`), executes within
   its advertised capabilities, reports back.
5. The result returns to `/mobile`; approvals stay human.

The UI never claims a node executed something it did not. Stale
(60s) and lease (300s × 3) semantics are unchanged (`main.py`).

## Quick actions (`/mobile`)

Research, Observe, Ask Mycelium, INVENTory, 3D, Project, Nodes,
Tasks, Import conversation — all deep-link existing routes
(`/research`, `/cameras`, `/chat`, `/world`, `/workshop/3d`,
`/projects`, `/nodes`, `/missions`, `/conversations`).

## Notifications (`notify_center.py`)

Closed types: `research_completed, mission_waiting,
approval_required, node_offline, task_completed, research_finding,
system_attention`.

- IN_APP: AVAILABLE (polling; `/activity`, `/mobile`,
  `GET /api/v1/notifications/*`). Reading never approves.
- WEB_PUSH: UNAVAILABLE (no push service configured; no credentials
  stored, no delivery faked). Capability: `GET
  /api/v1/notifications/capability`.

## Help

`/mobile` explains the six steps and states it plainly: "Jij blijft
degene die acties goedkeurt."
