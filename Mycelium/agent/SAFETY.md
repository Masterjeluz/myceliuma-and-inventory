# SAFETY — Milestone 2A

Local-first safety contract for the Mycelium Desktop Agent. This milestone adds
an explicit permission gate and a local Git checkpoint capability. It does not
integrate with or modify any existing user project.

## Permission model

`permissions.request_permission(action, target, details)` returns a
JSON-serialisable approval decision.

- **Default is DENY.** No approval is granted by omission, timeout, exception,
  or an unrecognized response.
- A human must explicitly type the exact response `YES` through an interactive
  caller (`request_permission_interactive`) or an explicitly supplied input
  callback. Any other response is a denial.
- The prompt always states the action, target, and reason.
- An optional approver callback is an explicit integration point for a UI/CLI;
  it must return exactly `True` to approve. It is never an implicit policy grant.
- Every request and decision is appended as one JSON line to
  `agent/permission_log.jsonl` (or a caller-supplied log path) with:
  - UTC `requested_at` and `decided_at`
  - unique `request_id`
  - action, target, details, reason
  - approved/denied decision and response
  - `provenance.source = mycelium-desktop-agent:permission`
  - `provenance.default = deny`
- A denied request performs no action. A caller must inspect the returned
  decision before doing anything.

The gate is intentionally separate from discovery/indexing. Read-only scan and
index operations do not require permission; mutating capabilities do.

## Checkpoint model

`checkpoint.create_checkpoint(repository, approval, ...)` implements:

`INSPECT → SHOW → PERMISSION → CHECKPOINT → MODIFY → TEST → VERIFY`

For this milestone, `INSPECT`, `SHOW` (the inspection returned to the caller),
`PERMISSION`, and `CHECKPOINT` are implemented. `MODIFY`, `TEST`, and
`VERIFY` remain future workflow stages and are not performed by this module.

Before a checkpoint is created:

1. Resolve and inspect the local repository.
2. Read Git status with untracked files included.
3. Require a clean work tree and an existing HEAD.
4. Require an explicit, matching approval for action
   `create_git_checkpoint` and the exact repository target.
5. Re-inspect after permission and immediately before commit; any status or
   HEAD change aborts the checkpoint.
6. Create one local empty commit with a generated or supplied message.
7. Re-inspect and return the previous HEAD, new checkpoint ID, inspection
   records, approval, and provenance.

Only local Git read operations and the single approved local `commit` are
allowed. The checkpoint command disables GPG signing and hooks for this
controlled checkpoint (`-c commit.gpgsign=false --no-verify`), and never invokes
network or destructive Git operations.

## Explicitly forbidden actions

This layer never performs, schedules, or silently permits:

- `git push`, including force push
- `git reset` or any history rewrite
- `git clean`
- `git rm` or deletion
- `git stash` (even though it is not destructive by itself)
- checkout/branch switching
- fetch/pull or any network operation
- automatic commits without a matching permission decision
- operations outside the explicitly approved repository target

Future mutating skills must call the permission gate independently and must not
reuse a checkpoint approval for a different action or target.

## Test boundary

Checkpoint tests create repositories only under pytest `tmp_path` directories.
They verify clean/dirty detection, permission denial/approval, commit parent and
message, race detection, command allow-listing, provenance logging, and that no
real project path is touched. No test uses Desktop, Documents, Downloads, or a
canonical user repository as its target.

## Current boundary and next step

M2A is a safety primitive, not an execution framework. It does not modify
tracked user projects, does not integrate with INVENTory, and does not add an
AI model or API. M2B must add the Desktop `stable_id` → INVENTory `proj_`
mapping and a dry-run import policy before any project data is written to the
world model.
