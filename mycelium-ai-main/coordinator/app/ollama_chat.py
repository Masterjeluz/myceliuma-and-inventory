"""Ollama-chat fallback (lokaal, gratis, geen key).

Tweede been naast Hermes voor NPC-antwoorden: Hermes eerst, bij
falen Ollama op loopback, bij falen een eerlijke system-noot (die
laatste stap woont in town_chat). Alleen JSON over HTTP naar
loopback; nooit shell, nooit credentials, nooit non-loopback.
"""

import os

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
BASE_URL_ENV_VAR = "OLLAMA_BASE_URL"
MODEL_ENV_VAR = "OLLAMA_CHAT_MODEL"
DEFAULT_MODEL = "phi4-mini"
MAX_MODEL_LENGTH = 80
REQUEST_TIMEOUT_SECONDS = 120.0


class OllamaRefusedError(ValueError):
    """Lokale validatie geweigerd; niets verzonden."""


class OllamaUnavailable(RuntimeError):
    """Ollama onbereikbaar of zonder bruikbaar antwoord."""


def base_url() -> str:
    """Loopback-only basis-URL. Al het andere wordt geweigerd."""
    raw = str(os.environ.get(BASE_URL_ENV_VAR,
                             DEFAULT_BASE_URL) or "").strip()
    lowered = raw.lower()
    ok = lowered.startswith((
        "http://127.0.0.1", "http://localhost",
        "http://[::1]")) and " " not in raw and len(raw) <= 120
    if not ok:
        raise OllamaRefusedError(
            "Ollama base URL must be an http loopback address")
    return raw.rstrip("/")


def model_name() -> str:
    """Modelnaam: kort, veilige tekens, nooit leeg."""
    import re as _re
    raw = str(os.environ.get(MODEL_ENV_VAR,
                             DEFAULT_MODEL) or "").strip()
    if not raw or len(raw) > MAX_MODEL_LENGTH or not _re.match(
            r"^[A-Za-z0-9_.:-]+$", raw):
        raise OllamaRefusedError(
            "Ollama model must be 1..80 chars "
            "[A-Za-z0-9_.:-]")
    return raw


def ollama_say(npc_id: str, message: str, system: str = "") -> str:
    """Eén chat-beurt via Ollama. Geeft de tekst terug.

    npc_id moet een bekende Hermes-NPC zijn (zelfde cast, zelfde
    regels); het system-prompt komt uit hun definitie. Lege
    antwoorden en fouten worden OllamaUnavailable — de caller
    beslist wat dan (town_chat: eerlijke noot).
    """
    import httpx
    from .hermes_npc import HERMES_NPCS
    npc_key = str(npc_id or "").strip()
    if npc_key not in HERMES_NPCS:
        raise OllamaRefusedError(f"Unknown NPC '{npc_key}'")
    text = str(message or "").strip()
    if not text:
        raise OllamaRefusedError("Message must be non-empty text")
    if len(text) > 2000:
        raise OllamaRefusedError("Message exceeds 2000 characters")
    npc = HERMES_NPCS[npc_key]
    url = base_url() + "/api/chat"
    prompt = str(system or npc.get("system", "") or "").strip()[:2000]
    try:
        response = httpx.post(url, json={
            "model": model_name(),
            "stream": False,
            "options": {"num_predict": 220},
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": text[:2000]},
            ]}, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception as error:
        raise OllamaUnavailable(
            f"Ollama unreachable: {type(error).__name__}")
    if response.status_code != 200:
        raise OllamaUnavailable(
            f"Ollama answered HTTP {response.status_code}")
    try:
        data = response.json()
    except Exception:
        raise OllamaUnavailable("Ollama answered invalid JSON")
    reply = str(((data.get("message") or {}).get("content")
                 or "").strip())
    if not reply:
        raise OllamaUnavailable("Ollama returned an empty reply")
    return reply
