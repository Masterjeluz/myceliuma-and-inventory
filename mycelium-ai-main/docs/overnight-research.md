# Overnight Research (BIG #31)

Explicit mode, bounded queue, honest mornings. The coordinator's
background scheduler runs only fixed read-only status jobs; the
research queue is worked by an explicit trigger — Jelles or n8n
cron. No scheduled job executes queued research.

## Mode

`GET /api/v1/mode` → `{mode: DAY|OVERNIGHT, ...}`.
`POST /api/v1/mode` / `POST /web/mode` (from `/morning`) switches.
OVERNIGHT means: safe research, analysis and reports may proceed.
It never means: physical acts, desktop input, publishing, external
messages, approvals — those stay human, always.

## Queue

- `GET /api/v1/research/queue` — drafts/blocked/failed runs with
  `priority` (HIGH/MEDIUM/LOW, default MEDIUM), ordered by
  priority then age, plus current mode.
- `POST /api/v1/research/queue` — `{question, priority, provider,
  max_sources≤10, objective, project_ref}` creates a draft run.
  Nothing fetches yet.
- `POST /api/v1/research/queue/run-once` — executes the top draft
  once through the real engine (`_execute_research_run`, same
  bounds as interactive runs). Returns `{ran, run_id,
  dossier_id}` or an honest `{ran: false, reason}`.

## Morning

`/morning` opens with GOOD MORNING + the current mode + an
Overnight panel (open research questions from fresh dossiers;
honest empty state when nothing ran). The rest of the report is
unchanged. If nothing happened overnight, it says so — never
fake activity.

## Distributed research (status)

Routing, missions with research steps, and node capability
adverts exist; `node_client` today only executes `system_inventory`
and `desktop_screenshot`. Research work on Linux nodes is
architecture-ready but FUTURE — the queue runs on the coordinator
until node executors are reviewed.
