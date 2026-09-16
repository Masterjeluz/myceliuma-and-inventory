"""Voice approval safety for Mycelium (BIG #9).

Spoken words are never authorization by themselves. A voice
approval resolves ONLY when ALL of these hold:

- exactly one active approval request exists (zero or several
  competing requests refuse — ambiguity never approves);
- the request has not expired;
- the transcript matches the small allowed response set
  (exact words, documented below — casual conversation never
  matches by accident because binding comes first);
- the target still exists in its pending state with an
  unchanged fingerprint/binding (rechecked live, never cached);
- the kind is not physical: voice can never satisfy
  approval for physical execution (printer.execute,
  robot.execute, drone.mission); those stay on their
  existing explicit channels. Desktop input counts as
  interface approval (option A): a spoken YES may resolve
  a pending desktop action through this same flow, but
  never a physical one.

On success this layer returns the canonical "YES" for the
caller to feed into the EXISTING decide path (decide_write /
approve_mission / agent decide). No second approval framework:
binding, staleness and fingerprint rules are reused, not
reinvented.
"""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

#: Exact spoken responses accepted (after strip + one trailing
#: period). Small on purpose: anything else refuses.
VOICE_YES_WORDS = frozenset({"YES", "yes", "Yes", "JA", "ja", "Ja"})
VOICE_NO_WORDS = frozenset({"NO", "no", "No", "NEE", "nee", "Nee"})

#: Kinds that voice may resolve. "physical" is deliberately
#: absent: voice never satisfies physical approval.
VOICE_APPROVABLE_KINDS = frozenset({"write", "mission", "desktop"})


class VoiceApprovalRefusedError(ValueError):
    """Voice approval refused; nothing was decided.

    ``retryable`` is True only for a non-matching transcript
    (the operator may speak again); structural refusals
    (expired, competing, target-changed, physical) retire the
    request.
    """

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class VoiceApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=3, max_length=80)
    kind: str = Field(min_length=1, max_length=20)
    target_id: str = Field(min_length=1, max_length=80)
    fingerprint: str = Field(default="", max_length=64)
    summary: str = Field(default="", max_length=500)
    created_at: str = ""
    expires_at: str = ""
    status: str = Field(default="pending", max_length=20)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def normalize_transcript(transcript) -> str:
    """Normalize spoken text for matching. Returns '' when the
    transcript cannot resolve to a decision word."""
    if not isinstance(transcript, str):
        return ""
    return transcript.strip().rstrip(".").strip()


def resolve_voice_approval(active: list,
                           transcript: str, *,
                           kind: str,
                           target_ok: bool,
                           now_str: str | None = None) -> dict:
    """Resolve one spoken answer against the active requests.

    ``active``: pending VoiceApprovalRequests for this session.
    ``kind``/``target_ok``: caller-verified — kind in the
    approvable set and the target still pending with unchanged
    binding. Returns {"approved": bool, "response": "YES"/"NO",
    "reason": str}. Refusals raise VoiceApprovalRefusedError.
    """
    if kind == "physical" or kind not in VOICE_APPROVABLE_KINDS:
        raise VoiceApprovalRefusedError(
            f"kind '{kind}' never resolves by voice; physical "
            "approval stays on its explicit channel")
    pending = [request for request in (active or [])
               if getattr(request, "status", "") == "pending"]
    if not pending:
        raise VoiceApprovalRefusedError(
            "no active approval request; spoken words decide "
            "nothing")
    if len(pending) > 1:
        raise VoiceApprovalRefusedError(
            "competing approval requests; ambiguity never approves")
    request = pending[0]
    stamp = now_str or now()
    try:
        expired = _parse_time(request.expires_at) <= _parse_time(
            stamp)
    except (ValueError, TypeError):
        expired = True
    if expired:
        raise VoiceApprovalRefusedError(
            "approval request expired; re-request explicitly")
    if not target_ok:
        raise VoiceApprovalRefusedError(
            "target changed or left pending state; refusing")
    word = normalize_transcript(transcript)
    if word in VOICE_YES_WORDS:
        return {"approved": True, "response": "YES",
                "approval_id": request.approval_id,
                "reason": "exactly one active request, unexpired, "
                          "binding intact, explicit YES word"}
    if word in VOICE_NO_WORDS:
        return {"approved": False, "response": "NO",
                "approval_id": request.approval_id,
                "reason": "explicit NO word"}
    raise VoiceApprovalRefusedError(
        "spoken response matches no allowed approval word; "
        "refusing", retryable=True)


# -- store (chat DB; queue DB untouched, INVENTory untouched) -----------

def save_voice_request(request: VoiceApprovalRequest) -> None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO voice_approvals
        (approval_id, kind, target_id, fingerprint, summary,
         status, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(approval_id) DO UPDATE SET status=excluded.status""",
                    (request.approval_id, request.kind,
                     request.target_id, request.fingerprint,
                     request.summary, request.status,
                     request.created_at, request.expires_at))


def load_voice_request(approval_id: str,
                       ) -> VoiceApprovalRequest | None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM voice_approvals "
                         "WHERE approval_id=?",
                         (approval_id,)).fetchone()
    if row is None:
        return None
    return VoiceApprovalRequest(**{key: row[key] for key in (
        "approval_id", "kind", "target_id", "fingerprint",
        "summary", "status", "created_at", "expires_at")})


def pending_voice_requests() -> list[VoiceApprovalRequest]:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute(
            "SELECT * FROM voice_approvals WHERE status='pending' "
            "ORDER BY created_at ASC").fetchall()
    return [VoiceApprovalRequest(**{key: row[key] for key in (
        "approval_id", "kind", "target_id", "fingerprint",
        "summary", "status", "created_at", "expires_at")})
        for row in rows]


def mark_voice_resolved(approval_id: str, status: str) -> None:
    if status not in ("resolved", "expired", "rejected"):
        raise VoiceApprovalRefusedError(
            f"Unknown voice status '{status}'")
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("UPDATE voice_approvals SET status=? WHERE "
                   "approval_id=?", (status, approval_id))
