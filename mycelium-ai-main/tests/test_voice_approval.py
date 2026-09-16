"""Voice approval safety tests (BIG #9).

Spoken words decide nothing by themselves: exactly one active
request, unexpired, target still pending with intact binding,
allowed word — and physical kinds never resolve by voice.
"""

import pytest

from coordinator.app.voice_approval import (
    VOICE_APPROVABLE_KINDS,
    VoiceApprovalRefusedError,
    VoiceApprovalRequest,
    load_voice_request,
    mark_voice_resolved,
    normalize_transcript,
    pending_voice_requests,
    resolve_voice_approval,
    save_voice_request,
)


def make_request(**overrides):
    record = {
        "approval_id": "vapr-1", "kind": "write",
        "target_id": "wrt-1", "fingerprint": "ab" * 32,
        "summary": "test", "created_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2026-01-02T00:00:00+00:00",
        "status": "pending",
    }
    record.update(overrides)
    return VoiceApprovalRequest(**record)


def test_exact_yes_word_approves():
    outcome = resolve_voice_approval(
        [make_request()], "YES", kind="write", target_ok=True,
        now_str="2026-01-01T12:00:00+00:00")
    assert outcome == {"approved": True, "response": "YES",
                       "approval_id": "vapr-1",
                       "reason": outcome["reason"]}
    outcome = resolve_voice_approval(
        [make_request()], "ja.", kind="mission", target_ok=True,
        now_str="2026-01-01T12:00:00+00:00")
    assert outcome["approved"] is True
    outcome = resolve_voice_approval(
        [make_request()], "nee", kind="desktop", target_ok=True,
        now_str="2026-01-01T12:00:00+00:00")
    assert outcome == {"approved": False, "response": "NO",
                       "approval_id": "vapr-1",
                       "reason": outcome["reason"]}


def test_casual_speech_never_approves():
    for transcript in ("doe maar", "oke", "ja toch?", "YES PLEASE",
                       "yep", "", "   ", "YES YES"):
        with pytest.raises(VoiceApprovalRefusedError):
            resolve_voice_approval(
                [make_request()], transcript, kind="write",
                target_ok=True,
                now_str="2026-01-01T12:00:00+00:00")


def test_no_competing_or_missing_requests():
    with pytest.raises(VoiceApprovalRefusedError,
                       match="no active"):
        resolve_voice_approval([], "YES", kind="write",
                               target_ok=True)
    with pytest.raises(VoiceApprovalRefusedError,
                       match="competing"):
        resolve_voice_approval(
            [make_request(), make_request(approval_id="vapr-2")],
            "YES", kind="write", target_ok=True)


def test_expiry_and_target_binding():
    with pytest.raises(VoiceApprovalRefusedError, match="expired"):
        resolve_voice_approval(
            [make_request()], "YES", kind="write", target_ok=True,
            now_str="2026-02-01T00:00:00+00:00")
    with pytest.raises(VoiceApprovalRefusedError,
                       match="target changed"):
        resolve_voice_approval(
            [make_request()], "YES", kind="write",
            target_ok=False,
            now_str="2026-01-01T12:00:00+00:00")


def test_physical_never_by_voice():
    assert "physical" not in VOICE_APPROVABLE_KINDS
    for kind in ("physical", "printer", "shell", ""):
        with pytest.raises(VoiceApprovalRefusedError):
            resolve_voice_approval(
                [make_request(kind="write")], "YES", kind=kind,
                target_ok=True,
                now_str="2026-01-01T12:00:00+00:00")


def test_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "vapr.db"))
    assert pending_voice_requests() == []
    assert load_voice_request("vapr-missing") is None
    save_voice_request(make_request())
    assert len(pending_voice_requests()) == 1
    assert load_voice_request("vapr-1").target_id == "wrt-1"
    mark_voice_resolved("vapr-1", "resolved")
    assert pending_voice_requests() == []
    assert load_voice_request("vapr-1").status == "resolved"
    with pytest.raises(VoiceApprovalRefusedError):
        mark_voice_resolved("vapr-1", "shipped")


def test_normalize():
    assert normalize_transcript("  YES. ") == "YES"
    assert normalize_transcript(None) == ""
    assert normalize_transcript(42) == ""
