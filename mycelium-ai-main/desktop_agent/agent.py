"""Standalone desktop-agent loop (BIG #2).

Pull-based like node_client: register -> heartbeat -> claim next
approved action -> revalidate -> observe -> act -> observe ->
report. The coordinator never performs input; this process is the
only place where ComputerActions touch screen, mouse or keyboard.

Safety (tested where side-effect-free):

- claim goes through POST /desktop/actions/next, which re-checks
  registration, freshness and capability match server-side and hands
  out each action at most once (atomic dispatch = lease).
- before EVERY input action the agent re-reads the action and
  requires status dispatched + dispatched_by == its own node id.
  Anything else BLOCKS (no execute, halt the run).
- input actions are wrapped in pre/post screenshots
  (observe -> act -> observe); a failed pre-observation blocks the
  action instead of acting blind.
- MAX_AGENT_STEPS bounds actions per run (default 20, hard cap 100);
  the stop flag halts between actions — never mid-action, never a
  next input after any stop reason (operator cancel, lease/stale,
  failure, invalid approval, capability mismatch, coordinator down).
- results reuse AgentActionResult semantics: completed, failed,
  cancelled, blocked. Never verified.
- no shell, no subprocess, no code execution: actions travel as
  validated ComputerAction data through desktop_runtime only.
"""

import logging
import os
import socket
import time
from typing import Any

import httpx

from coordinator.app.agent_results import AgentActionResult
from coordinator.app.computer_actions import (
    ComputerAction,
    validate_parameters,
)
from coordinator.app.desktop_runtime import (
    BackendUnavailable,
    DesktopBackend,
    get_backend,
)

logger = logging.getLogger("mycelium.desktop-agent")

DEFAULT_MAX_STEPS = 20
HARD_MAX_STEPS = 100
DEFAULT_POLL_SECONDS = 5.0


class CoordinatorUnavailable(RuntimeError):
    """Coordinator unreachable; agent backs off without acting."""


class ApprovalInvalid(RuntimeError):
    """Revalidation failed: do not execute, halt the run."""


def clamp_max_steps(value) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_STEPS
    return max(1, min(number, HARD_MAX_STEPS))


class DesktopAgent:
    """Local hands for approved coordinator actions."""

    def __init__(self, base_url: str, node_id: str,
                 capabilities: list[str],
                 backend: DesktopBackend | None = None,
                 poll_seconds: float = DEFAULT_POLL_SECONDS,
                 max_steps: int = DEFAULT_MAX_STEPS,
                 tier: str = "worker",
                 node_token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.node_id = node_id
        self.capabilities = list(capabilities)
        self.backend = backend or get_backend()
        self.poll_seconds = max(0.5, float(poll_seconds or 0))
        self.max_steps = clamp_max_steps(max_steps)
        self.tier = tier
        token = node_token or os.environ.get("MYCELIUM_NODE_TOKEN",
                                             "")
        self.node_token = token.strip() or None
        self._stop = False
        self.steps_done = 0
        self._client = httpx.Client(
            base_url=self.base_url, timeout=10.0,
            follow_redirects=False)

    # -- lifecycle ----------------------------------------------------

    def stop(self) -> None:
        """Graceful stop: no next input action after this returns."""
        self._stop = True

    @property
    def stopped(self) -> bool:
        return self._stop

    def close(self) -> None:
        try:
            self._client.close()
        except httpx.HTTPError:
            pass

    # -- coordinator protocol (outbound only, existing node routes) ---

    def _post(self, path: str, payload: dict) -> httpx.Response:
        try:
            response = self._client.post(path, json=payload)
        except httpx.HTTPError as error:
            raise CoordinatorUnavailable(str(error)) from error
        if response.status_code in (301, 302, 303, 307, 308):
            raise CoordinatorUnavailable("redirect refused")
        return response

    def _get(self, path: str) -> httpx.Response:
        try:
            response = self._client.get(path)
        except httpx.HTTPError as error:
            raise CoordinatorUnavailable(str(error)) from error
        if response.status_code in (301, 302, 303, 307, 308):
            raise CoordinatorUnavailable("redirect refused")
        return response

    def register(self) -> None:
        try:
            from node_client.main import detected_memory_mb
            memory = detected_memory_mb()
        except (ImportError, OSError):
            memory = 0
        payload = {
            "node_id": self.node_id, "hostname": socket.gethostname(),
            "tier": self.tier, "capabilities": self.capabilities,
            "cpu_cores": os.cpu_count() or 1, "memory_mb": memory,
            "energy_source": "unknown"}
        if self.node_token:
            payload["node_token"] = self.node_token
        response = self._post("/api/v1/nodes/register", payload)
        if response.status_code not in (200, 201):
            raise CoordinatorUnavailable(
                f"register refused: HTTP {response.status_code}")

    def heartbeat(self) -> None:
        payload: dict = {"available": True}
        if self.node_token:
            payload["node_token"] = self.node_token
        response = self._post(
            f"/api/v1/nodes/{self.node_id}/heartbeat", payload)
        if response.status_code == 404:
            self.register()
            response = self._post(
                f"/api/v1/nodes/{self.node_id}/heartbeat", payload)
        if response.status_code not in (200, 204):
            raise CoordinatorUnavailable(
                f"heartbeat refused: HTTP {response.status_code}")

    def claim_next(self) -> dict | None:
        """One atomic claim: approved -> dispatched-to-me, or None."""
        payload: dict = {"node_id": self.node_id}
        if self.node_token:
            payload["node_token"] = self.node_token
        response = self._post("/api/v1/desktop/actions/next", payload)
        if response.status_code == 404:
            raise CoordinatorUnavailable("node unknown; re-registering")
        if response.status_code != 200:
            raise CoordinatorUnavailable(
                f"claim refused: HTTP {response.status_code}")
        data = response.json()
        if isinstance(data, dict) and data.get("mission_id"):
            logger.info("claimed action_id=%s mission=%s step=%s",
                        data.get("action_id"), data.get("mission_id"),
                        data.get("step_id"))
        return data if isinstance(data, dict) else None

    def revalidate(self, action: dict) -> dict:
        """Fresh read immediately before input. Fail-closed.

        Requires status dispatched + dispatched_by == me + a
        still-valid dispatch lease + unchanged type/params.
        Returns the fresh record; raises ApprovalInvalid
        otherwise (BLOCK, halt the run).
        """
        from datetime import datetime, timezone
        action_id = str(action.get("action_id", ""))
        try:
            moment = datetime.fromisoformat(
                str(action.get("lease_until", "") or ""))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            local_valid = moment > datetime.now(timezone.utc)
        except (ValueError, TypeError):
            local_valid = False
        if not local_valid:
            raise ApprovalInvalid(
                f"action '{action_id}' dispatch lease expired; "
                "blocking instead of acting on revoked authority")
        response = self._get(f"/api/v1/desktop/actions/{action_id}")
        if response.status_code != 200:
            raise ApprovalInvalid(
                f"action '{action_id}' unreadable "
                f"(HTTP {response.status_code}); blocking")
        fresh = response.json()
        if (fresh.get("status") != "dispatched"
                or fresh.get("dispatched_by") != self.node_id):
            raise ApprovalInvalid(
                f"action '{action_id}' not dispatched to me "
                f"(status={fresh.get('status')}); blocking")
        lease_until = str(fresh.get("lease_until", "") or "")
        try:
            moment = datetime.fromisoformat(lease_until)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            lease_valid = moment > datetime.now(timezone.utc)
        except (ValueError, TypeError):
            lease_valid = False
        if not lease_valid:
            raise ApprovalInvalid(
                f"action '{action_id}' dispatch lease expired; "
                "blocking instead of acting on revoked authority")
        if fresh.get("action_type") != action.get(
                "action_type") or fresh.get("parameters") != action.get(
                "parameters"):
            raise ApprovalInvalid(
                f"action '{action_id}' changed after claim; blocking")
        return fresh

    def report(self, action_id: str, status: str, *,
               error: str = "",
               observation_reference: str = "") -> dict:
        """Close one action. A 409/422 means the operator moved first:
        treat as cancelled-by-operator and halt (no next input)."""
        response = self._post(
            f"/api/v1/desktop/actions/{action_id}/result",
            {"status": status, "error": error,
             "observation_reference": observation_reference})
        if response.status_code == 200:
            return response.json()
        raise ApprovalInvalid(
            f"result for '{action_id}' refused "
            f"(HTTP {response.status_code}); halting")

    # -- execution (only place where input happens) -------------------

    def _to_action(self, data: dict) -> ComputerAction:
        try:
            parameters = validate_parameters(
                str(data.get("action_type", "")),
                dict(data.get("parameters", {})))
        except (ValueError, TypeError, AttributeError) as error:
            raise ApprovalInvalid(
                f"action '{data.get('action_id')}' invalid: {error}")
        return ComputerAction(
            action_id=str(data.get("action_id", "")),
            action_type=str(data.get("action_type", "")),
            parameters=parameters,
            requires_approval=True,
        )

    def _observe(self) -> str:
        """Pre/post screenshot. Returns observation id or raises."""
        try:
            return self.backend.screenshot().observation_id
        except BackendUnavailable as error:
            raise ApprovalInvalid(
                f"observation failed: {error}; blocking") from error

    def execute_claimed(self, claimed: dict) -> AgentActionResult:
        """Revalidate -> observe -> act -> observe -> report.

        Returns the reported record summary. Raises ApprovalInvalid
        (BLOCK + halt) or CoordinatorUnavailable (back off, halt run).
        """
        fresh = self.revalidate(claimed)
        action = self._to_action(fresh)
        pre_observation = ""
        if action.action_type != "screenshot":
            pre_observation = self._observe()
        outcome = self.backend.execute(action)
        post_observation = ""
        if action.action_type != "screenshot":
            try:
                post_observation = self._observe()
            except ApprovalInvalid:
                post_observation = pre_observation
        reference = (outcome.observation_reference
                     or post_observation or pre_observation)
        closed = self.report(action.action_id, outcome.status,
                             error=outcome.error,
                             observation_reference=reference)
        logger.info("action_done action_id=%s status=%s mission=%s step=%s",
                    action.action_id, outcome.status,
                    fresh.get("mission_id"), fresh.get("step_id"))
        return closed

    # -- run ----------------------------------------------------------

    def run_once(self) -> str:
        """Single poll cycle: heartbeat, maybe one action.

        Returns idle | done:<status> | blocked:<reason>. Never raises
        for expected stop reasons; unexpected coordinator loss raises
        CoordinatorUnavailable so the caller backs off.
        """
        self.heartbeat()
        claimed = self.claim_next()
        if claimed is None:
            return "idle"
        if self._stop:
            return "blocked:stopped-before-input"
        try:
            closed = self.execute_claimed(claimed)
        except ApprovalInvalid as error:
            logger.warning("action_blocked cause=%s", error)
            return f"blocked:{error}"
        self.steps_done += 1
        result = (closed.get("result") or {})
        return f"done:{result.get('status', closed.get('status'))}"

    def run(self) -> str:
        """Bounded loop: at most max_steps actions, then stop.

        Returns done | step-limit | stopped. Coordinator loss aborts
        the run with CoordinatorUnavailable (caller sleeps, retries).
        """
        self.register()
        while not self._stop:
            if self.steps_done >= self.max_steps:
                logger.info("step_limit_reached steps=%d", self.steps_done)
                return "step-limit"
            outcome = self.run_once()
            if outcome == "idle":
                time.sleep(self.poll_seconds)
                continue
            if outcome.startswith("blocked:"):
                return outcome
            if self._stop:
                return "stopped"
            time.sleep(self.poll_seconds)
        return "stopped"

    def run_forever(self) -> None:
        """Long-running mode: run() in backoff loop until stopped."""
        while not self._stop:
            try:
                finished = self.run()
            except CoordinatorUnavailable as error:
                logger.warning("coordinator_unavailable cause=%s", error)
                time.sleep(self.poll_seconds)
                continue
            if finished == "step-limit":
                self.steps_done = 0
            time.sleep(self.poll_seconds)


def describe_capabilities(capabilities: list[str]) -> dict[str, Any]:
    """Operator-facing capability summary for the agent panel."""
    return {
        "advertised": list(capabilities),
        "input": sorted(cap for cap in capabilities
                        if cap.startswith("desktop.mouse")
                        or cap.startswith("desktop.keyboard")),
        "observe": [cap for cap in capabilities
                    if cap == "desktop.screen.read"],
    }
