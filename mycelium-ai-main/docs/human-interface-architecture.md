# Human Interface Architecture (BIG #9)

The living-workshop interface: how Jelles talks to Mycelium —
by text, by voice, from a phone browser — without ever
creating a second coordinator.

```
Human
  ↓ text / voice / phone browser
Interface Adapter (envelope + session, no decisions)
  ↓ converged conversation turn
Mycelium Coordinator (chat → advice → proposal → approval)
  ↓ mission / task / BIG #8 routing
Node (pull-only, capability-gated)
  ↓ result / observation
Coordinator (verification, events)
  ↓ text / spoken / notification rendering
Human
```

Two sentences that never mix:

- **The human interface is not a second coordinator.**
  Adapters carry turns; they decide nothing, execute nothing,
  approve nothing.
- **Voice recognition is not authorization.** Transcription
  is interpretation input; only a bound, unexpired, exact
  approval word on exactly one pending request resolves —
  and never for physical execution.

## Interface layer (`interface.py`)

`InterfaceAdapter` contract with `TextInterface` (real) and
`VoiceInterface` (architecture: transcribed text in, reply
text out; no microphone/speaker coupling). `InterfaceMessage`
envelopes converge voice and text as early as possible: after
STT a spoken turn IS a text turn with voice provenance.
Closed input/output types, capped content, no executable
content. `InterfaceSession` tracks presence (active/idle/
expired/revoked, 24h default, 7d cap) — sessions are not
credentials and never double as node identity.

## Voice (`voice.py`, `voice_approval.py`)

STT: `SpeechToTextProvider` with `LocalSTTProvider` (loopback
backend, configured never installed), `UnavailableSTTProvider`
and deterministic `TestSTTProvider`. TTS mirrors it
(`TestTTSProvider` writes a local marker file).
Transcription carries sensor-observed/unverified provenance;
confidence is informational and flows into no gate.

Audio security: one local root (`mycelium-audio`), plain
filenames (`.wav`/`.mp3`/`.ogg`), boundary checks, 25 MiB
cap, retention of 5, explicit delete. No upload, no cloud, no
public URLs, no background recording — capture sessions
(`cap-*`) open explicitly, bounded in time, close explicitly,
and only on nodes advertising `phone.microphone.read`.

Voice approval (`voice_approval.py`): spoken words resolve
only with exactly one pending request, unexpired, target
still pending with unchanged binding, exact YES/NO word —
otherwise refusal (retryable for a non-matching transcript
only). `physical` kinds can never resolve by voice; the
existing exact-YES dialect and fingerprint rules are reused,
and on YES the EXISTING decide path runs (no second
framework).

## Phone as node

Phones register through the normal BIG #8 node flow (stable
id, token, heartbeat, freshness, disabled state) with the
closed `phone.*` capability set (screen, notification,
camera, microphone, speaker). Roles stay explicit:
capabilities authorize, device type never implies permission.
Phone cameras register as `source=phone` devices and capture
through the existing ingest path; phone notifications are
informational records. Pull-only: the phone polls heartbeat,
events and notifications; no inbound ports, no port
forwarding, no public server.

## Events + notifications (`events.py`)

Bounded structured bus (`conversation.message`,
`mission.*`, `task.*`, `observation.created`,
`approval.required/resolved`, `node.*`, ...) with cursor
polling (`GET /api/v1/events?after=`), type filter and
retention. Payloads are small capped dicts; executable keys
(command/exec/url/approved/...) refuse. Notifications are
recipient-bound, expiring, markable-read — reading one
performs nothing. An event is never a command and can never
approve or execute.

## Realtime + status

Polling is the transport (`/events`, `/notifications`,
`/status`); no SSE/websocket/Redis was needed. `/api/v1/
status` returns counts and states only — no secrets, no
dumps, no paths. The mobile page (`/mobile`, responsive,
server-rendered, no framework) shows chat, status, missions,
approvals, notifications and nodes for a phone browser on
the LAN. The desktop chat page gained a compact live panel;
no redesign.

## Chat + routing convergence

Text and voice turns run the same `chat()` (provenance marks
voice origin; counts and sources unchanged when no options
are passed). "Analyseer wat er op mijn bureau ligt" flows:
chat → camera/vision requirements → BIG #8 routing → node
claim → observation → VLM → answer, with writes only
through controlled approval. Task detail
(`/tasks/by-id/{id}`) exposes assignment + routing
explanation so chat can describe where work goes and why.

## Provenance

voice input → STT provider/model → message → advice/proposal
→ approval → task → node → executor/model → result →
verification; TTS renders response text with its own
provenance. Nothing here is ever auto-`human_verified`.

## Privacy

Audio and transcripts stay local; media by reference only in
context; absolute paths redacted where existing redaction
applies; no background capture; no hidden activation;
explicit expiry for audio; sessions carry no credentials.

## Limitations (honest)

- No real STT/TTS backend ships (loopback contract only);
  no microphone/speaker hardware touched by the coordinator.
- No native app, no push infrastructure, no always-on
  microphone, no continuous camera streaming.
- Voice approval covers write/mission/desktop kinds only;
  physical approval stays fully manual.
- Sessions are presence, not auth; tokens stay the node
  credential (BIG #8, reused unchanged).
