# Agenda import (local-first)

No Google Calendar required. Paste `.ics` text at `/agenda`,
preview it, confirm it. Events become read-only world/context
data with source provenance — never commitment facts.

## Flow

```
AGENDA → plak .ics → Preview → Bevestig import → events
```

- `POST /api/v1/agenda/import {"preview_only": true}` parses
  and returns up to 50 events without storing anything.
- `preview_only: false` stores with UID dedup: re-importing
  the same label reuses the source row; same-UID events
  update instead of duplicating.
- `GET /api/v1/agenda/events` / `/sources` — read-only lists.
- `GET /api/v1/agenda/events?upcoming_only=true` feeds the
  morning report and the “agenda” command.

## Parser

Stdlib-only, bounded (500k chars, 500 events): unfolding,
VEVENT blocks, SUMMARY / DTSTART / DTEND / LOCATION /
DESCRIPTION / UID / RRULE. Missing UIDs get a deterministic
`derived-` id labelled as derived. Malformed input refuses
instead of guessing; nothing is ever invented.

URL-based ICS feeds are intentionally NOT fetched by the
coordinator (no arbitrary network destinations). Paste or
upload the text instead; later n8n transport can poll an
explicitly configured feed.

## Project ↔ agenda ↔ mission

Agenda rows may be shown as context next to projects and
missions (e.g. an “UMZ wedstrijd” event beside the OZFK
project). Links are explicit and provenance-carrying; personal
commitments are never inferred as facts.
