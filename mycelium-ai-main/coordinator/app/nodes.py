"""Distributed node registry foundation (BIG #8).

Coordinator-side node identity, authentication, capability /
model / executor advertisement, resource hints and status —
pure validation and derivation, no I/O, no sockets, no
credentials leaving the caller's hands.

Trust model (minimal, local-first, documented limits):

- A node proves identity with a per-node token. The
  coordinator stores only a salted hash (sha256 over
  ``mycelium-node-v1|node_id|token``); the token itself is
  never stored, never logged and never returned by any API.
- First registration may bind a token (hash stored). Later
  registrations, heartbeats and claims for that node must
  present the same token or fail closed (403-style refusal).
- Nodes without a stored hash stay in legacy mode so the
  existing node_client and desktop_agent keep working
  unchanged; operators should bind tokens for any node that
  claims privileged work.
- This is NOT PKI: tokens are bearer strings from local
  configuration (env/args). It proves possession of a shared
  secret on a trusted LAN, nothing more. Rotation = register
  again with a new token (rebinds). Limits are documented in
  docs/distributed-architecture.md.

Advertisement rules (all fail-closed):

- Capabilities are explicit strings (``^[a-zA-Z0-9._:+-]+$``,
  1..80 chars, max 50). No ``*`` wildcards, no whitespace, no
  shell metacharacters. A task can never grant a capability:
  matching only compares task requirements against what the
  node advertised at registration/heartbeat time.
- Models: ``model_id`` must start with ``mod_`` (INVENTory
  world-model link) or ``model:`` (node-local runtime name);
  ``model_type`` is closed; provider is a plain local name
  (no URLs, no credentials); resource_hints are bounded.
- Executors use the existing ``exec:`` namespace
  (``^exec:[a-z0-9._-]+$``); anything else is refused.
- Resource hints are scheduling hints, never guarantees and
  never measurements: bounded integers, closed energy enums.
- Locality is a closed label; matching is label equality (or
  ``any``). Loopback-only transport stays the real boundary.
"""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

NODE_ID_PATTERN = r"^[a-zA-Z0-9._-]+$"
CAPABILITY_PATTERN = r"^[a-zA-Z0-9._:+-]+$"
EXECUTOR_PATTERN = r"^exec:[a-z0-9._-]+$"
PROVIDER_PATTERN = r"^[a-z0-9_-]+$"

MAX_CAPABILITIES = 50
MAX_CAPABILITY_CHARS = 80
MAX_MODELS = 20
MAX_EXECUTORS = 20
MAX_NAME_CHARS = 120

VALID_NODE_STATUSES = frozenset({
    "unknown", "online", "stale", "offline", "disabled",
})

VALID_MODEL_TYPES = frozenset({
    "llm", "vlm", "vision", "detection", "ocr", "embedding",
    "speech_to_text", "other",
})

VALID_ENERGY_SOURCES = frozenset({"grid", "solar", "battery",
                                  "unknown"})
VALID_ENERGY_PRIORITIES = frozenset({"low", "normal", "high"})
VALID_LOCALITIES = frozenset({"same_host", "local_network",
                              "remote_lan", "any"})

#: Closed capability set for phone nodes (BIG #9). Phones are
#: interface + sensor + notification surface; capabilities stay
#: authoritative — device type never implies permission.
PHONE_CAPABILITIES = frozenset({
    "phone.screen.read",
    "phone.notification.send",
    "phone.camera.read",
    "phone.camera.snapshot",
    "phone.microphone.read",
    "phone.speaker.play",
})


def is_phone_node(capabilities) -> bool:
    """True when the advertisement carries phone capabilities."""
    try:
        advertised = {str(cap).strip().lower()
                      for cap in (capabilities or [])}
    except TypeError:
        return False
    return bool(advertised & PHONE_CAPABILITIES)

TOKEN_VERSION = "mycelium-node-v1"

#: Operator key env var for identity administration
#: (token binding on existing identities, enable/disable).
#: The operator runs on this machine; the key lives in local
#: env config, never in the database, never in logs.
OPERATOR_KEY_ENV_VAR = "MYCELIUM_OPERATOR_KEY"

#: Minimum token length. generate_token() issues 64 hex
#: chars; anything shorter is refused at registration and
#: rotation so trivial secrets cannot bind an identity.
MIN_NODE_TOKEN_CHARS = 16


class NodeRefusedError(ValueError):
    """Local validation refused the node data; nothing was stored."""


class NodeAuthError(ValueError):
    """Authentication failed. Fail closed, no detail leakage."""


# -- tokens --------------------------------------------------------

def generate_token() -> str:
    """One fresh bearer token (64 hex chars). Shown once to the
    operator; only its hash is ever stored."""
    return secrets.token_hex(32)


def hash_token(node_id: str, token: str) -> str:
    digest = hashlib.sha256(
        f"{TOKEN_VERSION}|{node_id}|{token}".encode("utf-8"))
    return digest.hexdigest()


def verify_token(node_id: str, token: str, stored_hash: str) -> bool:
    if not stored_hash or not token:
        return False
    try:
        return hmac.compare_digest(
            hash_token(node_id, token), stored_hash)
    except (TypeError, ValueError):
        return False


def authenticate(node_id: str, stored_hash: str | None,
                 presented: str | None) -> str:
    """Gate for register/heartbeat/claim. Returns 'legacy' when the
    node never bound a token, 'token' on match, else raises
    NodeAuthError (caller maps to 403 without detail)."""
    if not stored_hash:
        return "legacy"
    if (isinstance(presented, str) and presented
            and verify_token(node_id, presented, stored_hash)):
        return "token"
    raise NodeAuthError("node credential rejected")


def check_node_token_strength(token) -> str:
    """Refuse trivially short tokens before they bind."""
    if not isinstance(token, str) or len(token.strip()) < \
            MIN_NODE_TOKEN_CHARS:
        raise NodeRefusedError(
            f"node token must be at least "
            f"{MIN_NODE_TOKEN_CHARS} characters")
    return token.strip()


def check_operator_key(presented) -> None:
    """Operator authorization for identity administration.
    The expected key comes from local env only; unset means
    refuse everything (fail-closed, no default key)."""
    import hmac
    import os
    expected = os.environ.get(OPERATOR_KEY_ENV_VAR, "")
    if not expected or not isinstance(presented, str) or \
            not presented:
        raise NodeAuthError("operator authorization rejected")
    if not hmac.compare_digest(presented, expected):
        raise NodeAuthError("operator authorization rejected")


# -- advertisement validation ---------------------------------------


def check_node_id(node_id) -> str:
    if (not isinstance(node_id, str) or not node_id.strip()
            or len(node_id) > 80
            or not re.match(NODE_ID_PATTERN, node_id.strip())):
        raise NodeRefusedError(
            "node_id must be 1..80 chars of [a-zA-Z0-9._-]")
    return node_id.strip()


def check_capabilities(values) -> list[str]:
    if not isinstance(values, (list, tuple)):
        raise NodeRefusedError("capabilities must be a list")
    if len(values) > MAX_CAPABILITIES:
        raise NodeRefusedError(
            f"at most {MAX_CAPABILITIES} capabilities")
    cleaned: list[str] = []
    for entry in values:
        if (not isinstance(entry, str) or not entry.strip()
                or len(entry.strip()) > MAX_CAPABILITY_CHARS
                or not re.match(CAPABILITY_PATTERN,
                                entry.strip())):
            raise NodeRefusedError(
                f"capability '{str(entry)[:40]}' is not an explicit "
                "capability string")
        if "*" in entry:
            raise NodeRefusedError(
                "wildcard capabilities are never accepted")
        text = entry.strip()
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


def check_executors(values) -> list[str]:
    if not isinstance(values, (list, tuple)):
        raise NodeRefusedError("executors must be a list")
    if len(values) > MAX_EXECUTORS:
        raise NodeRefusedError(
            f"at most {MAX_EXECUTORS} executors")
    cleaned: list[str] = []
    for entry in values:
        if (not isinstance(entry, str)
                or not re.match(EXECUTOR_PATTERN,
                                entry.strip().lower())):
            raise NodeRefusedError(
                f"executor '{str(entry)[:40]}' must use the "
                "'exec:<kind>' namespace")
        text = entry.strip().lower()
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


def check_model_id(model_id) -> str:
    if (not isinstance(model_id, str) or not model_id.strip()
            or len(model_id) > 120):
        raise NodeRefusedError("model_id must be 1..120 chars")
    text = model_id.strip()
    if text.startswith("mod_") or text.startswith("model:"):
        rest = text[4:] if text.startswith("mod_") else text[6:]
        if rest and re.match(r"^[a-zA-Z0-9._:+-]+$", rest):
            return text
    raise NodeRefusedError(
        "model_id must start with 'mod_' (INVENTory link) or "
        "'model:' (node-local runtime name)")


def check_models(values) -> list[dict]:
    if not isinstance(values, (list, tuple)):
        raise NodeRefusedError("models must be a list")
    if len(values) > MAX_MODELS:
        raise NodeRefusedError(f"at most {MAX_MODELS} models")
    cleaned: list[dict] = []
    for entry in values:
        if not isinstance(entry, dict):
            raise NodeRefusedError("each model must be an object")
        unknown = set(entry) - {"model_id", "display_name",
                                "model_type", "capabilities",
                                "provider", "status"}
        if unknown:
            raise NodeRefusedError(
                f"model carries unknown fields: {sorted(unknown)}")
        model_type = str(entry.get("model_type", "other"))
        if model_type not in VALID_MODEL_TYPES:
            raise NodeRefusedError(
                f"model_type '{model_type}' unknown; expected one of "
                f"{sorted(VALID_MODEL_TYPES)}")
        provider = str(entry.get("provider", "local"))
        if (not re.match(PROVIDER_PATTERN, provider)
                or len(provider) > 40):
            raise NodeRefusedError(
                "model provider must be a plain local name "
                "(no URLs, no credentials)")
        if "://" in provider or provider.startswith("http"):
            raise NodeRefusedError(
                "model provider must not be a URL")
        display = str(entry.get("display_name", ""))[:MAX_NAME_CHARS]
        cleaned.append({
            "model_id": check_model_id(entry.get("model_id", "")),
            "display_name": display,
            "model_type": model_type,
            "capabilities": check_capabilities(
                entry.get("capabilities", [])),
            "provider": provider,
            "status": ("available" if str(
                entry.get("status", "available"))
                in ("available", "busy") else "available"),
        })
    return cleaned


def check_resources(values) -> dict:
    if values is None:
        return {}
    if not isinstance(values, dict):
        raise NodeRefusedError("resources must be an object")
    unknown = set(values) - {"cpu_cores", "memory_mb",
                             "gpu_available", "gpu_memory_mb",
                             "storage_free_mb", "energy_source",
                             "energy_level", "energy_priority"}
    if unknown:
        raise NodeRefusedError(
            f"resources carry unknown fields: {sorted(unknown)}")
    cleaned: dict[str, Any] = {}
    for key in ("cpu_cores", "memory_mb", "gpu_memory_mb",
                "storage_free_mb"):
        if key in values:
            number = values[key]
            if (isinstance(number, bool) or not isinstance(number,
                                                            int)
                    or number < 0 or number > 10**9):
                raise NodeRefusedError(
                    f"resource '{key}' must be a bounded integer")
            cleaned[key] = number
    if "gpu_available" in values:
        if not isinstance(values["gpu_available"], bool):
            raise NodeRefusedError("gpu_available must be boolean")
        cleaned["gpu_available"] = values["gpu_available"]
    source = str(values.get("energy_source", "unknown"))
    if source not in VALID_ENERGY_SOURCES:
        raise NodeRefusedError(
            f"energy_source '{source}' unknown; expected one of "
            f"{sorted(VALID_ENERGY_SOURCES)}")
    cleaned["energy_source"] = source
    level = values.get("energy_level", None)
    if level is not None:
        if (isinstance(level, bool) or not isinstance(level, int)
                or not 0 <= level <= 100):
            raise NodeRefusedError(
                "energy_level must be 0..100 or null")
        cleaned["energy_level"] = level
    priority = str(values.get("energy_priority", "normal"))
    if priority not in VALID_ENERGY_PRIORITIES:
        raise NodeRefusedError(
            f"energy_priority '{priority}' unknown; expected one "
            f"of {sorted(VALID_ENERGY_PRIORITIES)}")
    cleaned["energy_priority"] = priority
    return cleaned


def check_locality(value) -> str:
    text = str(value or "local_network")
    if text not in VALID_LOCALITIES:
        raise NodeRefusedError(
            f"locality '{text}' unknown; expected one of "
            f"{sorted(VALID_LOCALITIES)}")
    return text


def check_display_name(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise NodeRefusedError("display_name must be text")
    return value.strip()[:MAX_NAME_CHARS]


# -- status ---------------------------------------------------------------

def derive_status(stored_status: str, last_seen: str,
                  now_str: str | None = None,
                  stale_seconds: int = 60) -> str:
    """Derived node status. 'disabled' is sticky and wins over
    everything; otherwise freshness decides."""
    if stored_status == "disabled":
        return "disabled"
    if stored_status not in ("online", "busy", "offline",
                             "unknown"):
        return "unknown"
    try:
        current = (datetime.fromisoformat(now_str)
                   if now_str else datetime.now(timezone.utc))
        seen = datetime.fromisoformat(last_seen)
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        age = current - seen
    except (ValueError, TypeError):
        return "stale"
    if age > timedelta(seconds=stale_seconds):
        return "stale" if stored_status in ("online", "busy") \
            else "offline"
    return stored_status if stored_status in ("online", "busy") \
        else "unknown"


# -- telemetry validation (BIG #39 Hardware Reality Layer) ----------

VALID_TELEMETRY_FIELDS = frozenset({
    "hostname", "os", "platform", "architecture", "cpu_percent",
    "cpu_count", "memory_percent", "memory_total_mb",
    "memory_available_mb", "disk_percent", "disk_total_gb",
    "disk_free_gb", "uptime_seconds", "temperature_celsius",
    "load_average", "network_interfaces", "boot_time",
})

VALID_HARDWARE_KINDS = frozenset({
    "camera", "usb", "printer_3d", "sensor", "storage",
    "gpu", "display", "audio", "network", "other",
})

VALID_COMPUTE_CAPABILITIES = frozenset({
    "ollama", "local_models", "cpu_inference", "gpu_available",
    "vram_mb", "research", "vision", "inventory", "analysis",
})

VALID_ENERGY_STATES = frozenset({"grid", "solar", "battery", "unknown"})

MAX_TELEMETRY_FIELDS = 30
MAX_HARDWARE_ITEMS = 50
MAX_COMPUTE_ITEMS = 20


def check_telemetry(values) -> dict:
    """Validate node telemetry payload. Only known fields, bounded values."""
    if values is None:
        return {}
    if not isinstance(values, dict):
        raise NodeRefusedError("telemetry must be an object")
    unknown = set(values) - VALID_TELEMETRY_FIELDS
    if unknown:
        raise NodeRefusedError(
            f"telemetry carries unknown fields: {sorted(unknown)}")
    if len(values) > MAX_TELEMETRY_FIELDS:
        raise NodeRefusedError(
            f"at most {MAX_TELEMETRY_FIELDS} telemetry fields")
    cleaned: dict = {}
    for key, value in values.items():
        if key in ("cpu_percent", "memory_percent", "disk_percent"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise NodeRefusedError(f"telemetry '{key}' must be a number")
            if not 0 <= value <= 100:
                raise NodeRefusedError(f"telemetry '{key}' must be 0..100")
            cleaned[key] = float(value)
        elif key in ("cpu_count", "memory_total_mb", "memory_available_mb",
                     "uptime_seconds", "disk_total_gb", "disk_free_gb"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise NodeRefusedError(f"telemetry '{key}' must be a number")
            if value < 0 or value > 10**9:
                raise NodeRefusedError(f"telemetry '{key}' out of bounds")
            cleaned[key] = int(value) if key != "disk_total_gb" and key != "disk_free_gb" else float(value)
        elif key == "temperature_celsius":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise NodeRefusedError("temperature_celsius must be a number")
            if not -50 <= value <= 150:
                raise NodeRefusedError("temperature_celsius out of plausible range")
            cleaned[key] = float(value)
        elif key == "load_average":
            if not isinstance(value, (list, tuple)) or len(value) != 3:
                raise NodeRefusedError("load_average must be [1m, 5m, 15m]")
            cleaned[key] = [float(v) for v in value if isinstance(v, (int, float))]
        elif key == "network_interfaces":
            if not isinstance(value, list):
                raise NodeRefusedError("network_interfaces must be a list")
            cleaned[key] = [str(v)[:80] for v in value[:20]]
        elif key in ("hostname", "os", "platform", "architecture"):
            if not isinstance(value, str):
                raise NodeRefusedError(f"telemetry '{key}' must be text")
            cleaned[key] = value.strip()[:120]
        elif key == "boot_time":
            if not isinstance(value, (int, float, str)):
                raise NodeRefusedError("boot_time must be a timestamp")
            cleaned[key] = str(value)[:40]
    return cleaned


def check_hardware(values) -> list[dict]:
    """Validate hardware inventory list. Each item: kind, identifier, details."""
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        raise NodeRefusedError("hardware must be a list")
    if len(values) > MAX_HARDWARE_ITEMS:
        raise NodeRefusedError(f"at most {MAX_HARDWARE_ITEMS} hardware items")
    cleaned: list[dict] = []
    for entry in values:
        if not isinstance(entry, dict):
            raise NodeRefusedError("each hardware item must be an object")
        unknown = set(entry) - {"kind", "identifier", "details", "status", "connected_since"}
        if unknown:
            raise NodeRefusedError(
                f"hardware item carries unknown fields: {sorted(unknown)}")
        kind = str(entry.get("kind", "")).strip().lower()
        if kind not in VALID_HARDWARE_KINDS:
            raise NodeRefusedError(
                f"hardware kind '{kind}' unknown; expected one of {sorted(VALID_HARDWARE_KINDS)}")
        identifier = str(entry.get("identifier", "")).strip()[:120]
        if not identifier:
            raise NodeRefusedError("hardware item needs an identifier")
        details = entry.get("details", {})
        if not isinstance(details, dict):
            details = {}
        status = str(entry.get("status", "connected")).strip().lower()
        if status not in ("connected", "disconnected", "error", "unknown"):
            status = "unknown"
        connected_since = entry.get("connected_since")
        if connected_since is not None:
            if not isinstance(connected_since, (int, float, str)):
                connected_since = None
            else:
                connected_since = str(connected_since)[:40]
        cleaned.append({
            "kind": kind,
            "identifier": identifier,
            "details": details,
            "status": status,
            "connected_since": connected_since,
        })
    return cleaned


def check_compute_capabilities(values) -> list[dict]:
    """Validate compute/AI capabilities list. Each item: capability, details."""
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        raise NodeRefusedError("compute_capabilities must be a list")
    if len(values) > MAX_COMPUTE_ITEMS:
        raise NodeRefusedError(f"at most {MAX_COMPUTE_ITEMS} compute capabilities")
    cleaned: list[dict] = []
    for entry in values:
        if not isinstance(entry, dict):
            raise NodeRefusedError("each compute capability must be an object")
        unknown = set(entry) - {"capability", "details", "status", "since"}
        if unknown:
            raise NodeRefusedError(
                f"compute capability carries unknown fields: {sorted(unknown)}")
        capability = str(entry.get("capability", "")).strip().lower()
        if capability not in VALID_COMPUTE_CAPABILITIES:
            raise NodeRefusedError(
                f"compute capability '{capability}' unknown; expected one of {sorted(VALID_COMPUTE_CAPABILITIES)}")
        details = entry.get("details", {})
        if not isinstance(details, dict):
            details = {}
        status = str(entry.get("status", "available")).strip().lower()
        if status not in ("available", "busy", "unavailable", "unknown"):
            status = "unknown"
        since = entry.get("since")
        if since is not None:
            if not isinstance(since, (int, float, str)):
                since = None
            else:
                since = str(since)[:40]
        cleaned.append({
            "capability": capability,
            "details": details,
            "status": status,
            "since": since,
        })
    return cleaned


def check_energy_state(values) -> dict:
    """Validate energy/physical state. Source from closed set, level 0-100."""
    if values is None:
        return {}
    if not isinstance(values, dict):
        raise NodeRefusedError("energy_state must be an object")
    unknown = set(values) - {"source", "level_percent", "charging", "details", "since"}
    if unknown:
        raise NodeRefusedError(
            f"energy_state carries unknown fields: {sorted(unknown)}")
    cleaned: dict = {}
    source = str(values.get("source", "unknown")).strip().lower()
    if source not in VALID_ENERGY_STATES:
        raise NodeRefusedError(
            f"energy source '{source}' unknown; expected one of {sorted(VALID_ENERGY_STATES)}")
    cleaned["source"] = source
    level = values.get("level_percent")
    if level is not None:
        if isinstance(level, bool) or not isinstance(level, (int, float)):
            raise NodeRefusedError("energy level must be a number 0..100")
        if not 0 <= level <= 100:
            raise NodeRefusedError("energy level must be 0..100")
        cleaned["level_percent"] = int(level)
    charging = values.get("charging")
    if charging is not None:
        if not isinstance(charging, bool):
            raise NodeRefusedError("charging must be boolean")
        cleaned["charging"] = charging
    details = values.get("details", {})
    if not isinstance(details, dict):
        details = {}
    cleaned["details"] = details
    since = values.get("since")
    if since is not None:
        if not isinstance(since, (int, float, str)):
            since = None
        else:
            since = str(since)[:40]
        cleaned["since"] = since
    return cleaned


#: Hardware claim trust levels (BIG #41 live hardware reality).
#: ADVERTISED: the node said so (default, never a fact).
#: OBSERVED: connected right now AND the report is fresh
#: (< 5 min) — live-observed, still not verified.
#: VERIFIED: reserved for an explicit human link (like printer
#: twins). No automated path may ever derive VERIFIED.
HARDWARE_TRUST = ("ADVERTISED", "OBSERVED", "VERIFIED")

TELEMETRY_FRESH_SECONDS = 300


def hardware_trust(item: dict, telemetry_timestamp: str = ""
                   ) -> tuple[str, str]:
    """Trust level + reason for one hardware report. Pure.

    Never returns VERIFIED: claims are advertisements until a
    human links them, and that link lives outside this
    function by design.
    """
    if not isinstance(item, dict):
        return "ADVERTISED", "not a hardware report"
    if str(item.get("status", "")).lower() != "connected":
        return "ADVERTISED", "not currently connected"
    stamp = str(telemetry_timestamp or "")
    if not stamp:
        return "ADVERTISED", "no telemetry timestamp"
    try:
        from datetime import datetime, timezone
        moment = datetime.fromisoformat(stamp)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - moment
               ).total_seconds()
    except (ValueError, TypeError):
        return "ADVERTISED", "telemetry timestamp unparsable"
    if age < 0 or age > TELEMETRY_FRESH_SECONDS:
        return "ADVERTISED", \
            f"report older than {TELEMETRY_FRESH_SECONDS}s"
    return "OBSERVED", \
        f"connected with {int(age)}s-old telemetry"


def compute_node_health(record: dict) -> dict:
    """Compute node health status from record. Returns dict with status and details."""
    derived = record.get("derived_status", "unknown")
    telemetry_ts = record.get("telemetry_timestamp", "")
    now = datetime.now(timezone.utc)
    telemetry_age_seconds = None
    if telemetry_ts:
        try:
            ts = datetime.fromisoformat(telemetry_ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            telemetry_age_seconds = int((now - ts).total_seconds())
        except (ValueError, TypeError):
            telemetry_age_seconds = None

    # Health states: ONLINE, DEGRADED, STALE, OFFLINE, UNKNOWN
    if derived == "disabled":
        health = "OFFLINE"
    elif derived == "offline":
        health = "OFFLINE"
    elif derived == "stale":
        health = "STALE"
    elif derived in ("online", "busy"):
        if telemetry_age_seconds is None:
            health = "DEGRADED"
        elif telemetry_age_seconds > 300:  # 5 minutes
            health = "DEGRADED"
        elif telemetry_age_seconds > 60:
            health = "ONLINE"  # fresh but not real-time
        else:
            health = "ONLINE"
    else:
        health = "UNKNOWN"

    # Collect telemetry summary for health details
    telemetry = record.get("telemetry", {})
    hardware = record.get("hardware", [])
    compute = record.get("compute_capabilities", [])
    energy = record.get("energy_state", {})

    details = {
        "telemetry_age_seconds": telemetry_age_seconds,
        "telemetry_fields": len(telemetry) if isinstance(telemetry, dict) else 0,
        "hardware_count": len(hardware) if isinstance(hardware, list) else 0,
        "compute_capabilities": [c.get("capability") for c in compute if isinstance(c, dict)] if isinstance(compute, list) else [],
        "energy_source": energy.get("source") if isinstance(energy, dict) else "unknown",
        "energy_level": energy.get("level_percent") if isinstance(energy, dict) else None,
    }

    return {"health": health, "details": details}


# -- display discovery contract (VERTICAL SLICE 1: physical digital world)
#
# A node may report read-only display information alongside its
# heartbeat. This is ADVERTISED node-state, stored on the node row
# (like telemetry/hardware) — never a display database, never a
# second truth, never a write path to physical configuration.
#
# Honesty rules (fail-closed, never fake):
# - every field the node cannot reliably determine stays None
#   (unknown physical size, unknown position, unknown refresh).
# - `id` is the only required field (connector identifier, e.g.
#   "HDMI-1"); everything else is optional.
# - the coordinator never derives, guesses or backfills values.

VALID_DISPLAY_FIELDS = frozenset({
    "id", "name", "width", "height", "refresh_rate",
    "physical_width_mm", "physical_height_mm", "x", "y",
    "scale", "orientation", "primary",
})

VALID_DISPLAY_ORIENTATIONS = frozenset({
    "normal", "left", "right", "inverted", "unknown",
})

MAX_DISPLAYS = 16
MAX_DISPLAY_ID_CHARS = 120
MAX_DISPLAY_NAME_CHARS = 120
MAX_DISPLAY_PIXELS = 16384
MAX_DISPLAY_MM = 10000
MAX_DISPLAY_OFFSET = 100000


def _check_display_optional_int(value, field: str, low: int,
                                high: int) -> int | None:
    """One nullable bounded integer. None stays None (unknown);
    bools are refused (never silently 0/1)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise NodeRefusedError(
            f"display '{field}' must be an integer or null")
    if not low <= value <= high:
        raise NodeRefusedError(
            f"display '{field}' out of bounds ({low}..{high})")
    return value


def _check_display_optional_number(value, field: str, low: float,
                                   high: float):
    """One nullable bounded number (refresh rate, scale)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NodeRefusedError(
            f"display '{field}' must be a number or null")
    number = float(value)
    if not low <= number <= high:
        raise NodeRefusedError(
            f"display '{field}' out of bounds ({low}..{high})")
    return number


def check_displays(values) -> list[dict]:
    """Validate a node display report. Pure, fail-closed.

    Returns cleaned display dicts; unknown values stay None.
    Refuses unknown fields, duplicate ids, out-of-range numbers
    and anything that is not a list of objects."""
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        raise NodeRefusedError("displays must be a list")
    if len(values) > MAX_DISPLAYS:
        raise NodeRefusedError(
            f"at most {MAX_DISPLAYS} displays")
    cleaned: list[dict] = []
    seen_ids: set[str] = set()
    for entry in values:
        if not isinstance(entry, dict):
            raise NodeRefusedError(
                "each display must be an object")
        unknown = set(entry) - VALID_DISPLAY_FIELDS
        if unknown:
            raise NodeRefusedError(
                "display carries unknown fields: "
                f"{sorted(unknown)}")
        raw_id = entry.get("id", "")
        if (not isinstance(raw_id, str) or not raw_id.strip()
                or len(raw_id.strip()) > MAX_DISPLAY_ID_CHARS):
            raise NodeRefusedError(
                "display 'id' must be 1..120 chars of text")
        ident = raw_id.strip()
        if ident in seen_ids:
            raise NodeRefusedError(
                f"duplicate display id '{ident[:40]}'")
        seen_ids.add(ident)
        raw_name = entry.get("name", "")
        if raw_name is None:
            name = ""
        elif not isinstance(raw_name, str):
            raise NodeRefusedError("display 'name' must be text")
        else:
            name = raw_name.strip()[:MAX_DISPLAY_NAME_CHARS]
        orientation = str(entry.get("orientation", "unknown") or
                          "unknown").strip().lower()
        if orientation not in VALID_DISPLAY_ORIENTATIONS:
            raise NodeRefusedError(
                f"display orientation '{orientation}' unknown; "
                f"expected one of {sorted(VALID_DISPLAY_ORIENTATIONS)}")
        primary = entry.get("primary", False)
        if primary is None:
            primary = False
        if not isinstance(primary, bool):
            raise NodeRefusedError(
                "display 'primary' must be boolean")
        cleaned.append({
            "id": ident,
            "name": name,
            "width": _check_display_optional_int(
                entry.get("width"), "width", 1, MAX_DISPLAY_PIXELS),
            "height": _check_display_optional_int(
                entry.get("height"), "height", 1, MAX_DISPLAY_PIXELS),
            "refresh_rate": _check_display_optional_number(
                entry.get("refresh_rate"), "refresh_rate", 1, 1000),
            "physical_width_mm": _check_display_optional_int(
                entry.get("physical_width_mm"),
                "physical_width_mm", 1, MAX_DISPLAY_MM),
            "physical_height_mm": _check_display_optional_int(
                entry.get("physical_height_mm"),
                "physical_height_mm", 1, MAX_DISPLAY_MM),
            "x": _check_display_optional_int(
                entry.get("x"), "x",
                -MAX_DISPLAY_OFFSET, MAX_DISPLAY_OFFSET),
            "y": _check_display_optional_int(
                entry.get("y"), "y",
                -MAX_DISPLAY_OFFSET, MAX_DISPLAY_OFFSET),
            "scale": _check_display_optional_number(
                entry.get("scale"), "scale", 0.25, 8.0),
            "orientation": orientation,
            "primary": primary,
        })
    return cleaned


#: Max nodes in one derived digital-world snapshot (bounded,
#: sorted, deterministic — same contract as derive_fungi_network).
MAX_DIGITAL_WORLD_NODES = 200

DIGITAL_WORLD_HONESTY = (
    "Afgeleide view van node-state (provenance: derived). "
    "Displays zijn ADVERTISED door de node; onbekende waarden "
    "blijven null/onbekend en worden nooit ingevuld. "
    "UI-positie/schaal/selectie is lokale editor-state en "
    "verandert nooit de fysieke configuratie."
)


def derive_digital_world(records) -> dict:
    """Pure NODE -> DISPLAY view over node-registry records.

    Input: node dicts as produced by _node_to_json (or any dicts
    with node_id/hostname/telemetry/hardware/derived_status).
    Output: bounded, node_id-sorted snapshot with per-node
    identity/hardware/network/displays. No I/O, no storage, no
    writes — rendering this view never touches node state.
    Unknown display values pass through as None; invalid stored
    display rows are dropped (never break the world on one bad
    row, never invent a replacement)."""
    items = list(records or [])[:MAX_DIGITAL_WORLD_NODES]
    nodes: list[dict] = []
    for record in items:
        if not isinstance(record, dict):
            continue
        node_id = str(record.get("node_id", ""))
        if not node_id:
            continue
        telemetry = record.get("telemetry", {})
        if not isinstance(telemetry, dict):
            telemetry = {}
        hardware = record.get("hardware", [])
        if not isinstance(hardware, list):
            hardware = []
        stored_displays = record.get("displays", [])
        displays: list[dict] = []
        if isinstance(stored_displays, (list, tuple)):
            try:
                displays = check_displays(list(stored_displays))
            except NodeRefusedError:
                displays = []
        gpu_names = [
            str(item.get("identifier", ""))
            for item in hardware
            if isinstance(item, dict)
            and str(item.get("kind", "")) == "gpu"
            and str(item.get("status", "")) == "connected"
        ][:4]
        advertised = record.get("capabilities", [])
        if not isinstance(advertised, list):
            advertised = []
        from .remote_input import MOUSE_CAPABILITY
        nodes.append({
            "node_id": node_id,
            "hostname": str(record.get("hostname", "")),
            "tier": str(record.get("tier", "")),
            "derived_status": str(record.get(
                "derived_status", "unknown")),
            "health_status": str(record.get(
                "health_status", "UNKNOWN")),
            "last_seen": str(record.get("last_seen", "")),
            "identity": {
                "node_id": node_id,
                "hostname": str(record.get("hostname", "")),
                "os": telemetry.get("os"),
                "architecture": telemetry.get("architecture"),
                "platform": telemetry.get("platform"),
            },
            "hardware": {
                "cpu_count": telemetry.get("cpu_count"),
                "memory_total_mb": telemetry.get("memory_total_mb"),
                "gpu": gpu_names,
            },
            "network": {
                "interfaces": telemetry.get("network_interfaces", []),
                "connectivity": str(record.get(
                    "derived_status", "unknown")),
            },
            "displays": displays,
            "display_count": len(displays),
            "capabilities": [str(cap) for cap in advertised[:50]],
            "remote_mouse": (
                "supported"
                if MOUSE_CAPABILITY in {
                    str(cap).strip().lower() for cap in advertised}
                else "unsupported"),
            "provenance": "derived",
        })
    nodes.sort(key=lambda item: item["node_id"])
    return {
        "nodes": nodes,
        "node_count": len(nodes),
        "display_count": sum(item["display_count"] for item in nodes),
        "provenance": "derived",
        "honesty": DIGITAL_WORLD_HONESTY,
    }
