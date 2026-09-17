# Camera Workflow (BIG #30)

CAMERA → CONNECT → SOURCE → SNAPSHOT → OBSERVATION → INVENTORY → ANALYSIS.

Cameras are observation sources, never actuators. Every step shows
honestly what works.

## What exists (REAL)

- Registration (`POST /api/v1/cameras/register`, `/web/cameras/register`)
- Read-only local device scan — names only (`GET
  /api/v1/cameras/detected`)
- Snapshot ingest pipeline (`POST /api/v1/cameras/{id}/ingest`) with
  hash/size caps → media record → file-proposal payload
- Observation store (`GET /api/v1/cameras/{id}/observations`)
- Availability probe (`GET /api/v1/cameras/{id}/availability`)
- Local VLM analysis as advice (Ollama loopback / test / unavailable
  providers); observation ≠ fact until a gated write + verification.

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
