"""Coordinator election, lease and fencing (BIG #10, deel 2).

One coordinator at a time, without Raft/Kubernetes. Model:

- nodes carry ``coordinator_capable`` (operator-set, default
  off) in the queue DB nodes table (additive column);
- a single durable lease lives in the chat DB table
  ``coordinator_lease`` (the queue DB table SET is frozen by
  an existing pinning test, so election meta lives next to
  missions/agent context — documented, not hidden);
- election is deterministic: among fresh, enabled,
  coordinator-capable nodes the lowest node_id wins;
- a lease (epoch, holder, fencing token, expiry) must be held
  to coordinate; writes without the current epoch refuse;
- quorum = majority of fresh coordinator-capable nodes; a
  lone capable node elects itself explicitly in ``degraded``
  mode; without quorum the cluster refuses automatic
  election (manual recovery: wait, re-register, or
  operator-enable a node).

Guarantees this version GIVES:

- at most one holder per epoch (atomic conditional update on
  the single lease row; SQLite serializes writers);
- epochs strictly increase; fencing tokens are fresh random
  per epoch and never reused;
- an old coordinator's writes refuse via epoch mismatch
  (assignment records the epoch; claim rechecks it);
- a returning ex-primary synchronizes by reading (pull-only)
  and must campaign for a NEW epoch before coordinating.

Guarantees this version does NOT give:

- clock-synchronization safety (leases assume roughly sane
  local clocks; skew beyond the lease window can confuse
  expiry — documented, same trust domain as heartbeats);
- Byzantine tolerance, encrypted transport, or cross-network
  operation (loopback/LAN trust model unchanged);
- automatic split-brain healing across partitions (a
  partition without quorum degrades instead of electing).

Terms follow the existing lease vocabulary (M7.4): lease,
expiry, attempt-free single row, conditional update races.
"""

import secrets
from datetime import datetime, timedelta, timezone

COORDINATOR_LEASE_SECONDS = 60
STALE_SECONDS = 60


class ElectionRefusedError(ValueError):
    """Election or renewal refused; no state changed."""


class FencingError(ValueError):
    """Epoch/fencing mismatch. The writer is not the authority."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _fresh(last_seen: str, current: datetime) -> bool:
    try:
        seen = _parse_time(last_seen)
        return (current - seen) <= timedelta(seconds=STALE_SECONDS)
    except (ValueError, TypeError):
        return False


def read_lease() -> dict | None:
    """Current lease row or None. Read-only."""
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute(
            "SELECT * FROM coordinator_lease WHERE id=1").fetchone()
    return dict(row) if row is not None else None


def current_epoch(now_str: str | None = None) -> int:
    """Valid lease epoch, else 0 (no coordinator elected yet).
    Epoch 0 preserves all pre-failover behavior unchanged."""
    lease = read_lease()
    if lease is None:
        return 0
    try:
        current = _parse_time(now_str) if now_str else \
            datetime.now(timezone.utc)
        if _parse_time(lease["expires_at"]) <= current:
            return 0
    except (ValueError, TypeError, KeyError):
        return 0
    try:
        return max(0, int(lease.get("epoch", 0)))
    except (TypeError, ValueError):
        return 0


def require_epoch(epoch, now_str: str | None = None) -> int:
    """Fencing gate: the presented epoch must equal the live
    lease epoch. Raises FencingError otherwise (stale writer)."""
    try:
        presented = int(epoch)
    except (TypeError, ValueError):
        raise FencingError("epoch must be an integer")
    live = current_epoch(now_str)
    if presented != live:
        raise FencingError(
            f"epoch {presented} is not the live epoch {live}; "
            "stale coordinators cannot write")
    return live


def require_writer_epoch(presented_epoch=None,
                         now_str: str | None = None) -> int:
    """Central fencing gate for coordinator-owned mutations.

    Invariant: a writer holding an old fencing epoch cannot
    perform coordinator-owned mutations. No lease row yet
    means no election ever ran: live epoch is 0 and epoch-0
    writers pass (single-coordinator bootstrap preserved).
    Once an election ran, only the live epoch passes.

    Call sites present the epoch they act under (sync
    envelopes, stamped task routings). Local same-process
    writes present the current epoch. Fencing is authority
    protection only — never approval, never verification,
    never a human_verified bypass.
    """
    if presented_epoch is None:
        presented_epoch = current_epoch(now_str)
    return require_epoch(presented_epoch, now_str)


def _capable_set(nodes: list) -> list[dict]:
    """All enabled coordinator-capable nodes, fresh or not."""
    capable = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        if not node.get("coordinator_capable"):
            continue
        if str(node.get("status", "")) == "disabled":
            continue
        capable.append(node)
    capable.sort(key=lambda entry: str(entry.get("node_id", "")))
    return capable


def _eligible_voters(nodes: list) -> list[dict]:
    """Fresh subset of the capable set, sorted by node_id."""
    current = datetime.now(timezone.utc)
    return [entry for entry in _capable_set(nodes)
            if _fresh(str(entry.get("last_seen", "")), current)]


def campaign(node_id: str, get_nodes,
             now_str: str | None = None) -> dict:
    """Seek or renew the coordinator lease. Deterministic:
    the lowest fresh eligible node_id wins; quorum is a
    majority of fresh eligible voters; a lone voter wins in
    explicitly degraded mode."""
    from .database import chat_connection, init_chat_database
    if not isinstance(node_id, str) or not node_id.strip():
        raise ElectionRefusedError("campaign needs a node_id")
    node_id = node_id.strip()
    current = _parse_time(now_str) if now_str else \
        datetime.now(timezone.utc)
    try:
        source = get_nodes() if callable(get_nodes) else get_nodes
        nodes = list(source or [])
    except TypeError:
        nodes = []
    voters = _eligible_voters(nodes)
    mine = next((entry for entry in voters
                 if str(entry.get("node_id", "")) == node_id), None)
    if mine is None:
        raise ElectionRefusedError(
            f"node '{node_id}' is not an eligible voter "
            "(register, coordinator_capable, fresh, enabled)")
    winner = str(voters[0].get("node_id", ""))
    if winner != node_id:
        raise ElectionRefusedError(
            f"deterministic order elects '{winner}', not "
            f"'{node_id}'")
    init_chat_database()
    with chat_connection() as db:
        # Atomic takeover: BEGIN IMMEDIATE takes the write
        # lock first, then every write is conditional on the
        # exact row just read. A concurrent campaigner that
        # read the same row finds zero rows changed and loses
        # loudly instead of silently co-owning the epoch.
        # Invariant: two simultaneous campaigners can never
        # both become valid holders of the same epoch.
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM coordinator_lease WHERE id=1").fetchone()
        live_holder = None
        live_epoch = 0
        if row is not None:
            try:
                live_epoch = int(row["epoch"])
            except (TypeError, ValueError, KeyError):
                live_epoch = 0
            try:
                valid = _parse_time(row["expires_at"]) > current
            except (ValueError, TypeError, KeyError):
                valid = False
            if valid:
                live_holder = row["holder_node_id"]
        if live_holder is not None and live_holder != node_id:
            raise ElectionRefusedError(
                f"lease held by '{live_holder}' until "
                f"{row['expires_at']}; wait for expiry")
        if live_holder == node_id:
            changed = db.execute(
                "UPDATE coordinator_lease SET expires_at=? "
                "WHERE id=1 AND holder_node_id=? AND epoch=?",
                ((current + timedelta(
                    seconds=COORDINATOR_LEASE_SECONDS)).isoformat(),
                 node_id, live_epoch)).rowcount
            if not changed:
                raise ElectionRefusedError(
                    "lease moved during renewal; re-campaign")
            return {"node_id": node_id, "epoch": live_epoch,
                    "fencing_token": row["fencing_token"],
                    "mode": "renewed",
                    "expires_at": (current + timedelta(
                        seconds=COORDINATOR_LEASE_SECONDS)
                    ).isoformat()}
        total = len(_capable_set(nodes))
        quorum = total // 2 + 1
        if len(voters) < quorum:
            raise ElectionRefusedError(
                f"no quorum ({len(voters)} fresh of {total} "
                f"capable, need {quorum}); cluster degrades, "
                "manual recovery required")
        mode = "degraded" if total == 1 else "quorum"
        epoch = live_epoch + 1 if row is not None else 1
        fencing = secrets.token_hex(16)
        expires = (current + timedelta(
            seconds=COORDINATOR_LEASE_SECONDS)).isoformat()
        if row is None:
            # First lease ever. A concurrent campaigner may
            # insert between our read and write; ON CONFLICT
            # DO NOTHING plus rowcount detects the lost race
            # without exception parsing.
            changed = db.execute("""INSERT INTO coordinator_lease
                (id, epoch, holder_node_id, fencing_token,
                 expires_at, updated_at)
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING""",
                                   (epoch, node_id, fencing,
                                    expires,
                                    current.isoformat())).rowcount
            if not changed:
                raise ElectionRefusedError(
                    "a concurrent campaigner took the lease; "
                    "re-campaign")
        else:
            changed = db.execute(
                """UPDATE coordinator_lease SET epoch=?,
                holder_node_id=?, fencing_token=?, expires_at=?,
                updated_at=? WHERE id=1 AND epoch=? AND
                ifnull(holder_node_id, '')=ifnull(?, '') AND
                ifnull(expires_at, '')=ifnull(?, '')""",
                (epoch, node_id, fencing, expires,
                 current.isoformat(), live_epoch,
                 row["holder_node_id"], row["expires_at"])).rowcount
            if not changed:
                raise ElectionRefusedError(
                    "a concurrent campaigner took the lease; "
                    "re-campaign")
    return {"node_id": node_id, "epoch": epoch,
            "fencing_token": fencing, "mode": mode,
            "expires_at": expires}


def release(node_id: str) -> bool:
    """Explicit step-down. Returns True when a lease was held."""
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute(
            "SELECT holder_node_id FROM coordinator_lease "
            "WHERE id=1").fetchone()
        if row is None or row["holder_node_id"] != node_id:
            return False
        db.execute("UPDATE coordinator_lease SET expires_at=? "
                   "WHERE id=1", ("2000-01-01T00:00:00+00:00",))
    return True


def sync_status(nodes: list) -> dict:
    """Coordinator + election snapshot for status surfaces."""
    lease = read_lease()
    voters = _eligible_voters(list(nodes or []))
    epoch = current_epoch()
    return {
        "epoch": epoch,
        "holder": (lease["holder_node_id"]
                   if lease and epoch else None),
        "expires_at": (lease["expires_at"]
                       if lease and epoch else None),
        "eligible_voters": [str(entry.get("node_id", ""))
                            for entry in voters],
        "mode": ("degraded" if epoch and len(voters) <= 1
                 else ("quorum" if epoch else "none")),
    }
