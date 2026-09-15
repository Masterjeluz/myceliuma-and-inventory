"""Conversation/message model for Mycelium Chat (Fase B).

Small on purpose: a Conversation groups Messages. Roles are
user/assistant/system/agent. Every message carries its provenance and
never carries secrets — there is no field for credentials and content
is length-capped so API keys cannot hide in "just a little more text".

Persistence lives in the coordinator database (tables
``conversations``/``messages``, created additively in database.py).
IDs are caller-visible, deterministic-prefixed (``conv-``/``msg-``)
and unique per row.

Rules (tested):

- role must be one of user/assistant/system/agent; anything else is
  refused before storage.
- content is 1..4000 characters; empty or oversized content is refused.
- provenance defaults to user-created/human or ai-generated/unverified
  depending on role; assistant/agent messages can never claim
  human_verified=True.
- listing is bounded (latest N) and scoped to one conversation.
"""

import secrets
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .inventory_read import Provenance

ConversationRole = Literal["user", "assistant", "system", "agent"]
VALID_ROLES = frozenset({"user", "assistant", "system", "agent"})
MAX_CONTENT_CHARS = 4000
MAX_TITLE_CHARS = 120
LIST_LIMIT = 100


def generate_conversation_id() -> str:
    return f"conv-{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def generate_message_id() -> str:
    return f"msg-{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def default_provenance_for(role: str, creator: str = "chat") -> Provenance:
    if role in ("assistant", "agent"):
        return Provenance(source_type="ai-generated", creator_id=creator,
                          human_verified=False)
    return Provenance(source_type="user-created", creator_id=creator,
                      human_verified=True)


class Conversation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=3, max_length=80)
    title: str = Field(default="", max_length=MAX_TITLE_CHARS)
    project_ref: str = Field(default="", max_length=200)
    created_at: str = ""


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=3, max_length=80)
    conversation_id: str = Field(min_length=3, max_length=80)
    role: str = Field(min_length=1, max_length=20)
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    created_at: str = ""
    provenance: Provenance = Field(default_factory=Provenance)
    sources: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def check_role(cls, role: str) -> str:
        if role not in VALID_ROLES:
            raise ValueError(
                f"Unknown role '{role}'; expected one of "
                "user/assistant/system/agent")
        return role


def new_message(conversation_id: str, role: str, content: str, *,
                message_id: str | None = None,
                provenance: Provenance | None = None,
                sources: list[dict] | None = None) -> Message:
    """Build a validated message. Fail-closed on role/content/provenance."""
    Message.check_role(role)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Message content must be non-empty text")
    if len(content) > MAX_CONTENT_CHARS:
        raise ValueError(
            f"Message exceeds {MAX_CONTENT_CHARS} characters")
    prov = provenance or default_provenance_for(role)
    if role in ("assistant", "agent") and prov.human_verified:
        raise ValueError(
            "Assistant/agent messages must not claim human verification")
    return Message(
        message_id=message_id or generate_message_id(),
        conversation_id=conversation_id,
        role=role,
        content=content.strip(),
        provenance=prov,
        sources=list(sources or [])[:50],
    )
