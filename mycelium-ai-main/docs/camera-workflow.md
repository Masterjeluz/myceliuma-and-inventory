# Camera Workflow (BIG #34: sessions + VLM honesty + candidates)

CAMERA → CONNECT → SOURCE → SNAPSHOT → OBSERVATION → INVENTORY → ANALYSIS.

Cameras are observation sources, never actuators. Every step shows
honestly what works. Full chain in `docs/camera-ecosystem.md`.

## What exists (REAL)

- Registration (`POST /api/v1/cameras/register`, `/web/cameras/register`)
- Per-camera detail page (`/cameras/{id}`): identity, source,
  connection state, capabilities, last observations, inbox, actions
- **File ingest** (`POST /api/v1/cameras/{id}/ingest-file`,
  `/web/cameras/{id}/ingest-file`): the operator copies Insta360 /
  phone / USB files into the camera dir (inbox listing at
  `GET /api/v1/camera-inbox`); `FileIngestAdapter` turns one named
  file into an observation + inert File payload. Provenance says
  file-ingest explicitly — never a live capture. Traversal,
  missing files and oversized media refuse fail-closed.
- Read-only local device scan — names only (`GET
  /api/v1/cameras/detected`)
- Observation store (`GET /api/v1/cameras/{id}/observations`)
- Availability probe (`GET /api/v1/cameras/{id}/availability`)
- Local VLM analysis as advice + inert object/file proposals
  (`POST /api/v1/vision/analyze`, `/api/v1/vision/propose`) feeding
  the existing approval flow: OBSERVATION → CANDIDATE → HUMAN
  REVIEW → INVENTORY.
- Observations carry "Review as candidate" buttons (detail page,
  API `POST /api/v1/observations/{id}/candidate`): a photo becomes
  a knowledge candidate with sensor provenance, maturing through
  `/knowledge`. The Insta360 requirements stay documented on the
  adapter (`requirements()`) and the detail page.
- **Multi-file sessions** (`POST /api/v1/camera-sessions`,
  `.../run`): up to 8 inbox files per `cing_…` session, sha256
  dedupe across sessions, per-file states, timeline from the
  shared bus. Detail page shows sessions, per-observation
  Describe (VLM) / Propose-candidates buttons, link proposals,
  timeline.
- **VLM honesty** (`POST /api/v1/observations/{id}/describe`):
  REAL Ollama analysis when the loopback backend answers,
  extractive fallback (`vlm_state: UNAVAILABLE`, no labels)
  otherwise — stored distinguishably, never faked.
- **Candidates from labels**
  (`POST /api/v1/observations/{id}/propose-candidates`):
  one idempotent candidate per REAL label; fallback yields none.
- **Possible matches** (`GET /api/v1/camera-match`) and **link
  proposals** (`POST /api/v1/camera-suggest-link`, closed
  predicates) surfacing as PROPOSED symbiosis; YES/NO/REVIEW
  through `/knowledge`.
- Guide feeds on inbox + undescribed observations; mobile
  shows the camera add → processing → review flow; IN_APP
  notifications (`new_observation`, `camera_ready`,
  `candidate_waiting`, `new_connection`) to registered nodes.

## What is missing (UNAVAILABLE)

Live Insta360 transport. The `Insta360Adapter` is an explicit
unavailable foundation: identity/candidate matching only, capture
refused until a reviewed transport lands (webcam-driver or
file-ingest path). No SDK steps are invented.

## What Jelles needs to do

1. Register the camera on `/cameras` (source `insta360`, kinds
   `snapshot,webcam,stream,p360` for an X4-class device).
2. State stays REGISTERED until an adapter proves CONNECTED;
   otherwise the UI shows UNAVAILABLE — never fake-connected.
3. Ingest a file snapshot to create an OBSERVATION, then propose an
   INVENTory write through the existing approval flow; the world
   graph shows it as a sensor-observed overlay, never as truth.

Per-camera detail lives behind the JSON endpoints linked from
`/cameras` (identity, source, connection state, capabilities, last
observation/snapshot, available actions).
