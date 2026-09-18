# Camera Ecosystem (BIG #34)

Camera input is a first-class entrance to the living
Mycelium ecosystem — never an authority. The chain:

FILE → INGEST SESSION → OBSERVATION → VLM (or honest
fallback) → CANDIDATE → POSSIBLE MATCH → LINK PROPOSAL
(YES) → SYMBIOSIS → CRAFT → GUIDE → MEMORY (only through
the existing truth flow) → MORNING / ACTIVITY / WORLD.

## Multi-file ingest sessions (REAL)

`POST /api/v1/camera-sessions` (`device_id` + up to 8 inbox
filenames) creates a `cing_…` session; `POST
/api/v1/camera-sessions/{id}/run` ingests every file through
the existing `FileIngestAdapter` validation (plain filename,
inside the camera dir, known suffix, capped size). Each file
gets an `obs-…` observation; states per item: `queued`,
`observed`, `duplicate`, `refused`. Dedupe is by sha256
across recent sessions: replays refuse as duplicates and
never create a second observation. Sessions live in the
additive `camera_ingest_sessions` table (chat DB, JSON dump
pattern like `vision_analyses`). No video is ever processed
whole — the operator extracts stills first.

## VLM layer (REAL / UNAVAILABLE)

`POST /api/v1/observations/{id}/describe` tries the local
Ollama loopback provider (`qwen3-vl:4b` default, loopback
only, no downloads, no cloud). Success stores a structured
analysis (labels, confidences, description, uncertainty) and
reports `vlm_state: REAL`. When the backend is unreachable
the call does NOT fail: it stores an extractive fallback
(media facts only, empty labels, `model: ""`, explicit
uncertainty) and reports `vlm_state: UNAVAILABLE`. The two
are distinguishable in storage, and the fallback never
claims a VLM ran.

## Observation → candidate (REAL, gated)

`POST /api/v1/observations/{id}/propose-candidates` turns
each REAL VLM label into one `observation`-type knowledge
candidate (suggested name, model confidence, evidence bound
to the observation, sensor/ai provenance). Idempotent per
(observation, label); fallback analyses yield nothing. No
auto-promotion: candidates mature through support → YES →
memory in `/knowledge` exactly like every other candidate.

## Entity matching (POSSIBLE MATCH, never merge)

`GET /api/v1/camera-match?q=…` returns bounded substring
evidence over inventory objects/projects/ideas. `POST
/api/v1/camera-suggest-link` (`observation_id`, `entity_id`,
closed predicate set: `used_in`, `component_of`,
`related_to`, `stored_at`, `supports`, `evidence_for`,
`part_of`) creates a `connection` candidate that surfaces
as PROPOSED in the symbiosis layer (`/symbiosis`). YES / NO
/ REVIEW run through the existing knowledge flow.

## Craft, guide, timeline, notifications

Camera observations already flow into world-graph overlays,
so `/craft` picks them up (present ✓ / missing ? /
uncertain ○ via gaps). The guide gains camera items
(inbox files, undescribed observations). `GET
/api/v1/camera-timeline` reads the shared bus (no second
event system). IN_APP notifications (`new_observation`,
`camera_ready`, `candidate_waiting`, `new_connection`) fan
out to registered nodes only; WEB_PUSH stays UNAVAILABLE.

## Insta360 status

REAL: registration, file ingest, metadata, sessions,
analysis of provided files. UNAVAILABLE: direct live
transport, camera control, proprietary protocol — until a
reviewed adapter exists. REGISTERED is never CONNECTED.
The Camera Guide on `/cameras` shows the 8-step file path.

## What Jelles does tomorrow

1. Register the X4 on `/cameras` (source `insta360`).
2. Shoot, export a still, copy it into the inbox
   (`GET /api/v1/camera-inbox` lists names).
3. Run a session from the camera detail page.
4. Describe (VLM), propose candidates, review.
5. YES keeps one; suggest a link to the solar project.
6. Watch it appear in symbiosis, craft, guide, morning.
