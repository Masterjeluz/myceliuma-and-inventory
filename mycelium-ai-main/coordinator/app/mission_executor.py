"""Server-side MissionExecutor (BIG #3).

The executor orchestrates — it never performs desktop input itself.
One tick advances a running mission step by step until it waits for
approval, pauses, or reaches a terminal state:

- readout steps run here (git/project/INVENTory reads, all
  read-only) and complete immediately.
- desktop steps create exactly one desktop action through the
  existing gate, bind it to (mission, step), and wait: the
  standalone agent claims, executes and reports; the next tick
  reads the action result back into the step. Autonomy never
  leaves the approved step list — an action without a valid
  binding is ignored, never adopted.
- analysis steps ask the provider for advice (artifact only).
- proposal steps build one AdapterProposal artifact and stop:
  approving it happens outside the mission through the existing
  /approvals flow (new approval boundary, never automatic).

Dependencies are injected (ExecutorDeps) so the executor stays
free of HTTP and database imports beyond missions.py; main.py
wires the real coordinator pieces. No shell, no subprocess, no
code execution anywhere in this module.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .adapter_contracts import AdapterProposal
from .agent_loop import DesktopActionRecord
from .inventory_read import Provenance
from .missions import (
    Mission,
    MissionConflictError,
    MissionStep,
    approve_mission,
    bindings_for_mission,
    bind_action,
    cancel_mission,
    check_binding,
    current_step_of,
    load_mission,
    new_event,
    new_mission,
    pause_mission,
    resume_mission,
    save_event,
    save_mission,
    set_step,
)
from .proposal_tasks import proposal_fingerprint

logger = logging.getLogger("mycelium.missions")

MISSION_ADAPTER_ID = "mycelium-mission"


@dataclass
class ExecutorDeps:
    """Injected coordinator pieces (real wiring lives in main.py)."""

    propose_desktop: Callable[[str, dict], DesktopActionRecord]
    load_desktop: Callable[[str], DesktopActionRecord | None]
    post_message: Callable[[str, str, str, list], str]
    advise: Callable[[str, list[dict]], Awaitable[Any]]
    inventory_search: Callable[[str], Awaitable[list[dict]]]
    git_read: Callable[[str], dict]
    project_read: Callable[[], dict]
    default_steps: list[dict] = field(default_factory=list)


class ExecutorError(RuntimeError):
    """Mission cannot proceed; carrying an operator-readable reason."""


def render_plan(mission: Mission) -> str:
    lines = [f"Plan voor: {mission.goal}", ""]
    for position, step in enumerate(mission.steps, start=1):
        marker = {"completed": "✓", "failed": "✗", "blocked": "■",
                  "dispatched": "▶"}.get(step.status, "○")
        extra = ""
        if step.kind == "desktop":
            extra = (" [desktop-input, approval vereist]"
                     if step.requires_approval else " [observatie]")
        lines.append(f"{marker} {position}. {step.description}{extra}")
    return "\n".join(lines)


class MissionExecutor:
    def __init__(self, deps: ExecutorDeps):
        self.deps = deps

    # -- creation -----------------------------------------------------

    def create(self, conversation_id: str, goal: str,
               steps_data: list[dict] | None, *,
               max_steps: int = 10,
               context_records: list[dict] | None = None) -> Mission:
        import secrets
        mission = new_mission(
            f"mission_{secrets.token_hex(4)}", conversation_id, goal,
            steps_data or self.deps.default_steps or
            _default_exploration_steps(),
            max_steps=max_steps, context_records=context_records or [])
        save_mission(mission)
        save_event(new_event(
            conversation_id, "mission_created",
            f"Missie aangemaakt met {len(mission.steps)} stappen. "
            "Goedkeuring vereist voor uitvoering.",
            mission_id=mission.mission_id))
        self.deps.post_message(
            conversation_id, "assistant",
            f"Ik heb een plan gemaakt met {len(mission.steps)} stappen:\n\n"
            f"{render_plan(mission)}\n\n"
            f"Missie: `{mission.mission_id}` — keur het plan goed om te "
            "starten. Desktop-input blijft per stap approval-gated.",
            [])
        logger.info("mission_created mission_id=%s steps=%d",
                    mission.mission_id, len(mission.steps))
        return mission

    # -- control ------------------------------------------------------

    def _load_or_raise(self, mission_id: str) -> Mission:
        mission = load_mission(mission_id)
        if mission is None:
            raise ExecutorError(f"Mission '{mission_id}' not found")
        return mission

    def approve(self, mission_id: str, response: str,
                decided_by: str = "human") -> Mission:
        mission = self._load_or_raise(mission_id)
        try:
            updated = approve_mission(mission, response,
                                      decided_by=decided_by)
        except ValueError as error:
            raise ExecutorError(str(error)) from error
        try:
            save_mission(updated, expected=(mission.status,
                                            mission.current_step))
        except MissionConflictError as error:
            raise ExecutorError(str(error)) from error
        save_event(new_event(
            updated.conversation_id, "mission_approved",
            f"Plan goedgekeurd door {updated.approved_by}.",
            mission_id=mission_id))
        self.deps.post_message(
            updated.conversation_id, "assistant",
            f"Plan goedgekeurd. Ik voer het stap voor stap uit:\n\n"
            f"{render_plan(updated)}", [])
        return updated

    def pause(self, mission_id: str) -> Mission:
        mission = self._load_or_raise(mission_id)
        try:
            updated = pause_mission(mission)
        except ValueError as error:
            raise ExecutorError(str(error)) from error
        try:
            save_mission(updated, expected=(mission.status,
                                            mission.current_step))
        except MissionConflictError as error:
            raise ExecutorError(str(error)) from error
        save_event(new_event(
            updated.conversation_id, "mission_paused", "Missie gepauzeerd.",
            mission_id=mission_id))
        return updated

    def resume(self, mission_id: str) -> Mission:
        mission = self._load_or_raise(mission_id)
        try:
            updated = resume_mission(mission)
        except ValueError as error:
            raise ExecutorError(str(error)) from error
        try:
            save_mission(updated, expected=(mission.status,
                                            mission.current_step))
        except MissionConflictError as error:
            raise ExecutorError(str(error)) from error
        save_event(new_event(
            updated.conversation_id, "mission_resumed", "Missie hervat.",
            mission_id=mission_id))
        return updated

    def cancel(self, mission_id: str) -> Mission:
        mission = self._load_or_raise(mission_id)
        try:
            updated = cancel_mission(mission)
        except ValueError as error:
            raise ExecutorError(str(error)) from error
        try:
            save_mission(updated, expected=(mission.status,
                                            mission.current_step))
        except MissionConflictError as error:
            raise ExecutorError(str(error)) from error
        save_event(new_event(
            updated.conversation_id, "mission_cancelled",
            "Missie gestopt door operator.",
            mission_id=mission_id))
        self.deps.post_message(
            updated.conversation_id, "assistant",
            "Missie gestopt. Er wordt geen volgende actie uitgevoerd.",
            [])
        return updated

    # -- tick: bounded step-by-step autonomy --------------------------

    async def tick(self, mission_id: str) -> dict[str, Any]:
        """Advance a mission until it waits, pauses or terminates.

        Returns a summary dict. At most max_steps iterations; every
        iteration either completes a step or exits. Concurrent ticks
        lose the conditional-update race (409-style abort, no double
        execution).
        """
        mission = self._load_or_raise(mission_id)
        if mission.status == "approved":
            mission = mission.model_copy(update={"status": "running"})
            try:
                save_mission(mission, expected=("approved",
                                                mission.current_step))
            except MissionConflictError as error:
                raise ExecutorError(str(error)) from error
        if mission.status != "running":
            raise ExecutorError(
                f"Mission is {mission.status}; only running missions tick")
        outcome = "waiting"
        for _ in range(mission.max_steps + 1):
            mission = self._load_or_raise(mission_id)
            if mission.status != "running":
                outcome = mission.status
                break
            step = current_step_of(mission)
            if step is None:
                mission = self._finish(mission, "completed",
                                       "Alle stappen voltooid.")
                outcome = "completed"
                break
            if mission.current_step >= mission.max_steps:
                mission = self._finish(
                    mission, "blocked",
                    "Stap-budget op; missie geblokkeerd voor review.")
                outcome = "blocked"
                break
            if step.status in ("completed", "skipped"):
                mission = self._advance(mission, step)
                if (mission.current_step >= mission.max_steps
                        and current_step_of(mission) is not None):
                    mission = self._finish(
                        mission, "blocked",
                        "Stap-budget op; missie geblokkeerd voor review.")
                    outcome = "blocked"
                    break
                continue
            if step.status in ("failed", "blocked"):
                mission = self._finish(
                    mission, "failed" if step.status == "failed"
                    else "blocked",
                    f"Stap {step.sequence + 1} {step.status}.")
                outcome = mission.status
                break
            mission = await self._run_step(mission, step)
            refreshed = self._load_or_raise(mission_id)
            if refreshed.status != "running":
                mission = refreshed
                outcome = mission.status
                break
            current = current_step_of(refreshed)
            if current is not None and current.status in (
                    "pending", "waiting_approval", "dispatched"):
                mission = refreshed
                outcome = "waiting"
                break
            mission = refreshed
        return {"mission_id": mission.mission_id, "status": mission.status,
                "current_step": mission.current_step,
                "total_steps": len(mission.steps), "outcome": outcome}

    async def _run_step(self, mission: Mission,
                        step: MissionStep) -> Mission:
        if step.status == "pending" and not step.started_at:
            mission = set_step(mission, step.step_id,
                               started_at=_now(), status="pending")
            save_mission(mission)
            save_event(new_event(
                mission.conversation_id, "step_started",
                f"Stap {step.sequence + 1} gestart: {step.description}",
                mission_id=mission.mission_id, step_id=step.step_id))
            step = next(entry for entry in mission.steps
                        if entry.step_id == step.step_id)
        if step.kind == "readout":
            return await self._run_readout(mission, step)
        if step.kind == "desktop":
            return await self._run_desktop(mission, step)
        if step.kind == "analysis":
            return await self._run_analysis(mission, step)
        if step.kind == "proposal":
            return self._run_proposal(mission, step)
        return self._block_step(
            mission, step, f"Onbekend stap-type '{step.kind}'")

    # -- step kinds ----------------------------------------------------

    async def _run_readout(self, mission: Mission,
                           step: MissionStep) -> Mission:
        source = str(step.parameters.get("source", ""))
        try:
            if source.startswith("git-"):
                text = _format_git(self.deps.git_read(source))
            elif source == "project":
                text = _format_project(self.deps.project_read())
            elif source == "inventory":
                records = await self.deps.inventory_search(
                    str(step.parameters.get("q", mission.goal))[:200])
                text = _format_records(records)
            else:
                raise ExecutorError(f"Unknown readout source '{source}'")
        except ExecutorError as error:
            return self._block_step(mission, step, str(error))
        except Exception as error:
            return self._block_step(
                mission, step, f"Readout mislukt: {error}")
        mission = set_step(mission, step.step_id, status="completed",
                           result_text=text[:4000],
                           completed_at=_now())
        save_mission(mission)
        save_event(new_event(
            mission.conversation_id, "step_completed",
            f"Stap {step.sequence + 1} voltooid (read-only): "
            f"{step.description}",
            mission_id=mission.mission_id, step_id=step.step_id))
        return mission

    async def _run_desktop(self, mission: Mission,
                           step: MissionStep) -> Mission:
        bindings = bindings_for_mission(mission.mission_id)
        if not step.desktop_action_id:
            import secrets
            action_id = f"dact-{secrets.token_hex(4)}"
            try:
                record = self.deps.propose_desktop(
                    action_id, step.action_type, step.parameters)
            except ValueError as error:
                return self._fail_step(mission, step, str(error))
            bind_action(action_id, mission.mission_id, step.step_id)
            mission = set_step(
                mission, step.step_id,
                desktop_action_id=action_id,
                status=("waiting_approval"
                        if record.status == "pending_approval"
                        else "dispatched"),
                started_at=step.started_at or _now())
            save_mission(mission)
            save_event(new_event(
                mission.conversation_id, "action_proposed",
                f"Desktop-actie voorgesteld voor stap {step.sequence + 1}: "
                f"{step.action_type}"
                + (" — goedkeuring vereist." if step.requires_approval
                   else " (observatie, automatisch toegestaan)."),
                mission_id=mission.mission_id, step_id=step.step_id,
                metadata={"action_id": action_id}))
            if step.requires_approval:
                self.deps.post_message(
                    mission.conversation_id, "assistant",
                    f"Aan stap {step.sequence + 1} is desktop-input "
                    f"gekoppeld (`{step.action_type}`). Keur de actie "
                    f"`{action_id}` goed in het agent-paneel; de Desktop "
                    "Agent voert daarna uit.", [])
            return mission
        try:
            check_binding(mission, step.step_id,
                          step.desktop_action_id, bindings)
        except ValueError as error:
            return self._block_step(mission, step, f"Scope: {error}")
        record = self.deps.load_desktop(step.desktop_action_id)
        if record is None:
            return self._block_step(
                mission, step,
                f"Actie '{step.desktop_action_id}' spoorloos; "
                "scope gebroken")
        if record.status in ("pending_approval", "approved", "dispatched"):
            mission = set_step(
                mission, step.step_id,
                status=("waiting_approval"
                        if record.status == "pending_approval"
                        else "dispatched"))
            save_mission(mission)
            return mission
        if record.status == "completed":
            observation = (record.result.observation_reference
                           if record.result else "")
            mission = set_step(
                mission, step.step_id, status="completed",
                observation_reference=observation,
                result_text=f"Actie {record.action.action_type} voltooid.",
                completed_at=_now())
            save_mission(mission)
            save_event(new_event(
                mission.conversation_id, "observation",
                f"Observatie na stap {step.sequence + 1}: "
                f"{observation or 'geen'}.",
                mission_id=mission.mission_id, step_id=step.step_id,
                metadata={"observation_reference": observation}))
            save_event(new_event(
                mission.conversation_id, "step_completed",
                f"Stap {step.sequence + 1} voltooid: {step.description}",
                mission_id=mission.mission_id, step_id=step.step_id))
            self.deps.post_message(
                mission.conversation_id, "assistant",
                f"✓ Stap {step.sequence + 1} voltooid: {step.description}",
                [])
            return mission
        if record.status == "failed":
            error = (record.result.error if record.result else "")
            return self._fail_step(
                mission, step, f"Desktop-actie faalde: {error}")
        return self._block_step(
            mission, step,
            f"Desktop-actie {record.status}; missie geblokkeerd.")

    async def _run_analysis(self, mission: Mission,
                            step: MissionStep) -> Mission:
        context = list(mission.context_records)
        for prior in mission.steps[:mission.current_step]:
            if prior.result_text:
                context.append({
                    "entity_type": "step-result",
                    "entity_id": prior.step_id,
                    "title": prior.description,
                    "snippet": prior.result_text[:500],
                    "provenance": {"source_type": "sensor-observed",
                                   "human_verified": False}})
        question = str(step.parameters.get("question", "") or
                       f"Analyseer voor missie: {mission.goal}")[:500]
        try:
            answered = await self.deps.advise(question, context[:10])
        except Exception as error:
            mission = set_step(mission, step.step_id, status="blocked",
                               error=f"Adviseur onbereikbaar: {error}"[:500],
                               completed_at=_now())
            save_mission(mission)
            paused = mission.model_copy(update={"status": "paused"})
            save_mission(paused)
            save_event(new_event(
                mission.conversation_id, "step_blocked",
                f"Stap {step.sequence + 1} geblokkeerd: adviseur "
                "onbereikbaar. Missie gepauzeerd.",
                mission_id=mission.mission_id, step_id=step.step_id))
            self.deps.post_message(
                mission.conversation_id, "assistant",
                f"Stap {step.sequence + 1} wacht: mijn lokale model is "
                "onbereikbaar. Missie gepauzeerd — hervat later.", [])
            return paused
        mission = set_step(mission, step.step_id, status="completed",
                           result_text=answered.advice[:4000],
                           completed_at=_now())
        save_mission(mission)
        save_event(new_event(
            mission.conversation_id, "step_completed",
            f"Stap {step.sequence + 1} voltooid (analyse).",
            mission_id=mission.mission_id, step_id=step.step_id))
        self.deps.post_message(
            mission.conversation_id, "assistant",
            f"Analyse bij stap {step.sequence + 1}:\n\n{answered.advice}",
            [])
        return mission

    def _run_proposal(self, mission: Mission,
                      step: MissionStep) -> Mission:
        summary = str(step.parameters.get("proposal", "") or
                      step.description)[:2000]
        proposal_id = f"prop-{mission.mission_id[-8:]}-{step.sequence}"
        proposal = AdapterProposal(
            proposal_id=proposal_id[:80],
            request_id=f"req-{mission.mission_id[-8:]}-{step.sequence}",
            adapter_id=MISSION_ADAPTER_ID,
            proposed_action=summary,
            expected_output=f"Voorstel uit missie {mission.mission_id}",
            risks=["Voorstel is AI-advies; uitvoering vereist aparte "
                   "goedkeuring via de bestaande flow."],
            provenance=Provenance(
                source_type="ai-generated",
                creator_id=f"mission:{mission.mission_id}",
                human_verified=False,
                notes="missie-voorstel; nooit automatisch goedgekeurd"),
            requires_approval=True,
        )
        fingerprint = proposal_fingerprint(proposal)
        mission = set_step(mission, step.step_id, status="completed",
                           proposal_id=proposal.proposal_id,
                           result_text=f"Voorstel {proposal.proposal_id} "
                           f"(fingerprint {fingerprint[:16]}…). Keur apart "
                           "goed via /approvals; geen automatische "
                           "uitvoering.",
                           completed_at=_now())
        save_mission(mission)
        save_event(new_event(
            mission.conversation_id, "step_completed",
            f"Stap {step.sequence + 1} voltooid: voorstel "
            f"{proposal.proposal_id}.",
            mission_id=mission.mission_id, step_id=step.step_id,
            metadata={"proposal_id": proposal.proposal_id,
                      "fingerprint": fingerprint}))
        self.deps.post_message(
            mission.conversation_id, "assistant",
            f"Voorstel uit stap {step.sequence + 1}:\n\n{summary}\n\n"
            f"Voorstel-ID: `{proposal.proposal_id}`. Dit is advies — "
            "goedkeuring en uitvoering lopen via de bestaande "
            "proposal-flow, niet automatisch.", [])
        return mission

    # -- helpers --------------------------------------------------------

    def _advance(self, mission: Mission, step: MissionStep) -> Mission:
        updated = mission.model_copy(
            update={"current_step": mission.current_step + 1})
        try:
            save_mission(updated, expected=(mission.status,
                                            mission.current_step))
        except MissionConflictError as error:
            raise ExecutorError(str(error)) from error
        return updated

    def _fail_step(self, mission: Mission, step: MissionStep,
                   error: str) -> Mission:
        mission = set_step(mission, step.step_id, status="failed",
                           error=error[:2000], completed_at=_now())
        save_mission(mission)
        save_event(new_event(
            mission.conversation_id, "step_failed",
            f"Stap {step.sequence + 1} gefaald: {error[:500]}",
            mission_id=mission.mission_id, step_id=step.step_id))
        failed = mission.model_copy(update={"status": "failed"})
        save_mission(failed)
        save_event(new_event(
            mission.conversation_id, "mission_failed",
            f"Missie gestopt bij stap {step.sequence + 1}.",
            mission_id=mission.mission_id))
        self.deps.post_message(
            mission.conversation_id, "assistant",
            f"Stap {step.sequence + 1} is gefaald: {error[:500]} "
            "Missie veilig gestopt.", [])
        return failed

    def _block_step(self, mission: Mission, step: MissionStep,
                    error: str) -> Mission:
        mission = set_step(mission, step.step_id, status="blocked",
                           error=error[:2000], completed_at=_now())
        save_mission(mission)
        blocked = mission.model_copy(update={"status": "blocked"})
        save_mission(blocked)
        save_event(new_event(
            mission.conversation_id, "step_blocked",
            f"Stap {step.sequence + 1} geblokkeerd: {error[:500]}",
            mission_id=mission.mission_id, step_id=step.step_id))
        self.deps.post_message(
            mission.conversation_id, "assistant",
            f"Stap {step.sequence + 1} geblokkeerd: {error[:500]} "
            "Er gebeurt niets meer tot review.", [])
        return blocked

    def _finish(self, mission: Mission, status: str,
                message: str) -> Mission:
        updated = mission.model_copy(update={"status": status})
        try:
            save_mission(updated, expected=(mission.status,
                                            mission.current_step))
        except MissionConflictError as error:
            raise ExecutorError(str(error)) from error
        event_type = ("mission_completed" if status == "completed"
                      else "mission_blocked" if status == "blocked"
                      else "mission_failed")
        save_event(new_event(
            updated.conversation_id, event_type, message,
            mission_id=mission.mission_id))
        if status == "completed":
            self.deps.post_message(
                updated.conversation_id, "assistant",
                _final_summary(updated, self.deps), [])
        else:
            self.deps.post_message(
                updated.conversation_id, "assistant", message, [])
        logger.info("mission_finished mission_id=%s status=%s",
                    mission.mission_id, status)
        return updated


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _default_exploration_steps() -> list[dict]:
    return [
        {"kind": "readout", "description": "Lees projectcontext",
         "parameters": {"source": "project"}},
        {"kind": "readout", "description": "Lees git-status",
         "parameters": {"source": "git-status"}},
        {"kind": "analysis",
         "description": "Vat samen wat er nog moet gebeuren",
         "parameters": {}},
    ]


def _format_git(data: dict) -> str:
    lines = data.get("lines", [])
    text = "\n".join(str(line) for line in lines[:50])
    branch = f"branch: {data.get('branch', '?')}\n" if "branch" in data else ""
    diff = data.get("diff", "")
    if diff:
        return f"{branch}status:\n{text}\n\ndiff:\n{diff[:2000]}"
    return f"{branch}status:\n{text or '(schoon)'}"


def _format_project(data: dict) -> str:
    return (f"project: {data.get('name', '?')}\n"
            f"repository: {data.get('repository', '?')}\n"
            f"werkmap: {data.get('working_directory', '?')}")


def _format_records(records: list[dict]) -> str:
    if not records:
        return "INVENTory: geen records gevonden."
    lines = [f"INVENTory ({len(records)} records):"]
    for record in records[:10]:
        lines.append(f"- [{record.get('entity_type', '?')}] "
                     f"{record.get('title', '')} "
                     f"({record.get('entity_id', '')})")
    return "\n".join(lines)


def _final_summary(mission: Mission, deps: ExecutorDeps) -> str:
    lines = [f"Missie voltooid: {mission.goal}", ""]
    for position, step in enumerate(mission.steps, start=1):
        marker = "✓" if step.status == "completed" else "○"
        lines.append(f"{marker} {position}. {step.description}")
        if step.result_text and step.kind in ("analysis", "readout"):
            lines.append(f"   {step.result_text[:300]}")
    sources = [str(record.get("entity_id", "?")) for record in
               mission.context_records if record.get("entity_id")]
    if sources:
        lines += ["", f"Bronnen: {', '.join(sources[:10])}"]
    actions: list[str] = []
    for step in mission.steps:
        if step.desktop_action_id:
            record = None
            try:
                record = deps.load_desktop(step.desktop_action_id)
            except ValueError:
                pass
            state = record.status if record else "onbekend"
            actions.append(f"{step.desktop_action_id} ({state})")
    if actions:
        lines += ["", f"Uitgevoerde acties: {', '.join(actions)}"]
    return "\n".join(lines)
