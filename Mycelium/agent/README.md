# Mycelium Desktop Agent

Local-first desktop agent for the Mycelium + INVENTory ecosystem.

Core loop:

DISCOVER → UNDERSTAND → PLAN → ASK PERMISSION → BUILD → TEST → CHECKPOINT

Safety principles:

- Never delete or move user files without explicit permission.
- Never execute destructive commands without explicit permission.
- Inspect before modifying.
- Create a Git checkpoint before modifying tracked projects.
- Run tests after code changes.
- Keep provenance for discovered information.
- Prefer existing code/projects over rebuilding from scratch.
