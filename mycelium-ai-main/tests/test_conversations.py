"""Conversation/message model tests (Fase B/Q).

Roles, content bounds, provenance rules, ID shapes. Storage is
covered through the chat API tests; this file pins the pure model.
"""

import pytest

from coordinator.app.conversations import (
    LIST_LIMIT,
    MAX_CONTENT_CHARS,
    default_provenance_for,
    generate_conversation_id,
    generate_message_id,
    new_message,
)


def test_ids_have_stable_prefixes_and_vary():
    first, second = generate_conversation_id(), generate_conversation_id()
    assert first.startswith("conv-") and second.startswith("conv-")
    assert first != second
    assert generate_message_id().startswith("msg-")


def test_roles_accepted():
    for role in ("user", "assistant", "system", "agent"):
        message = new_message("conv-1", role, "hallo")
        assert message.role == role


def test_unknown_role_refused():
    with pytest.raises(ValueError):
        new_message("conv-1", "godmode", "hallo")


def test_empty_and_oversized_content_refused():
    with pytest.raises(ValueError):
        new_message("conv-1", "user", "   ")
    with pytest.raises(ValueError):
        new_message("conv-1", "user", "x" * (MAX_CONTENT_CHARS + 1))
    assert LIST_LIMIT == 100


def test_assistant_provenance_never_human_verified():
    message = new_message("conv-1", "assistant", "advies")
    assert message.provenance.source_type == "ai-generated"
    assert message.provenance.human_verified is False
    message = new_message("conv-1", "agent", "actie")
    assert message.provenance.human_verified is False


def test_assistant_claiming_verification_refused():
    from coordinator.app.inventory_read import Provenance
    claimed = Provenance(source_type="ai-generated", creator_id="m",
                         human_verified=True)
    with pytest.raises(ValueError):
        new_message("conv-1", "assistant", "advies", provenance=claimed)


def test_user_provenance_is_human():
    message = new_message("conv-1", "user", "vraag")
    assert message.provenance.human_verified is True


def test_default_provenance_per_role():
    assert default_provenance_for("assistant").human_verified is False
    assert default_provenance_for("user").human_verified is True


def test_no_secrets_field_on_message():
    message = new_message("conv-1", "user", "x")
    assert "secret" not in message.model_dump()
    assert "credential" not in message.model_dump()
    assert "token" not in message.model_dump()
