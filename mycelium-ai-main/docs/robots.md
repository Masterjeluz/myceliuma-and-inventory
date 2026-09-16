# Robots (BIG #11-15, Phase 5) — PARTIAL (model + gates IMPLEMENTED)

Robots are allow-listed capability holders
(robot.move/observe/grab/place/speak/navigate/stop/
status — no wildcards, no custom capabilities) with
an explicit safety state (safe/supervised/locked/
estop/unknown) and a node/location binding.

Flow as data: intent → plan → simulation note →
proposal → human approval → telemetry → independent
observation → verification. Physical actions need
safe|supervised state plus approval; locked/estop
refuse; only idle robots take work; telemetry alone
never verifies. Physical execution against real
hardware is HARDWARE_REQUIRED (FUTURE) — nothing
here moves, and nothing pretends to.
