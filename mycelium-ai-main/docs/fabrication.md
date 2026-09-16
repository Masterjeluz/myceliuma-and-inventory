# Fabrication (BIG #11-15, Phase 4) — PARTIAL (gates IMPLEMENTED)

Prepares everything, starts nothing by itself. Spool
tracking, deterministic printer selection (capability
match, explicit preference, lowest id on ties — never
a "better" claim), filament estimates with the method
shown, and staged pipeline plans are IMPLEMENTED.
The physical start path (print proposal → exact YES →
revalidated execution → telemetry + camera
verification → INVENTory via BIG #5) is unchanged
and mandatory.

Real slicer runtimes and printer transports stay
FUTURE (test-slicer and simulated adapters only);
adding one must document why, license, offline
behaviour, security impact and fallback.
