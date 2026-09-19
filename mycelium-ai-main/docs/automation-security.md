# Automation Security (BIG #38)

Threat model, mitigations, and security invariants for the
living automation engine.

## Threat Model

Automation runs untrusted step definitions (from templates or
web forms) and drives them through existing functions. The
attacker controls:

- Step kinds and params (via `POST /api/v1/automation/runs` or
  `POST /web/automation/from-template`)
- Template arguments (goal, conversation_id)
- Conversation content (imported chats)
- Research questions and objectives

The attacker **cannot**:
- Execute arbitrary code (no shell, no eval, no exec)
- Bypass human gates (gates re-read live stores)
- Fabricate approvals (resume re-checks every time)
- Access secrets (redacted at import, never in payloads)
- Write to INVENTory without exact YES
- Spawn background threads
- Escalate capabilities beyond nodemesh allow-list

## Defense in Depth

### 1. Closed Step-Kind Allow-List (Creation + Drive)

```python
SAFE_STEP_KINDS = frozenset({
    "observe", "readout", "search", "research_queue",
    "research_execute", "conversation_analyze", "intel_analyze",
    "knowledge_candidate", "symbiosis_propose", "craft_update",
    "context_packet", "notify", "mission_tick", "mission_propose",
    "write_propose", "fab_prepare", "node_prepare",
    "camera_session", "wait",
})
```

Any other kind → `AutomationRefusedError` at creation AND at
drive time. Default-deny.

### 2. Overnight Subset

```python
OVERNIGHT_SAFE_KINDS = frozenset({
    "observe", "readout", "search", "research_queue",
    "research_execute", "conversation_analyze", "intel_analyze",
    "knowledge_candidate", "symbiosis_propose", "craft_update",
    "context_packet", "notify", "wait",
})
```

Overnight runs refuse mission ticks, proposals, fabrication,
camera, node prep.

### 3. Param Validation (Creation Time)

- Depth-limited recursive cleaning (≤3, covers mission steps)
- Text/number/bool/short list (≤10)/shallow object (≤12 keys)
- String values truncated to 2000 chars
- Step params limited to 12 keys
- Run steps limited to 20

### 4. Kind-Specific Static Checks

| Kind | Checks |
|------|--------|
| `node_prepare` | task_kind in allow-list, capability prefixed, no wildcard |
| `craft_update` | entity_id validates via `clean_entity` |
| `symbiosis_propose` | predicate in closed set, two valid entities |
| `mission_tick` | mission_id format or empty (resolves from draft) |
| `mission_propose` | goal required, steps read-only kinds only |
| `write_propose` | mutation_type in allow-list, target required, payload ≤12 keys, secret scan |
| `knowledge_candidate` | kind in allow-list, title+text required, health regex blocks |
| `camera_session` | op in {run, describe, propose} |
| `fab_prepare` | op in {prepare, slice, propose}, job_id required |
| `research_queue` | question required, priority in {HIGH, MEDIUM, LOW} |
| `research_execute` | run_id format `res_*` |
| `observe`/`readout` | source in allow-list |

### 5. Gate Validation (Creation + Live Re-Check)

```python
GATE_TYPES = frozenset({
    "mission_approved", "write_approved", "desktop_decided",
    "candidate_advanced", "research_completed", "time_elapsed",
})
```

Gate ref required (except `time_elapsed`). `write_approved`
carries fingerprint for extra integrity.

### 6. Live Gate Re-Check (Resume)

`check_gate_live()` re-reads the authoritative store:

- `mission_approved` → loads mission, checks status + approver
- `write_approved` → loads proposal, checks status + human decider
- `desktop_decided` → loads desktop action, checks status + decider
- `candidate_advanced` → loads candidate, checks state
- `research_completed` → loads run, checks dossier/status
- `time_elapsed` → wall clock compare

Missing records → unmet. Exceptions → unmet (fail-safe).

### 7. Secret Redaction

- Import: credential-like text redacted in conversation bridge
- Payloads: `_SECRET_HINTS` scan (token, secret, password,
  api_key, bearer, credential, private_key, client_secret)
- Packets: reuse existing redaction in `context_packet.py`
- Nodemesh: capability hints only, no secrets in task payloads

### 8. Health Isolation

`knowledge_candidate` and `symbiosis_propose` both run
through `candidate_from_finding` path which applies the
health regex (`_HEALTH_RE`) — health-related text **never**
becomes a candidate, even if automation tries.

### 9. No Shell / RCE Surface

Static analysis asserts no:
- `subprocess`, `os.system`, `os.popen`
- `eval(`, `exec(`, `__import__`
- `socket`, `urllib`

All execution goes through existing, audited functions.

### 10. Capability Escalation Refused

`node_prepare` validates:
- `task_kind` ∈ `ALLOWED_TASK_KINDS`
- `capability` starts with `ALLOWED_CAPABILITY_PREFIXES`
- No `*`, no oversized strings

### 11. Path Traversal Refused

`craft_update` and `symbiosis_propose` entity IDs validated
through `clean_entity()` which rejects `..`, `/`, `\`,
control chars.

### 12. Prompt Injection Containment

Injected text in conversation imports:
- Stored as-is (escaped on render)
- Analyzed by deterministic extractive engine (no LLM)
- Can become candidate text (labeled `ai-generated`,
  `human_verified=False`)
- **Cannot** approve, execute, verify, or change truth
- Test: `test_injection_never_executes` verifies

### 13. Provenance Discipline

Every automation-created record carries:
```python
Provenance(
    source_type="ai-generated",
    creator_id=f"automation:{run_id}",
    human_verified=False,
    notes="automation proposal; support/promote stay human"
)
```

Health content forces `human_verified=False` even if
someone tries to hand-set it.

## Invariants (Tested)

- `test_create_rejects_garbage`: closed kinds, bounds, gates,
  secrets, overnight, templates
- `test_health_never_becomes_candidate`: health regex blocks
- `test_stale_approval_never_wakes`: resume re-reads live
- `test_mission_tick_refuses_unapproved`: tick only in approved
- `test_write_prepare_then_human_yes_then_resume`: proposal →
  exact YES → resume
- `test_bounds_stop_runs`: max_steps, max_consecutive_failures
- `test_capability_escalation_refused`: wildcard, bad task_kind,
  path traversal, bad predicate
- `test_no_shell_surface_and_states_honest`: static scan +
  gate honesty
- `test_injection_never_executes`: hostile content contained

## What Jelles Approves

Every consequential step waits with an explicit gate:
- Mission approval → `/api/v1/missions/{id}/approve` (exact YES)
- Write approval → `/api/v1/writes/{id}/approve` (exact YES)
- Desktop action → `/api/v1/desktop/{id}/approve` (exact YES)
- Candidate support/promote → `/api/v1/candidates/{id}/support`
- Research completion → automatic (dossier exists)

Automation **never** writes an approval, never decides for
the human, never reuses a stale decision.