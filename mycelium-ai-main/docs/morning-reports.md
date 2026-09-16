# Morning Reports (BIG #11-15, Phase 1+) — IMPLEMENTED

One deterministic engine (`reports.py`): Report → blocks →
evidence → entity links → actions/proposals. Same inputs,
same report. Fifteen independent sections, each loading on
its own, none dumping context:

today, health, recovery, projects, tasks, missions,
skills, inventory, workshop, research, fabrication,
devices, findings, suggestions, fun.

Health/recovery sections appear only when health data
exists; nothing is invented to fill them. Served at
`GET /api/v1/reports/morning` and rendered mobile-first
on `/morning`. A scheduled `morning_report` job builds the
same structure.
