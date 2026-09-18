# Camera Workflow (BIG #31: file ingest is REAL)

CAMERA → CONNECT → SOURCE → SNAPSHOT → OBSERVATION → INVENTORY → ANALYSIS.

Cameras are observation sources, never actuators. Every step shows
honestly what works.

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
