# Health (BIG #11-15, Phase 2) — IMPLEMENTED (tracking only)

Personal tracking and trends. This is not a medical
engine: no illness assessment exists anywhere in the
module, no hidden score, no medical claims.

## Measurements

Closed metric list (sleep, steps, activity, training,
recovery, hydration, meals, weight/BMI/waist/hip,
energy, stress, heart rate, calories) with per-metric
plausibility bounds. Six source adapters: manual,
wearable, sensor, inventory-derived, external,
file-import. Every row carries source + provenance;
wearable/external values are marked, never trusted.
Dedup on metric/source/moment.

## Personal Health Index

Transparent per-dimension ratios (sleep, activity,
recovery, hydration, nutrition, body, habits, training
consistency) with raw values, calculation method,
missing-data counts and completeness on every
dimension. The overall is a plain mean of available
dimensions, labelled with coverage. Gaps render as
"no data", never as zero.

Health data reaches Live/AI only through the explicit
`health.read` capability plus an `include_health` scope
flag. Real wearable integrations beyond the Garmin mock
are FUTURE.
