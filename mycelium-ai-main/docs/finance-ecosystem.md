# Finance ecosystem (BIG #42)

Minimal, first-class finance records. This is NOT accounting
software: just enough to make money a real ecosystem entity.

## Model

- Kinds (closed): `income` | `expense` | `budget`.
- Status (closed): `DRAFT` → `CONFIRMED` | `ARCHIVED`.
- Amounts are minor units + 3-letter currency. **Omitted
  amounts stay NULL and render as UNKNOWN — never zero,
  never invented.**
- Every record carries `project_ref`, a note, and human-recorded
  provenance (`human_verified=False`; recording is not
  verification).

## Rules

- No fake records: rows exist only through the explicit API
  with operator-supplied figures.
- Privacy: amounts live ONLY in the finance store, its
  dedicated endpoints, and the scoped `/finance` page.
  Generic packets carry counts; amounts enter a packet ONLY
  when its `project_id` matches the record's `project_ref`
  (asserted in tests). Telemetry never carries finance data.

## Symbiosis

Prefixes `fin_` + closed predicates `funds` / `funded_by` /
`allocated_to` (strict at proposal input, `related` display
fallback for unknown stored verbs). Never merges entities.

## Surfaces

`/finance` page + API, `finance_pending` presence items
(DRAFT rows, waiting band), guide finance/energy items,
morning FINANCE section (only when records exist), overview
`finance` (counts + unknown-amount count), packet-v2 scoped
finance block, mobile finance panel (counts only).
