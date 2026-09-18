"""Conversation bridge (BIG #30): external AI chats become Mycelium context.

Jelles talks to ChatGPT / Codex / OpenCode / Ollama / Claude / Gemini /
Antigravity / Google AI Studio / ... — those conversations live outside.
This module imports them as data, never as authority:

- parse pasted text / TXT / Markdown / JSON / safe HTML export
- store as conv_... conversation with msg rows (imported provenance)
- deterministic analysis -> OBSERVATION / CANDIDATE findings with evidence
- missed-item detection ("what did we miss?"), each with evidence refs
- NEVER auto-promotes to memory/FACT; NEVER executes imported instructions
- NEVER fetches URLs; NEVER stores credentials (redacted)

Security (fail-closed, tested):
- HTML is stripped to text (no scripts, no forms, no javascript: URLs)
- prompt-injection: imported text is data; analysis prefixes state labels
- fake entity IDs: mentions are candidates, never resolved as truth
- health content is flagged; context packets exclude it unless scoped
- node tokens / api keys are redacted before storage
"""

from __future__ import annotations

import hashlib
import html as _html
import json as _json
import re as _re
import secrets as _secrets
import time as _time
from html.parser import HTMLParser as _HTMLParser
from typing import Any

SUPPORTED_FORMATS = frozenset({"plain", "markdown", "txt", "json", "html"})

KNOWN_PLATFORMS = (
    "chatgpt", "codex", "opencode", "ollama", "chatgpt-live",
    "google-ai-studio", "antigravity", "claude", "gemini", "other",
)

MAX_RAW_CHARS = 200_000
MAX_MESSAGES = 200
MAX_MESSAGE_CHARS = 4000
MAX_TITLE_CHARS = 120

IMPORT_SOURCE_TYPE = "imported"
EXECUTION_STATE_IMPORTED = "IMPORTED"


class BridgeRefusedError(ValueError):
    """Import/analysis refused; nothing was stored."""


# -- ids -------------------------------------------------------------------

def generate_import_id() -> str:
    return f"conv_{int(_time.time() * 1000):x}{_secrets.token_hex(4)}"


def generate_import_message_id() -> str:
    return f"msg_{int(_time.time() * 1000):x}{_secrets.token_hex(4)}"


def content_hash(raw: str) -> str:
    normalized = "\n".join(
        line.strip() for line in str(raw or "").splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# -- sanitizing --------------------------------------------------------------

_PLATFORM_RE = _re.compile(r"^[A-Za-z0-9 _.\-]{1,40}$")
_SECRET_RE = _re.compile(
    r"(?i)(token|bearer|api[_-]?key|secret|password|passwd|auth[_-]?token)"
    r"\s*[:=]\s*\S+")
_URL_RE = _re.compile(r"https?://[^\s<>\"]{1,300}")
_ENTITY_RE = _re.compile(
    r"\b(obj|proj|idea|rel|evt|hw|sns|cam|loc|mod|task|act|file|mem|"
    r"mission|conv)_[A-Za-z0-9._\-]{1,60}\b")
_HEALTH_RE = _re.compile(
    r"(?i)\b(gezondheid|health|garmin|gewicht|weight|slaap|sleep|"
    r"hartslag|heart.?rate|bloeddruk|calorie|voeding|nutrition|"
    r"diagnose|diagnosis|medic|dokter|doctor|ziekte|disease)\b")


def check_platform(platform: str) -> str:
    cleaned = str(platform or "").strip().lower()[:40]
    if not cleaned:
        raise BridgeRefusedError("source_platform is required")
    if not _PLATFORM_RE.match(cleaned):
        raise BridgeRefusedError(
            "source_platform must be 1..40 chars [A-Za-z0-9 _.-]")
    return cleaned


def check_format(fmt: str) -> str:
    cleaned = str(fmt or "").strip().lower()
    if cleaned not in SUPPORTED_FORMATS:
        raise BridgeRefusedError(
            f"Unsupported format '{fmt}'; expected one of "
            f"{sorted(SUPPORTED_FORMATS)}")
    return cleaned


def redact_secrets(text: str) -> str:
    return _SECRET_RE.sub(
        lambda m: m.group(0).split(":")[0].split("=")[0] + "=[REDACTED]",
        str(text or ""))


def _strip_controls(text: str) -> str:
    out = []
    for char in str(text or ""):
        if char in ("\n", "\t"):
            out.append(char)
        elif ord(char) < 32:
            out.append(" ")
        else:
            out.append(char)
    return "".join(out)


_TAG_BLOCK_RE = _re.compile(
    r"<\s*(script|style|iframe|object|embed|form)\b.*?"
    r"<\s*/\s*\1\s*>",
    _re.IGNORECASE | _re.DOTALL)
_TAG_RE = _re.compile(r"</?[A-Za-z][^>]{0,200}>")


def _neutralize_markup(text: str) -> str:
    """Strip active markup from pasted text. Stored imports keep
    words, never live tags: script/style/form blocks are removed
    wholesale, remaining tags collapse to spaces. Plain comparisons
    like 'a < b' (no letter-tag shape) survive untouched."""
    cleaned = _TAG_BLOCK_RE.sub(" ", str(text or ""))
    return _TAG_RE.sub(" ", cleaned)


class _TextExtractor(_HTMLParser):
    """Text-only HTML extraction. Drops scripts/styles/forms/inputs."""

    _DROP = frozenset({
        "script", "style", "iframe", "object", "embed", "form",
        "input", "button", "select", "textarea", "noscript", "canvas",
    })

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag.lower() in self._DROP:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._DROP and self._depth:
            self._depth -= 1
        if tag.lower() in ("p", "br", "div", "li", "tr", "h1", "h2",
                           "h3", "h4") and not self._depth:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._depth:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        raw = _html.unescape(raw)
        raw = _re.sub(r"javascript\s*:", "", raw, flags=_re.IGNORECASE)
        return raw


def html_to_text(raw_html: str) -> str:
    if len(str(raw_html or "")) > MAX_RAW_CHARS:
        raise BridgeRefusedError("HTML export exceeds size limit")
    parser = _TextExtractor()
    try:
        parser.feed(str(raw_html or "")[:MAX_RAW_CHARS])
    except Exception as exc:
        raise BridgeRefusedError(
            f"HTML could not be parsed safely: {exc}") from exc
    return parser.text()


# -- parsing -----------------------------------------------------------------

_ROLE_PREFIX_RE = _re.compile(
    r"^\s*(user|jelles|human|you|assistant|chatgpt|gpt|codex|opencode|"
    r"ollama|qwen|claude|gemini|gemini-live|chatgpt-live|antigravity|"
    r"ai|bot|system|agent)\s*[:\u2013\u2014\-]\s*(.*)$",
    _re.IGNORECASE)

_ROLE_MAP = {
    "user": "user", "jelles": "user", "human": "user", "you": "user",
    "assistant": "assistant", "chatgpt": "assistant", "gpt": "assistant",
    "codex": "assistant", "opencode": "assistant", "ollama": "assistant",
    "qwen": "assistant", "claude": "assistant", "gemini": "assistant",
    "gemini-live": "assistant", "chatgpt-live": "assistant",
    "antigravity": "assistant", "ai": "assistant", "bot": "assistant",
    "system": "system", "agent": "agent",
}


def _split_plain(text: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    current_role = ""
    current_lines: list[str] = []
    participants: list[str] = []

    def flush() -> None:
        if current_role and "".join(current_lines).strip():
            messages.append({
                "role": current_role,
                "content": "\n".join(current_lines).strip(),
                "speaker": participants[-1] if participants else current_role,
            })

    for line in str(text or "").splitlines():
        match = _ROLE_PREFIX_RE.match(line)
        if match:
            flush()
            speaker = match.group(1).strip().lower()
            role = _ROLE_MAP.get(speaker, "user")
            current_role = role
            participants.append(speaker)
            current_lines = [match.group(2)]
        elif current_role:
            current_lines.append(line)
        elif line.strip():
            current_role = "user"
            participants.append("pasted")
            current_lines = [line]
    flush()
    if not messages and str(text or "").strip():
        messages.append({"role": "user", "content": str(text).strip(),
                         "speaker": "pasted"})
    return messages


def _split_json(raw: str) -> list[dict[str, str]]:
    try:
        data = _json.loads(raw)
    except Exception as exc:
        raise BridgeRefusedError(
            f"JSON could not be parsed: {exc}") from exc
    items: Any = data
    if isinstance(data, dict):
        for key in ("messages", "turns", "conversation", "items"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
        else:
            raise BridgeRefusedError(
                "JSON needs a messages/turns/conversation list")
    if not isinstance(items, list) or not items:
        raise BridgeRefusedError("JSON holds no messages")
    messages: list[dict[str, str]] = []
    for entry in items[:MAX_MESSAGES]:
        if isinstance(entry, str):
            messages.append({"role": "user", "content": entry,
                             "speaker": "json"})
            continue
        if not isinstance(entry, dict):
            continue
        role_raw = str(entry.get("role", entry.get("speaker",
                                                  entry.get("author",
                                                            "user")))
                         ).strip().lower()
        role = _ROLE_MAP.get(role_raw, "user")
        content = entry.get("content", entry.get("text", entry.get(
            "message", "")))
        if isinstance(content, list):
            content = "\n".join(str(part.get("text", part))
                                if isinstance(part, dict) else str(part)
                                for part in content)
        content = str(content or "").strip()
        if not content:
            continue
        messages.append({"role": role, "content": content,
                         "speaker": role_raw[:40] or "json"})
    if not messages:
        raise BridgeRefusedError("JSON holds no usable message text")
    return messages


def parse_import_content(raw: str, fmt: str) -> list[dict[str, str]]:
    """Parse raw import to [{role, content, speaker}]. Fail-closed."""
    fmt = check_format(fmt)
    if not isinstance(raw, str) or not raw.strip():
        raise BridgeRefusedError("Nothing to import: empty content")
    if len(raw) > MAX_RAW_CHARS:
        raise BridgeRefusedError(
            f"Content exceeds {MAX_RAW_CHARS} characters")
    cleaned = _neutralize_markup(
        _strip_controls(redact_secrets(raw)))
    if fmt == "json":
        parsed = _split_json(cleaned)
    elif fmt == "html":
        parsed = _split_plain(html_to_text(cleaned))
    else:
        parsed = _split_plain(cleaned)
    if not parsed:
        raise BridgeRefusedError("No messages found in this import")
    if len(parsed) > MAX_MESSAGES:
        raise BridgeRefusedError(
            f"Too many messages ({len(parsed)} > {MAX_MESSAGES})")
    out: list[dict[str, str]] = []
    for item in parsed:
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        role = str(item.get("role", "user")).strip().lower()
        if role not in ("user", "assistant", "system", "agent"):
            role = "user"
        if len(content) > MAX_MESSAGE_CHARS:
            for start in range(0, len(content), MAX_MESSAGE_CHARS):
                chunk = content[start:start + MAX_MESSAGE_CHARS]
                if chunk.strip():
                    out.append({"role": role, "content": chunk.strip(),
                                "speaker": str(item.get("speaker",
                                                        role))[:40]})
        else:
            out.append({"role": role, "content": content,
                        "speaker": str(item.get("speaker", role))[:40]})
        if len(out) >= MAX_MESSAGES:
            break
    if not out:
        raise BridgeRefusedError("No importable messages remain")
    return out[:MAX_MESSAGES]


# -- persistence ---------------------------------------------------------------

def init_bridge_tables() -> None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS conversation_imports (
            conversation_id TEXT PRIMARY KEY,
            source_platform TEXT NOT NULL DEFAULT '',
            imported_at TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            participants TEXT NOT NULL DEFAULT '[]',
            message_count INTEGER NOT NULL DEFAULT 0,
            content_hash TEXT NOT NULL DEFAULT '',
            execution_state TEXT NOT NULL DEFAULT 'IMPORTED',
            provenance TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS conversation_analyses (
            conversation_id TEXT PRIMARY KEY,
            record TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT ''
        );
        """)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def import_conversation(title: str, raw: str, fmt: str,
                        platform: str) -> dict:
    """Parse + persist an external conversation. Returns import record."""
    from .database import chat_connection, dump, init_chat_database
    fmt = check_format(fmt)
    platform = check_platform(platform)
    title = str(title or "").strip()[:MAX_TITLE_CHARS]
    if not title:
        raise BridgeRefusedError("A title is required")
    messages = parse_import_content(raw, fmt)
    digest = content_hash(raw)
    init_bridge_tables()
    init_chat_database()
    conversation_id = generate_import_id()
    created = _now()
    participants = sorted({str(item.get("speaker", item["role"]))
                           for item in messages})[:20]
    with chat_connection() as db:
        dup = db.execute(
            "SELECT conversation_id FROM conversation_imports "
            "WHERE content_hash=?", (digest,)).fetchone()
        if dup is not None:
            raise BridgeRefusedError(
                "This exact content was already imported as "
                f"{dup['conversation_id']}")
        db.execute("""INSERT INTO conversations
        (conversation_id, title, project_ref, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(conversation_id) DO NOTHING""",
                   (conversation_id, title, "", created))
        for item in messages:
            db.execute("""INSERT INTO messages
            (message_id, conversation_id, role, content, created_at,
             provenance, sources) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                       (generate_import_message_id(), conversation_id,
                        item["role"], item["content"], created,
                        dump({"source_type": IMPORT_SOURCE_TYPE,
                              "creator_id": f"conversation-import:"
                                            f"{platform}",
                              "human_verified": False,
                              "notes": "external import; data, never "
                                       "authority"}),
                        "[]"))
        db.execute("""INSERT INTO conversation_imports
        (conversation_id, source_platform, imported_at, title,
         participants, message_count, content_hash, execution_state,
         provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                   (conversation_id, platform, created, title,
                    dump(participants), len(messages), digest,
                    EXECUTION_STATE_IMPORTED,
                    dump({"source_type": IMPORT_SOURCE_TYPE,
                          "creator_id": f"conversation-import:{platform}",
                          "human_verified": False})))
    return {"conversation_id": conversation_id,
            "source_platform": platform, "imported_at": created,
            "title": title, "participants": participants,
            "message_count": len(messages), "content_hash": digest,
            "execution_state": EXECUTION_STATE_IMPORTED,
            "provenance": {"source_type": IMPORT_SOURCE_TYPE,
                           "creator_id": f"conversation-import:{platform}",
                           "human_verified": False}}


def get_import(conversation_id: str) -> dict | None:
    from .database import chat_connection, load
    init_bridge_tables()
    with chat_connection() as db:
        row = db.execute(
            "SELECT * FROM conversation_imports WHERE conversation_id=?",
            (conversation_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["participants"] = load(data.get("participants") or "[]")
        data["provenance"] = load(data.get("provenance") or "{}")
        return data


def list_imports(limit: int = 50) -> list[dict]:
    from .database import chat_connection, load
    init_bridge_tables()
    count = max(1, min(int(limit or 50), 100))
    with chat_connection() as db:
        rows = db.execute(
            "SELECT * FROM conversation_imports ORDER BY imported_at "
            "DESC LIMIT ?", (count,)).fetchall()
    out = []
    for row in rows:
        data = dict(row)
        data["participants"] = load(data.get("participants") or "[]")
        data["provenance"] = load(data.get("provenance") or "{}")
        out.append(data)
    return out


def import_messages(conversation_id: str) -> list[dict]:
    from .database import chat_connection
    init_bridge_tables()
    with chat_connection() as db:
        rows = db.execute(
            "SELECT * FROM messages WHERE conversation_id=? "
            "ORDER BY created_at ASC LIMIT 200",
            (conversation_id,)).fetchall()
    return [dict(row) for row in rows]


# -- analysis ------------------------------------------------------------------

_SENT_RE = _re.compile(r"(?<=[.!?\u2026])\s+|\n+")


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENT_RE.split(str(text or ""))
            if part.strip()][:60]


_FINDING_RULES: list[tuple[str, _re.Pattern[str], str]] = [
    ("decision", _re.compile(
        r"(?i)\b(besloten|besluit|decided|decision|akkoord|agreed|"
        r"gaan we doen|we kiezen|conclusie|conclusion)\b"), "CANDIDATE"),
    ("todo", _re.compile(
        r"(?i)\b(todo|action item|actiepunt|moet nog|moeten nog|"
        r"nog doen|afspraak|deadline|vervolgactie|follow.?up)\b"),
     "CANDIDATE"),
    ("open_question", _re.compile(r"\?\s*$"), "OBSERVATION"),
    ("open_question", _re.compile(
        r"(?i)\b(open vraag|open question|onduidelijk|unclear|"
        r"nog uitzoeken|to be determined|tbd|weet (ik|we) niet)\b"),
     "OBSERVATION"),
    ("idea", _re.compile(
        r"(?i)\b(idee|idea|voorstel|proposal|suggestie|suggestion|"
        r"wat als|what if|zouden we|could we|misschien|maybe we)\b"),
     "CANDIDATE"),
    ("technical_claim", _re.compile(
        r"(?i)\b(werkt|works|bewering|claim|feit|fact|meting|measurement|"
        r"\d+\s?(mm|cm|m\b|km|ms|s\b|min|uur|hour|watt|volt|amp|gb|mb|"
        r"ghz|mhz|rpm|gram|kg)\b)"), "OBSERVATION"),
    ("proposed_action", _re.compile(
        r"(?i)\b(stel voor|propose|adviseer|recommend|aanrader|"
        r"je zou moeten|you should|probeer|try)\b"), "CANDIDATE"),
    ("project_mention", _re.compile(
        r"(?i)\b(project|camper|werkplaats|workshop|printer|insta360|"
        r"linux|laptop|node|mission|research|inventory)\b"), "OBSERVATION"),
]


def analyze_import(conversation_id: str) -> dict:
    """Deterministic analysis. Findings are OBSERVATION/CANDIDATE only."""
    from .database import chat_connection, dump
    meta = get_import(conversation_id)
    if meta is None:
        raise BridgeRefusedError("Unknown imported conversation")
    messages = import_messages(conversation_id)
    if not messages:
        raise BridgeRefusedError("Imported conversation has no messages")
    findings: list[dict] = []
    seen_sentences: dict[str, list[int]] = {}
    for index, message in enumerate(messages):
        role = str(message.get("role", "user"))
        for sentence in _sentences(str(message.get("content", ""))):
            norm = _re.sub(r"\s+", " ", sentence.strip().lower())[:200]
            if norm:
                seen_sentences.setdefault(norm, []).append(index)
            for kind, pattern, state in _FINDING_RULES:
                if pattern.search(sentence):
                    findings.append({
                        "kind": kind, "state": state,
                        "text": sentence[:280],
                        "message_index": index,
                        "message_role": role,
                        "message_id": str(message.get("message_id", "")),
                        "evidence": sentence[:200],
                        "conversation_id": conversation_id})
                    break
            for entity in _ENTITY_RE.findall(sentence):
                pass
            for match in _ENTITY_RE.finditer(sentence):
                findings.append({
                    "kind": "entity_mention", "state": "CANDIDATE",
                    "text": f"Mogelijke entity-verwijzing: {match.group(0)}",
                    "message_index": index, "message_role": role,
                    "message_id": str(message.get("message_id", "")),
                    "evidence": sentence[:200],
                    "conversation_id": conversation_id,
                    "entity_candidate": match.group(0)})
            for match in _URL_RE.finditer(sentence):
                findings.append({
                    "kind": "source_reference", "state": "OBSERVATION",
                    "text": f"Bronverwijzing (niet opgehaald): "
                            f"{match.group(0)[:120]}",
                    "message_index": index, "message_role": role,
                    "message_id": str(message.get("message_id", "")),
                    "evidence": sentence[:200],
                    "conversation_id": conversation_id})
                break
    repeats: list[dict] = []
    for norm, indices in seen_sentences.items():
        unique = sorted(set(indices))
        if len(unique) >= 2 and len(norm) > 24:
            repeats.append({
                "kind": "repeated_topic", "state": "OBSERVATION",
                "text": f"Herhaald onderwerp ({len(unique)}x): "
                        f"{norm[:180]}",
                "message_index": unique[0],
                "message_role": "",
                "message_id": "",
                "evidence": f"messages {unique[:6]}",
                "conversation_id": conversation_id})
    contradictions: list[dict] = []
    lowered = [(idx, str(msg.get("content", "")).lower())
               for idx, msg in enumerate(messages)]
    for word in ("printer", "camera", "node", "printer", "research",
                 "project", "inventory"):
        positive = [idx for idx, text in lowered
                    if f" {word}" in f" {text}" and "werkt" in text]
        negative = [idx for idx, text in lowered
                    if word in text and ("niet" in text or "geen" in text
                                         or "not " in text)]
        if positive and negative:
            contradictions.append({
                "kind": "possible_contradiction", "state": "CANDIDATE",
                "text": f"Mogelijke tegenspraak over '{word}': "
                        f"positief in message {positive[0]}, "
                        f"negatief in message {negative[0]}",
                "message_index": negative[0],
                "message_role": "",
                "message_id": "",
                "evidence": f"messages {positive[0]} vs {negative[0]}",
                "conversation_id": conversation_id})
            if len(contradictions) >= 5:
                break
    contains_health = any(
        _HEALTH_RE.search(str(msg.get("content", "")))
        for msg in messages)
    record = {
        "conversation_id": conversation_id,
        "created_at": _now(),
        "message_count": len(messages),
        "contains_health": bool(contains_health),
        "findings": (findings[:120] + repeats[:10]
                     + contradictions[:5])[:140],
        "counts": {
            "findings": len(findings),
            "repeated_topics": len(repeats),
            "possible_contradictions": len(contradictions)},
        "note": "Deterministische extractie. Alles is OBSERVATION of "
                "CANDIDATE; niets is als feit opgeslagen. Promotie naar "
                "memory loopt via de bestaande provenance-flow.",
        "provenance": {"source_type": "ai-generated",
                       "creator_id": "conversation-analysis",
                       "human_verified": False},
    }
    init_bridge_tables()
    with chat_connection() as db:
        db.execute("""INSERT INTO conversation_analyses
        (conversation_id, record, created_at) VALUES (?, ?, ?)
        ON CONFLICT(conversation_id) DO UPDATE SET record=excluded.record,
        created_at=excluded.created_at""",
                   (conversation_id, dump(record), record["created_at"]))
    return record


def load_analysis(conversation_id: str) -> dict | None:
    from .database import chat_connection, load
    init_bridge_tables()
    with chat_connection() as db:
        row = db.execute(
            "SELECT record FROM conversation_analyses WHERE "
            "conversation_id=?", (conversation_id,)).fetchone()
    if row is None:
        return None
    return load(row["record"])


# -- missed items --------------------------------------------------------------

_INVENTORY_HINT_RE = _re.compile(
    r"(?i)\b(object|spullen|voorraad|inventory|obj_|hardware|sensor|"
    r"onderdeel|parts?)\b")
_FAB_HINT_RE = _re.compile(
    r"(?i)\b(3d|print|slic|stl|gcode|g-code|filament|mesh|printer)\b")


def missed_items(conversation_id: str,
                 analysis: dict | None = None) -> list[dict]:
    """'What did we miss?' — only evidence-backed suggestions."""
    record = analysis or load_analysis(conversation_id)
    if record is None:
        record = analyze_import(conversation_id)
    findings = record.get("findings", [])
    messages = import_messages(conversation_id)
    full_text = "\n".join(str(msg.get("content", ""))
                          for msg in messages)
    entity_mentions = {str(item.get("entity_candidate", ""))
                       for item in findings
                       if item.get("kind") == "entity_mention"}
    entity_mentions.discard("")
    has_url = any(item.get("kind") == "source_reference"
                  for item in findings)
    missed: list[dict] = []

    def add(kind: str, text: str, evidence: str,
            message_index: int | None) -> None:
        missed.append({"kind": kind, "state": "CANDIDATE", "text": text,
                       "evidence": evidence[:220],
                       "conversation_id": conversation_id,
                       "message_index": message_index})

    for item in findings:
        if item.get("kind") in ("idea", "todo", "open_question",
                                "proposed_action") \
                and not entity_mentions \
                and item.get("kind") != "open_question":
            add("unlinked_topic",
                "Dit onderwerp werd besproken maar is niet gekoppeld "
                "aan een project of entity.",
                str(item.get("evidence", "")), item.get("message_index"))
            break
    for item in findings:
        if item.get("kind") == "idea":
            add("idea_without_task",
                "Dit idee werd genoemd maar heeft nog geen task of "
                "missie.",
                str(item.get("evidence", "")), item.get("message_index"))
            break
    claims = [item for item in findings
              if item.get("kind") == "technical_claim"]
    if claims and not has_url:
        first = claims[0]
        add("claim_without_source",
            "Deze technische claim heeft nog geen bron.",
            str(first.get("evidence", "")), first.get("message_index"))
    if _INVENTORY_HINT_RE.search(full_text) and not entity_mentions:
        add("inventory_gap",
            "Dit onderdeel lijkt relevant voor INVENTory maar heeft "
            "geen entity-koppeling.",
            full_text[_INVENTORY_HINT_RE.search(full_text).start()  # type: ignore[union-attr]
                      - 60:_INVENTORY_HINT_RE.search(full_text).start()  # type: ignore[union-attr]
                      + 120], None)
    if _FAB_HINT_RE.search(full_text) and not entity_mentions:
        add("fabrication_gap",
            "Dit gesprek noemt een 3D/print-workflow die nog niet aan "
            "een model of file is gekoppeld.",
            full_text[_FAB_HINT_RE.search(full_text).start()  # type: ignore[union-attr]
                      - 60:_FAB_HINT_RE.search(full_text).start()  # type: ignore[union-attr]
                      + 120], None)
    for item in findings:
        if item.get("kind") == "open_question":
            add("open_question",
                "Dit gesprek bevat een open vraag die nog wacht op een "
                "antwoord.",
                str(item.get("evidence", "")), item.get("message_index"))
            break
    return missed[:10]


# -- cross-import archaeology (BIG #31) ----------------------------------------

_COMPARE_WORD_RE = _re.compile(r"[a-zA-Z0-9]{4,}")


def _compare_key(sentence: str) -> str:
    words = sorted({word.lower() for word in
                    _COMPARE_WORD_RE.findall(sentence or "")})
    return " ".join(words[:12])


def compare_imports(limit: int = 10) -> dict:
    """Compare all imported conversations: repeated topics across
    imports, shared platforms, shared entity candidates. Every
    comparison carries evidence (which conversations, which
    messages). Deterministic, read-only."""
    metas = list_imports(limit=20)
    analyses: dict[str, dict] = {}
    for meta in metas:
        conversation_id = meta["conversation_id"]
        try:
            analyses[conversation_id] = (
                load_analysis(conversation_id)
                or analyze_import(conversation_id))
        except BridgeRefusedError:
            continue
    by_sentence: dict[str, list[dict]] = {}
    for conversation_id, record in analyses.items():
        for item in record.get("findings", []):
            if item.get("kind") not in (
                    "idea", "todo", "open_question", "decision",
                    "technical_claim", "proposed_action"):
                continue
            key = _compare_key(str(item.get("text", "")))
            if len(key) < 12:
                continue
            by_sentence.setdefault(key, []).append({
                "conversation_id": conversation_id,
                "message_index": item.get("message_index"),
                "kind": item.get("kind", ""),
                "text": str(item.get("text", ""))[:180],
            })
    repeated = [
        {"topic": key[:160], "state": "OBSERVATION",
         "occurrences": occurrences}
        for key, occurrences in by_sentence.items()
        if len({occ["conversation_id"] for occ in occurrences}) >= 2
    ][: max(1, min(int(limit or 10), 20))]
    platforms: dict[str, int] = {}
    for meta in metas:
        platform = str(meta.get("source_platform", "other"))
        platforms[platform] = platforms.get(platform, 0) + 1
    shared_entities: dict[str, list[str]] = {}
    for conversation_id, record in analyses.items():
        for item in record.get("findings", []):
            candidate = str(item.get("entity_candidate", ""))
            if candidate:
                shared_entities.setdefault(candidate, []).append(
                    conversation_id)
    shared = {entity: sorted(set(conversations))
              for entity, conversations in shared_entities.items()
              if len(set(conversations)) >= 2}
    return {"imports_compared": len(analyses),
            "repeated_across_imports": repeated,
            "platforms": platforms,
            "shared_entity_candidates": dict(list(shared.items())[:20]),
            "note": "Herhaling over gesprekken heen is een OBSERVATION "
                    "met evidence; koppeling aan projecten blijft "
                    "mensenwerk."}


def render_import_markdown(conversation_id: str) -> str:
    """One import as portable Markdown (OPEN AS MARKDOWN): messages,
    analysis states, missed items, provenance. For reading and
    re-importing elsewhere — never authority."""
    meta = get_import(conversation_id)
    if meta is None:
        raise BridgeRefusedError("Unknown imported conversation")
    messages = import_messages(conversation_id)
    analysis = load_analysis(conversation_id) or {}
    lines = [f"# {meta.get('title', conversation_id)}", "",
             f"source_platform: {meta.get('source_platform', '')}",
             f"imported_at: {meta.get('imported_at', '')}",
             f"messages: {meta.get('message_count', 0)}",
             f"execution_state: {meta.get('execution_state', '')}",
             "provenance: imported / human_verified=false", "",
             "## Messages", ""]
    for message in messages:
        lines.append(f"### {message.get('role', 'user')}")
        lines.append(str(message.get("content", ""))[:3500])
        lines.append("")
    lines.append("## Analysis (OBSERVATION / CANDIDATE — never fact)")
    lines.append("")
    for item in analysis.get("findings", [])[:60]:
        lines.append(
            f"- [{item.get('state', '')}] {item.get('kind', '')}: "
            f"{str(item.get('text', ''))[:220]} "
            f"(evidence: {str(item.get('evidence', ''))[:140]})")
    if not analysis.get("findings"):
        lines.append("- (not analyzed yet)")
    lines.append("")
    lines.append("## What was missed")
    lines.append("")
    for item in missed_items(conversation_id, analysis or None)[:10]:
        lines.append(
            f"- {item.get('kind', '')}: "
            f"{str(item.get('text', ''))[:220]}")
    return "\n".join(lines)[:60000]
