# n8n workflows (test-only, localhost)

Importable n8n workflow JSON for the Mycelium integration
plane. No secrets in these files: HTTP auth reads
`$env.MYCELIUM_N8N_KEY` (set `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`).

- `workflow-a-schedule-morning-report.json` — daily 07:00
  schedule → POST /api/v1/integrations/trigger
  (morning_report, date-stable run_key).
- `workflow-b-outbox-notify.json` — every 5 minutes poll
  /api/v1/integrations/outbox → local log → ack loop.

Runbook: free ~2 GB disk, scoped install
(`npm install n8n` in a temp dir, never global), start
with `N8N_USER_FOLDER` in temp plus
`N8N_HOST=127.0.0.1 N8N_PORT=5678`, no tunnel, import via
`n8n import:workflow --input=<file>`, paste the
integration key (issued by Mycelium) into
`MYCELIUM_N8N_KEY`, execute manually once before
activating schedules. Full detail: `docs/n8n-integration.md`.
