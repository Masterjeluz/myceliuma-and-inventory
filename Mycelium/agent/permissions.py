"""Explicit, default-deny permission gate for local Desktop Agent actions."""

from pathlib import Path
import json
import uuid
from datetime import datetime, timezone

BASE = Path(__file__).parent
DEFAULT_LOG_PATH = BASE / "permission_log.jsonl"
PERMISSION_SOURCE = "mycelium-desktop-agent:permission"
PERMISSION_COMPONENT = "permissions"
PERMISSION_MODE = "explicit-human-confirmation"


class PermissionDeniedError(RuntimeError):
    pass


class PermissionLogError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _normalise_details(details):
    if details is None:
        return {}
    if isinstance(details, str):
        return {"reason": details}
    if isinstance(details, dict):
        return _json_safe(dict(details))
    return {"reason": str(details)}


def _prompt(action, target, reason) -> str:
    return (
        "Mycelium permission required\n"
        f"Action: {action}\n"
        f"Target: {target}\n"
        f"Reason: {reason}\n"
        "Type YES to approve; any other response denies: "
    )


class PermissionGate:
    def __init__(self, log_path=None, input_func=None, now=None):
        self.log_path = Path(log_path) if log_path is not None else DEFAULT_LOG_PATH
        self.input_func = input_func
        self.now = now or _utc_now

    def _append_log(self, decision):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(decision, sort_keys=True) + "\n")
            handle.flush()

    def request_permission(self, action, target, details=None):
        action = str(action).strip()
        target = str(target).strip()
        normalised = _normalise_details(details)
        reason = str(normalised.get("reason") or normalised.get("details") or "not supplied").strip()
        request_id = str(uuid.uuid4())
        requested_at = self.now()
        request = {
            "request_id": request_id,
            "action": action,
            "target": target,
            "details": normalised,
            "reason": reason,
            "requested_at": requested_at,
        }

        if self.input_func is None:
            response = ""
            decision_source = "default-deny"
        else:
            try:
                response = self.input_func(request["reason"] + "\n" + _prompt(action, target, reason))
                response = response.strip() if isinstance(response, str) else ""
            except Exception:
                response = ""
            decision_source = "human-input"

        approved = response == "YES"
        decided_at = self.now()
        decision = {
            **request,
            "approved": approved,
            "decision": "approved" if approved else "denied",
            "response": "YES" if approved else "DENY",
            "decided_at": decided_at,
            "decision_source": decision_source,
            "provenance": {
                "source": PERMISSION_SOURCE,
                "component": PERMISSION_COMPONENT,
                "mode": PERMISSION_MODE,
                "default": "deny",
                "request_id": request_id,
            },
        }
        self._append_log(decision)
        return decision


def request_permission(action, target, details=None, *, log_path=None, input_func=None, now=None):
    """Ask for an explicit permission and return a JSON-serialisable decision.

    Omitted input always denies. Callers that provide an interactive UI or CLI
    must pass ``input_func=input`` explicitly; no approval is ever implicit.
    """
    gate = PermissionGate(log_path=log_path, input_func=input_func, now=now)
    return gate.request_permission(action, target, details)


def request_permission_interactive(action, target, details=None, *, log_path=None, now=None):
    """Interactive wrapper; it still accepts only an exact YES response."""
    return request_permission(
        action,
        target,
        details,
        input_func=input,
        log_path=log_path,
        now=now,
    )
