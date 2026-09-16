# Garmin (BIG #11-15, Phase 2) — MOCK (live UNAVAILABLE)

Honest states only. The adapter interface, the mock
provider and the import pipeline are IMPLEMENTED; live
Garmin data is UNAVAILABLE (no credentials, no reviewed
live transport) and the module refuses to fetch.

## Import pipeline

`fetch (cursor page) → map (Garmin type → health metric)
→ dedupe (metric/source/moment) → store as health
measurements (source=wearable,
provenance=external-source/imported with provider ref)`.
Cursor paging, bounded pages, retryable, rate-limit
aware (the mock enforces a call budget).

States: UNAVAILABLE (default) / AUTH_REQUIRED (a token is
set but no live transport exists) / MOCK (deterministic
synthetic samples, labelled everywhere) / CONFIGURED
(reserved for a future reviewed transport).

A real integration needs: user-owned OAuth against an
official Garmin API, token storage outside the DB,
mapping review — then the same import function serves
it unchanged.
