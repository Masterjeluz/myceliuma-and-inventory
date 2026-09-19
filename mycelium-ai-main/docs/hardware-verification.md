# Hardware verification (BIG #42)

Human-controlled trust for node/device claims. Trust levels
(see `nodes.hardware_trust`):

- ADVERTISED — the node said so. Default, never a fact.
- OBSERVED — connected + fresh telemetry (<300s). Derived.
- VERIFIED — a live row in the hardware-links store with status
  VERIFIED. **No automated path may ever derive it.**

## Flow

1. PROPOSE — anyone: `POST /api/v1/hardware/links`
   (human_ref, node_id, device_ref, kind, capability, evidence).
   The row always starts PROPOSED. Proposing verifies nothing.
2. VERIFY — operator key only:
   `POST /api/v1/hardware/links/{id}/verify`
   (verified_by + operator_key). Node credentials are never
   accepted here, so a device cannot self-verify.
3. REVOKE — operator key only:
   `POST /api/v1/hardware/links/{id}/revoke`. REVOKED sticks:
   re-verification is refused (422).

## Rules

- VERIFY requires status PROPOSED + a non-empty human
  verified_by. Re-verifying an already-VERIFIED link is a
  no-op returning the link; verifying a REVOKED link refuses.
- Audit trail: `hardware.linked` / `hardware.verified` /
  `hardware.revoked` bus events name human, node, device —
  never secrets.
- The `/nodes/{id}/reality` endpoint overlays VERIFIED only
  when a live VERIFIED link names that exact node + device
  ref. `hardware_trust()` itself can never return VERIFIED
  (asserted in tests).
- Unknown nodes cannot be linked (404). Fake link ids 404.
  Empty/unknown statuses refuse (422). Everything fails closed.

## Surfaces

`/hardware` page, nodes reality, guide (unverified-GPU/camera
items → /hardware), presence `hardware_unverified` (waiting),
morning HARDWARE section (only when links exist), packet-v2
hardware block (verified counts per node), overview `hardware`.
