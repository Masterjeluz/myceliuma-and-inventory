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
