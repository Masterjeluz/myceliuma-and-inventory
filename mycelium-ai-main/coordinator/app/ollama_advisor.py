"""Local Ollama advisor for Mycelium (M8.1, read-only advice only).

Flow: operator question + explicitly supplied, curated INVENTory records
-> bounded prompt -> local Ollama model -> text advice. Nothing else.

Hard limits, all tested:

- network: exactly one endpoint, POST {base_url}/api/generate, where the
  base URL must be loopback (127.0.0.1, localhost, ::1); redirects refused;
  timeout at most 5 seconds; every failure mode closes to OllamaUnavailable.
- prompt: question capped, record count capped, total context capped;
  paths redacted; file contents never accepted (records carry
  metadata text only); provenance of every record preserved in context.
- output: plain text advice plus a source list. No proposals, no tasks,
  no approvals, no dispatch. Coupling to the M6/M7 chain is explicitly
  out of scope for this first version and therefore absent here.
"""

import re
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "llama3.1"
GENERATE_PATH = "/api/generate"
MAX_TIMEOUT_SECONDS = 5.0
MAX_QUESTION_LENGTH = 500
MAX_RECORDS = 10
MAX_CONTEXT_LENGTH = 4000
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_PATH_PATTERN = re.compile(r"[A-Za-z]:\\[^\s\"']*|\\\\[^\s\"']+")


class OllamaUnavailable(RuntimeError):
    """Local model unreachable or answered unusably. Always fail-closed."""


class OllamaRefusedError(ValueError):
    """Local validation refused the request; nothing was sent."""


class AdviceSource(BaseModel):
    model_config = ConfigDict(extra="allow")

    entity_id: str = ""
    source_type: str = "unknown"
    human_verified: bool = False


class AdviceResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    question: str = ""
    advice: str = ""
    model: str = ""
    records_used: int = 0
    sources: list[AdviceSource] = Field(default_factory=list)


def _validate_base_url(raw) -> str:
    from urllib.parse import urlsplit
    if not isinstance(raw, str) or not raw.strip():
        raise OllamaRefusedError("Ollama base URL must be non-empty text")
    try:
        parts = urlsplit(raw.strip())
    except ValueError as error:
        raise OllamaRefusedError(f"Invalid Ollama base URL: {error}") from error
    if parts.scheme != "http":
        raise OllamaRefusedError("Ollama base URL must use http")
    if parts.username or parts.password:
        raise OllamaRefusedError("Ollama base URL must not contain credentials")
    host = (parts.hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        raise OllamaRefusedError(
            f"Ollama host '{host or '?'}' is not loopback; refusing")
    return raw.strip()


def redact_paths(text: str) -> str:
    """Replace path text with a marker. Metadata text only."""
    return _PATH_PATTERN.sub("[redacted-path]", text or "")


def _record_text(record: dict) -> tuple[str, AdviceSource]:
    entity_id = str(record.get("entity_id", ""))
    title = redact_paths(str(record.get("title", "")))[:200]
    snippet = redact_paths(str(record.get("snippet", "")))[:500]
    provenance = record.get("provenance") or {}
    if not isinstance(provenance, dict):
        provenance = {}
    source = AdviceSource(
        entity_id=entity_id,
        source_type=str(provenance.get("source_type", "unknown")),
        human_verified=bool(provenance.get("human_verified", False)),
    )
    block = (f"- [{record.get('entity_type', '?')}] {title} ({entity_id})\n"
             f"  {snippet}\n"
             f"  herkomst: {source.source_type}, "
             f"geverifieerd: {source.human_verified}")
    return block, source


def build_prompt(question, records) -> tuple[str, list[AdviceSource]]:
    """Build a bounded prompt from a question plus curated records.

    Deterministic: same inputs always yield the same prompt. Returns the
    prompt and the source list describing exactly which records went in.
    """
    if not isinstance(question, str) or not question.strip():
        raise OllamaRefusedError("Question must be non-empty text")
    cleaned_question = question.strip()
    if len(cleaned_question) > MAX_QUESTION_LENGTH:
        raise OllamaRefusedError(
            f"Question exceeds {MAX_QUESTION_LENGTH} characters")
    if not isinstance(records, (list, tuple)):
        raise OllamaRefusedError("Records must be a list")
    chosen = list(records)[:MAX_RECORDS]
    blocks: list[str] = []
    sources: list[AdviceSource] = []
    for record in chosen:
        if not isinstance(record, dict):
            raise OllamaRefusedError("Each record must be an object")
        block, source = _record_text(record)
        blocks.append(block)
        sources.append(source)
    context = "\n".join(blocks)[:MAX_CONTEXT_LENGTH]
    prompt = (
        "Je bent een lokale adviseur. Beantwoord op basis van onderstaande "
        "wereldmodel-records. Verzin geen feiten die er niet staan.\n\n"
        f"Vraag: {cleaned_question}\n\n"
        f"Context ({len(sources)} records):\n{context}\n\nAdvies:"
    )
    return prompt, sources


class OllamaAdvisor:
    """Read-only advisor against a user-managed local Ollama instance."""

    def __init__(self, base_url=None, model=None, timeout=MAX_TIMEOUT_SECONDS,
                 transport=None):
        raw = base_url if base_url is not None else DEFAULT_BASE_URL
        self.base_url = _validate_base_url(raw)
        if not isinstance(model, str) or not model.strip():
            raise OllamaRefusedError("Model name must be non-empty text")
        self.model = model.strip() if model else DEFAULT_MODEL
        try:
            self.timeout = min(float(timeout), MAX_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            self.timeout = MAX_TIMEOUT_SECONDS
        if self.timeout <= 0:
            self.timeout = MAX_TIMEOUT_SECONDS
        self._transport = transport

    async def advise(self, question, records) -> AdviceResponse:
        """Ask the local model for text advice. Fail-closed on any problem."""
        prompt, sources = build_prompt(question, records)
        cleaned = question.strip()
        try:
            async with httpx.AsyncClient(
                    base_url=self.base_url, timeout=self.timeout,
                    follow_redirects=False,
                    transport=self._transport) as client:
                response = await client.post(
                    GENERATE_PATH,
                    json={"model": self.model, "prompt": prompt,
                          "stream": False})
        except httpx.TimeoutException as error:
            raise OllamaUnavailable(f"Ollama timed out: {error}") from error
        except httpx.HTTPError as error:
            raise OllamaUnavailable(f"Ollama unreachable: {error}") from error
        if response.status_code in (301, 302, 303, 307, 308):
            raise OllamaUnavailable("Ollama redirect refused")
        if response.status_code != 200:
            raise OllamaUnavailable(
                f"Ollama answered with HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as error:
            raise OllamaUnavailable("Ollama answered with invalid JSON") from error
        advice = data.get("response") if isinstance(data, dict) else None
        if not isinstance(advice, str) or not advice.strip():
            raise OllamaUnavailable("Ollama answered without usable text")
        return AdviceResponse(question=cleaned, advice=advice.strip(),
                              model=self.model, records_used=len(sources),
                              sources=sources)
