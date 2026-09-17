"""Conversation import routes (BIG #30): real pipeline, no stub.

POST /api/v1/conversations/import parses pasted text / TXT /
Markdown / JSON / safe HTML and persists a conv_... conversation
with imported provenance. Analysis stays OBSERVATION/CANDIDATE.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter()


class ConversationImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1, max_length=200000)
    format: str = Field(default="plain", max_length=20)
    source_platform: str = Field(default="other", max_length=40)


@router.post("/api/v1/conversations/import")
def import_conversation(data: ConversationImport):
    from .conversation_bridge import BridgeRefusedError, import_conversation
    try:
        return import_conversation(
            data.title, data.content, data.format,
            data.source_platform)
    except BridgeRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
