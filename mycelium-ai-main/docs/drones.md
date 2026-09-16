# Drones (BIG #11-15, Phase 5) — PARTIAL (model + gates IMPLEMENTED)

Capabilities (observe/photograph/video/navigate/
position/return_home/land), safety state and
missions as data. No drone SDK, no autonomous
flight without a safety architecture: autonomous
missions additionally require a named geofence, an
altitude cap (≤120m) and human approval — anything
less refuses at proposal time.

Physical flight is HARDWARE_REQUIRED (FUTURE).
Unrestricted autonomous flight is explicitly out
of scope until the safety architecture exists.
