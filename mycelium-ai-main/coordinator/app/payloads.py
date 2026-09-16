"""Shared payload validation (BIG #16, Fase 11).

One implementation for the security-relevant payload rules
previously forked between events.py and diststate.py. Union
of both banned sets, case-insensitive, including nested
objects (bounded depth): a banned key nested inside
{"outer": {"exec": ...}} refuses exactly like a top-level
one. Limits stay per-caller (bus events are tighter than
sync envelopes); the raised error type stays per-caller so
existing except-clauses keep working.
"""

BANNED_PAYLOAD_KEYS = frozenset({
    "command", "commands", "exec", "execute", "shell", "code",
    "script", "url", "callback", "webhook", "approved",
    "decision", "execute_now", "sql", "query",
})

SUPPORTED_VALUE_TYPES = (
    str, int, float, bool, type(None), list, dict,
)

#: Recursion bound for nested structures. Deep enough for
#: real metadata, shallow enough to keep validation cheap
#: and hostile nesting out.
MAX_NESTING_DEPTH = 5

#: Total visited nodes per payload (list/dict/scalar).
MAX_NODES = 1000

MAX_KEY_CHARS = 80


class PayloadRefusedError(ValueError):
    """Shared payload validation refused; nothing was stored."""


def check_payload(payload, *, max_keys: int = 20,
                  max_value_chars: int = 500,
                  error=PayloadRefusedError) -> dict:
    """Validate a payload object. Fail-closed on shape, keys
    (top-level and nested), value types, sizes and depth."""
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise error("payload must be an object")
    try:
        key_cap = max(1, int(max_keys))
        char_cap = max(1, int(max_value_chars))
    except (TypeError, ValueError):
        raise error("payload limits must be integers")
    if len(payload) > key_cap:
        raise error(f"at most {key_cap} payload keys")
    state = {"seen": 0}
    _check_mapping(payload, depth=0, char_cap=char_cap,
                   error=error, state=state)
    return dict(payload)


def _check_mapping(mapping: dict, *, depth: int, char_cap: int,
                   error, state: dict) -> None:
    if depth > MAX_NESTING_DEPTH:
        raise error("payload nesting too deep; refusing")
    for key, value in mapping.items():
        _count(state, error)
        if not isinstance(key, str) or not key.strip() \
                or len(key) > MAX_KEY_CHARS:
            raise error("payload keys must be short text")
        if key.strip().lower() in BANNED_PAYLOAD_KEYS:
            raise error(
                f"payload key '{key}' would make the payload "
                "executable; refusing")
        _check_value(value, depth=depth, char_cap=char_cap,
                     error=error, state=state, key=key)


def _check_value(value, *, depth: int, char_cap: int, error,
                 state: dict, key: str) -> None:
    _count(state, error)
    if isinstance(value, str):
        if len(value) > char_cap:
            raise error("payload values are capped")
        return
    if isinstance(value, dict):
        _check_mapping(value, depth=depth + 1,
                       char_cap=char_cap, error=error,
                       state=state)
        return
    if isinstance(value, list):
        if depth + 1 > MAX_NESTING_DEPTH:
            raise error("payload nesting too deep; refusing")
        for item in value:
            _check_value(item, depth=depth + 1,
                         char_cap=char_cap, error=error,
                         state=state, key=key)
        return
    if not isinstance(value, SUPPORTED_VALUE_TYPES):
        raise error(
            f"payload value for '{key}' has an unsupported type")


def _count(state: dict, error) -> None:
    state["seen"] = state["seen"] + 1
    if state["seen"] > MAX_NODES:
        raise error("payload has too many nodes; refusing")
