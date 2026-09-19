# Mobile Mycelium (BIG #36)

The phone is the living command surface of Mycelium — a
surface over the coordinator, not a second application.
`/mobile` answers "What can I do right now?" and "Is
Mycelium waiting for me?" from live backend state only.

## Home order (small screens first)

NOW → WAITING FOR YOU → ACTIVE → INPUT → GUIDE ME →
how-it-works → CAMERA → CONTINUE ELSEWHERE → CRAFT →
SYMBIOSIS → NODES → RECENT → remember/queue → workbench →
status. Same backend and gates as desktop.

## Input lifecycle

"Wat wil je doen?" posts to `/web/chat` (the existing
coordinator entry). Quick actions link existing routes.
State shown: INPUT → PROCESSING → NODE → RESULT, with
RESULT in events/activity and NEEDS YOU pointing at YES
buttons. Oversized input refuses with a redirect, never a
500.

## Approval triage

`approval_cards()` unifies desktop actions, write proposals
and missions into cards with WHAT / WHY / SOURCE / SCOPE /
what YES does / what YES does NOT do. Actions: YES and NO
post to the existing gates (`/web/desktop/.../decision`,
`/web/writes/.../approve`, `/web/missions/.../approve|...`);
OPEN links the detail page; DEFER is an honest non-action
(open later, nothing changes). Replayed YES is harmless
(idempotent states); wrong response text never approves.

## Notifications

IN_APP only (`notification_cards()` + `?node=` per-node
view). Every notification carries a deeplink computed from
`related_mission` / `related_entity` / `related_task` or its
type (approval→agents, candidate→knowledge,
research→research, camera→cameras, connection→symbiosis,
fabrication→fabrication, nodes→nodes, morning→morning).
Tapping opens the real object. WEB_PUSH stays UNAVAILABLE
(capability endpoint says so).

## Camera from the phone

Counts (inbox/sessions/observations/waiting candidates) +
the honest chain FILE → SESSION → OBSERVATION → DESCRIBE →
REVIEW → CANDIDATE → LINK → YES, with Insta360 live
transport labeled UNAVAILABLE and the inbox as the real
path. No native upload is claimed.

## Continue elsewhere

CONTINUE ELSEWHERE surfaces the existing packet-v2: goal,
missions, entities, memories, open questions + COPY PACKET
(Markdown), JSON and continuation links, plus the 3D
packet. Models work; Mycelium keeps state; no secrets
inside. Works across ChatGPT, Claude, Gemini, Codex,
OpenCode, Ollama.

## Guide, craft, symbiosis, nodes, progress

- GUIDE ME: live guide cards (kind/glyph/what/why/next).
- CRAFT: presence checklists with ✓/○ linking to craft
  trees.
- SYMBIOSIS: PROPOSED items with WHY/SOURCE/STATUS;
  YES runs the guarded knowledge flow.
- NODES: status + WHAT IT CAN DO + the
  PHONE→COORDINATOR→NODE(S) mesh path (read-only BIG37
  prep; coordinator authoritative, no shell, no wildcard).
- ACTIVE: quest progress from mission/fab-job states only.

## Notifier (OpenCode/terminal)

`scripts/mycelium-notify.py` now covers the full run
lifecycle: `start`, `status` (PROGRESS), `need`/`waiting`
(WAITING_FOR_APPROVAL), `done`, `failed`. Terminal bell +
OSC 9/99 + ASCII fallback; no service, no credentials.
Long-term: OpenCode → Mycelium event → notification →
phone/web shows "Approval required" (IN_APP; no web push
needed).

## Security

Mobile shares desktop boundaries exactly: same gates, same
exact YES, same validation. Tested: fake notification/
mission/approval/entity IDs, unauthorized + replayed YES,
malformed packet, oversized input, hostile content (escaped
on render), traversal, unknown camera ids.

## REAL / TEST / SIMULATED / UNAVAILABLE

REAL: dashboard, triage, deeplinks, camera counts, packet
handoff, guide/craft/symbiosis/nodes/progress panels,
IN_APP notifications. TEST: synthetic adapters (labeled).
SIMULATED: printers (unchanged). UNAVAILABLE: web push,
Insta360 live transport, native upload, STT.
