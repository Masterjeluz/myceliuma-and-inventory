# Autonomous Mission Loop (BIG #21) — IMPLEMENTED

One safe continuous runner over the existing executor:
chat intent → mission → tick → observe → evaluate →
continue → verify → complete. The loop adds no
execution power: it calls `executor.tick()`, reads the
gates, and stops at every one of them.

## What runs automatically from chat

1. Chat interprets the opdracht (existing advisor flow)
   and creates a mission (existing `POST /chat/{id}/
   missions` or `/missions`).
2. `POST /missions/{id}/run` (or the mission page's
   *Run loop* button) drives the approved plan:
   - readout steps (git/project/INVENTory) complete
     on their own, results recorded, observations
     linked;
   - analysis steps run through the advisor;
   - screenshot/wait desktop steps auto-dispatch and
     complete when the desktop agent claims, acts and
     reports through its existing loop;
   - camera_observe steps complete with observation
     references (metadata only, never auto-written).
3. Each terminal mission stores one episodic memory
   (observed truth, sensor-observed provenance, never
   a fact tier, never verified) and the run report
   names rounds, transitions and the memory id.

## Where Mycelium stops for Jelles

- **Plan approval**: `pending_approval` missions never
  tick (`needs_plan_approval`).
- **Desktop input**: any step with `requires_approval`
  stops with `needs_desktop_approval` + action_id; only
  an exact YES through `/desktop/actions/{id}/decision`
  unblocks it. Dispatched actions stop with
  `waiting_agent` until the agent reports.
- **Proposals**: drafted as data, completed as steps;
  the separate `/approvals` flow stays human.
- **Writes**: own exact YES + fingerprint revalidation.
- **Physical/fabrication**: own physical approval; a
  mission YES never starts a machine (verified: the
  loop stops, nothing executes).
- **Failure/block/pause/conflict**: halt, human
  reviews; never blind retry, never invented steps.
- Continuation ("herplan → vervolg") happens across
  runs: human/agent/observation changes state, the
  next run ticks further inside the approved plan.
  Replanning beyond approved steps needs a new
  approval. Rounds per call are capped at 10;
  concurrent runs lose the existing conditional race.

## Mock / test / unavailable inventory

- Lokaal uitvoerbaar: readout, analysis (met model),
  screenshot/wait steps, camera_observe (metadata),
  proposal-drafts, write/fabricate/slice/print *alleen*
  met hun eigen approvals + runners.
- Test: TestCameraAdapter, SimulatedPrinterAdapter,
  test-slicer — altijd gelabeld, nooit echt.
- Unavailable: echte printertransporten, echte
  drone/robot-hardware, live externe integraties.
  Fysieke executie blijft HARDWARE_REQUIRED.

## Contract

`POST /api/v1/missions/{id}/run {"max_rounds": 1..10}`
→ `{mission_id, status, outcome, stop_reason?, detail?,
action?, rounds, tick?, memory_id?}`. Unknown missions
422; never shell, network, or SQL surface in the
loop module itself.
