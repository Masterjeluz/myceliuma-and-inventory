"""Human-interface foundation for Mycelium (BIG #9).

Separates the HUMAN INTERFACE from the BRAIN (coordinator) and
from NODE EXECUTION. The interface is never a second
coordinator: adapters produce/consume structured messages and
events, while all decisions (intent, proposals, approvals,
routing, execution, verification) stay in the existing
coordinator machinery.

Pieces (all fail-closed, all bounded):

- InterfaceAdapter: text in, text/voice/notification/status
  out. TextInterface is real (drives the chat flow);
  VoiceInterface is architecture (STT in, TTS out) without any
  microphone/speaker library coupling.
- InterfaceMessage: envelope around one conversation turn with
  interface/session/node identity, input/output types and
  provenance. Converges voice and text as early as possible:
  after STT, a voice turn IS a text turn plus provenance.
- InterfaceSession: active/idle/expired/revoked lifecycle for
  one interface endpoint. A session is not a credential and
  never doubles as node identity.

Rules (tested):

- input/output types are closed literals; content is capped;
  no executable content travels through messages.
- voice transcription is interpretation input, never FACT and
  never authorization (see voice.py for the approval rules).
- sessions expire (default 24h, hard cap 7d); revoked and
  expired sessions refuse; session ids never authenticate nodes.
"""

import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .inventory_read import Provenance

InterfaceKind = Literal["text", "voice"]
VALID_INTERFACE_KINDS = frozenset({"text", "voice"})

InputType = Literal["text", "voice", "image", "camera", "event",
                    "system"]
VALID_INPUT_TYPES = frozenset({"text", "voice", "image", "camera",
                               "event", "system"})

OutputType = Literal["text", "voice", "notification", "event",
                     "status"]
VALID_OUTPUT_TYPES = frozenset({"text", "voice", "notification",
                                "event", "status"})

SessionStatus = Literal["active", "idle", "expired", "revoked"]
VALID_SESSION_STATUSES = frozenset({"active", "idle", "expired",
                                    "revoked"})

MAX_CONTENT_CHARS = 4000
MAX_METADATA_KEYS = 20

SESSION_TTL_SECONDS = 24 * 3600
SESSION_MAX_TTL_SECONDS = 7 * 24 * 3600


class InterfaceRefusedError(ValueError):
    """Local validation refused; nothing was stored or sent."""


class InterfaceMessage(BaseModel):
    """One interface turn envelope. Structured, bounded,
    attributable — never executable."""

    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=3, max_length=80)
    conversation_id: str = Field(min_length=3, max_length=80)
    session_id: str = Field(default="", max_length=80)
    interface_id: str = Field(default="", max_length=80)
    node_id: str = Field(default="", max_length=80)
    role: str = Field(min_length=1, max_length=20)
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    input_type: str = Field(default="text", max_length=20)
    output_type: str = Field(default="text", max_length=20)
    created_at: str = ""
    provenance: Provenance = Field(default_factory=Provenance)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InterfaceSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=3, max_length=80)
    interface_id: str = Field(min_length=1, max_length=80)
    node_id: str = Field(default="", max_length=80)
    conversation_id: str = Field(default="", max_length=80)
    status: str = Field(default="active", max_length=20)
    created_at: str = ""
    last_seen: str = ""
    expires_at: str = ""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_session_id() -> str:
    return f"sess-{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def generate_interface_id(kind: str = "text") -> str:
    if kind not in VALID_INTERFACE_KINDS:
        raise InterfaceRefusedError(
            f"Unknown interface kind '{kind}'")
    return f"iface-{kind}-{secrets.token_hex(4)}"


def _check_metadata(metadata) -> dict:
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise InterfaceRefusedError("metadata must be an object")
    if len(metadata) > MAX_METADATA_KEYS:
        raise InterfaceRefusedError(
            f"at most {MAX_METADATA_KEYS} metadata keys")
    for key, value in metadata.items():
        if not isinstance(key, str) or not key.strip() \
                or len(key) > 80:
            raise InterfaceRefusedError(
                "metadata keys must be short text")
        if isinstance(value, str) and len(value) > 1000:
            raise InterfaceRefusedError(
                "metadata values are capped at 1000 chars")
    return dict(metadata)


def new_interface_message(message_id: str, conversation_id: str,
                          role: str, content: str, *,
                          session_id: str = "",
                          interface_id: str = "",
                          node_id: str = "",
                          input_type: str = "text",
                          output_type: str = "text",
                          provenance: Provenance | None = None,
                          metadata: dict | None = None
                          ) -> InterfaceMessage:
    """Build one validated interface envelope. Fail-closed on
    role/content/types/provenance."""
    from .conversations import Message
    try:
        Message.check_role(role)
    except ValueError as error:
        raise InterfaceRefusedError(str(error)) from error
    if not isinstance(content, str) or not content.strip():
        raise InterfaceRefusedError(
            "Interface content must be non-empty text")
    if len(content) > MAX_CONTENT_CHARS:
        raise InterfaceRefusedError(
            f"Interface content exceeds {MAX_CONTENT_CHARS} chars")
    if input_type not in VALID_INPUT_TYPES:
        raise InterfaceRefusedError(
            f"Unknown input type '{input_type}'")
    if output_type not in VALID_OUTPUT_TYPES:
        raise InterfaceRefusedError(
            f"Unknown output type '{output_type}'")
    if role in ("assistant", "agent") and provenance is not None \
            and provenance.human_verified:
        raise InterfaceRefusedError(
            "Assistant/agent turns must not claim human "
            "verification")
    return InterfaceMessage(
        message_id=message_id, conversation_id=conversation_id,
        session_id=session_id[:80], interface_id=interface_id[:80],
        node_id=node_id[:80], role=role, content=content.strip(),
        input_type=input_type, output_type=output_type,
        created_at=now(),
        provenance=provenance or Provenance(
            source_type=("user-created" if role == "user"
                         else "ai-generated"),
            creator_id=interface_id or "interface",
            human_verified=(role == "user")),
        metadata=_check_metadata(metadata))


def new_session(interface_id: str, *, node_id: str = "",
                conversation_id: str = "",
                ttl_seconds: int = SESSION_TTL_SECONDS
                ) -> InterfaceSession:
    """Open one interface session. A session tracks presence, not
    permission: it never authenticates a node and never carries
    credentials."""
    if not isinstance(interface_id, str) or not interface_id.strip():
        raise InterfaceRefusedError(
            "Session needs an interface_id")
    try:
        ttl = int(ttl_seconds)
    except (TypeError, ValueError):
        raise InterfaceRefusedError("ttl must be an integer")
    if ttl <= 0 or ttl > SESSION_MAX_TTL_SECONDS:
        raise InterfaceRefusedError(
            f"ttl must be 1..{SESSION_MAX_TTL_SECONDS}")
    created = datetime.now(timezone.utc)
    return InterfaceSession(
        session_id=generate_session_id(),
        interface_id=interface_id.strip()[:80],
        node_id=node_id[:80], conversation_id=conversation_id[:80],
        status="active", created_at=created.isoformat(),
        last_seen=created.isoformat(),
        expires_at=(created + timedelta(seconds=ttl)).isoformat())


def touch_session(session: InterfaceSession,
                  now_str: str | None = None) -> InterfaceSession:
    """Refresh presence. Expired or revoked sessions stay that way;
    touching never revives them."""
    if session.status in ("expired", "revoked"):
        return session
    stamp = now_str or now()
    try:
        expired = datetime.fromisoformat(
            session.expires_at) <= datetime.fromisoformat(stamp)
    except (ValueError, TypeError):
        expired = True
    if expired:
        return session.model_copy(update={"status": "expired"})
    return session.model_copy(update={"last_seen": stamp,
                                      "status": "active"})


def revoke_session(session: InterfaceSession) -> InterfaceSession:
    return session.model_copy(update={"status": "revoked"})


def session_usable(session: InterfaceSession,
                   now_str: str | None = None) -> bool:
    """True only for a live, unexpired, unrevoked session."""
    if session.status in ("expired", "revoked"):
        return False
    stamp = now_str or now()
    try:
        if datetime.fromisoformat(session.expires_at) <= \
                datetime.fromisoformat(stamp):
            return False
    except (ValueError, TypeError):
        return False
    return session.status in ("active", "idle")


# -- store (chat DB; queue DB untouched, INVENTory untouched) -----------

def save_session(session: InterfaceSession) -> None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO interface_sessions
        (session_id, interface_id, node_id, conversation_id,
         status, created_at, last_seen, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
        node_id=excluded.node_id,
        conversation_id=excluded.conversation_id,
        status=excluded.status, last_seen=excluded.last_seen,
        expires_at=excluded.expires_at""",
                    (session.session_id, session.interface_id,
                     session.node_id, session.conversation_id,
                     session.status, session.created_at,
                     session.last_seen, session.expires_at))


def load_session(session_id: str) -> InterfaceSession | None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM interface_sessions "
                         "WHERE session_id=?",
                         (session_id,)).fetchone()
    if row is None:
        return None
    return InterfaceSession(**{key: row[key] for key in (
        "session_id", "interface_id", "node_id",
        "conversation_id", "status", "created_at", "last_seen",
        "expires_at")})


def list_sessions(interface_id: str = "",
                  limit: int = 50) -> list[InterfaceSession]:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        if interface_id:
            rows = db.execute(
                """SELECT * FROM interface_sessions
                WHERE interface_id=? ORDER BY last_seen DESC
                LIMIT ?""",
                (interface_id, max(1, min(limit, 100)))).fetchall()
        else:
            rows = db.execute(
                """SELECT * FROM interface_sessions ORDER BY
                last_seen DESC LIMIT ?""",
                (max(1, min(limit, 100)),)).fetchall()
    return [InterfaceSession(**{key: row[key] for key in (
        "session_id", "interface_id", "node_id",
        "conversation_id", "status", "created_at", "last_seen",
        "expires_at")}) for row in rows]


class InterfaceAdapter:
    """Interface contract. Core logic never touches hardware."""

    kind = "base"

    def receive_input(self, raw: dict) -> InterfaceMessage:
        raise NotImplementedError

    def send_response(self, message: InterfaceMessage) -> dict:
        raise NotImplementedError


class TextInterface(InterfaceAdapter):
    """Real text adapter: validates raw turns into envelopes and
    renders answers back to bounded text."""

    kind = "text"

    def __init__(self, interface_id: str = ""):
        self.interface_id = interface_id or generate_interface_id(
            "text")

    def receive_input(self, raw: dict) -> InterfaceMessage:
        if not isinstance(raw, dict):
            raise InterfaceRefusedError("Input must be an object")
        for key in ("message_id", "conversation_id", "content"):
            if not isinstance(raw.get(key), str) \
                    or not raw[key].strip():
                raise InterfaceRefusedError(
                    f"Input needs '{key}' as non-empty text")
        return new_interface_message(
            raw["message_id"].strip()[:80],
            raw["conversation_id"].strip()[:80],
            str(raw.get("role", "user")),
            raw["content"],
            session_id=str(raw.get("session_id", "")),
            interface_id=self.interface_id,
            node_id=str(raw.get("node_id", "")),
            input_type=str(raw.get("input_type", "text")),
            output_type=str(raw.get("output_type", "text")),
            metadata=raw.get("metadata"))

    def send_response(self, message: InterfaceMessage) -> dict:
        if not isinstance(message, InterfaceMessage):
            raise InterfaceRefusedError(
                "Response needs an InterfaceMessage")
        return {"interface_id": self.interface_id,
                "message_id": message.message_id,
                "output_type": message.output_type,
                "content": message.content}


class VoiceInterface(InterfaceAdapter):
    """Voice architecture adapter: STT text in, TTS text out. No
    microphone/speaker coupling — audio lives in voice.py media
    handling, this layer only carries the converged text plus
    voice provenance."""

    kind = "voice"

    def __init__(self, interface_id: str = ""):
        self.interface_id = interface_id or generate_interface_id(
            "voice")

    def receive_input(self, raw: dict) -> InterfaceMessage:
        """Accept transcribed text (never raw audio). Audio
        references travel separately through voice media checks."""
        if not isinstance(raw, dict):
            raise InterfaceRefusedError("Input must be an object")
        text = raw.get("transcript", raw.get("content", ""))
        if not isinstance(text, str) or not text.strip():
            raise InterfaceRefusedError(
                "Voice input needs transcript text")
        if len(text) > MAX_CONTENT_CHARS:
            raise InterfaceRefusedError("Transcript too long")
        return new_interface_message(
            str(raw.get("message_id", "") or
                f"msg-{int(time.time() * 1000):x}"
                f"{secrets.token_hex(4)}")[:80],
            str(raw.get("conversation_id", ""))[:80] or "conv-voice",
            "user", text,
            session_id=str(raw.get("session_id", "")),
            interface_id=self.interface_id,
            node_id=str(raw.get("node_id", "")),
            input_type="voice", output_type="voice",
            provenance=Provenance(
                source_type="user-created",
                creator_id=f"voice:{self.interface_id}",
                human_verified=True,
                notes="spoken turn, transcribed; interpretation "
                      "still pending"),
            metadata={"stt_model": str(raw.get("stt_model", ""))[
                :80]})

    def send_response(self, message: InterfaceMessage) -> dict:
        if not isinstance(message, InterfaceMessage):
            raise InterfaceRefusedError(
                "Response needs an InterfaceMessage")
        return {"interface_id": self.interface_id,
                "message_id": message.message_id,
                "output_type": "voice",
                "content": message.content}
