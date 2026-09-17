# Desktop Agent Hands (BIG #22) — IMPLEMENTED

Mycelium is the brain, the desktop agent is the hands:
chat → mission → approved plan → desktop step →
desktop approval where required → claim → revalidate →
mouse/keyboard action → screenshot/observation →
result → mission loop → next step. Proven end to end
over real localhost HTTP with the real Windows backend
(screenshots verified byte-for-byte as 24-bit BMP).

## What runs where

- Coordinator: propose → approve (exact YES) → atomic
  dispatch with lease (300s) + attempt counting (max 3)
  → revalidation reads → result intake → mission
  continuation → verification → memory. Never input.
- Agent process (`python -m desktop_agent.main`):
  register → heartbeat → claim → revalidate (status +
  owner + lease + params, fail-closed) → observe →
  act → observe → report. Full capabilities, `--once`,
  `--read-only` and `--dry-run` modes; stops between
  actions, never mid-action.

## Lease, failure, recovery

- Dispatch stamps `lease_until` + `attempt_count`;
  re-dispatch past 3 attempts refuses.
- `expire_desktop_leases()` runs lazily on every claim:
  expired → approved while attempts remain (re-claim
  allowed), blocked when exhausted. Late reports still
  win their own conditional-update race.
- Agent revalidation blocks on expired leases; operator
  cancel revokes between actions; coordinator loss
  backs off; step limits bound every run.
- Mission loop reports `waiting_agent` while dispatched
  and continues after the result lands.

## Boundaries (unchanged, tested)

- Only allow-listed ComputerActions (screenshot, wait,
  move/click/scroll, type/key/hotkey); unknown types,
  out-of-range coordinates and shell-like actions
  refuse at validation.
- Mission approval never auto-approves desktop input;
  every input action needs its own exact YES.
- Physical actions are impossible through this chain:
  no printer/robot/drone path exists here, and the
  generic executors refuse them (HARDWARE_REQUIRED).
- Tokens/hashes never appear in nodes, status,
  actions or logs (tested).
- No shell, subprocess, code execution, cloud or
  inbound ports anywhere in the loop.

## Real vs simulated

- REAL on Windows: screenshots (GDI BitBlt → local
  BMP, retention-capped), mouse move/click/scroll,
  keyboard type/press/hotkey, active-window title —
  stdlib ctypes only, no new dependency. Verified:
  1920×1080 capture in ~0.15s, no-op cursor move,
  full claim→screenshot→report→mission-completion
  over live HTTP with zero desktop disturbance.
- Click/type/keypress paths execute ONLY from
  approved + dispatched actions in production; the
  smoke deliberately used screenshot steps so no
  real input landed. DryRun backend validates but
  executes nothing (tests default to fakes).
- Task-queue `expire_leases` remains uncalled in
  production (pre-existing; documented future work —
  assigned tasks with dead nodes wait for it).
