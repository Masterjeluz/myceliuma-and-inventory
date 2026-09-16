"""FASE 1 tests (BIG #16): SQLite concurrency foundation.

WAL + busy_timeout must let concurrent local writers
serialize instead of failing with "database is locked".
Threads share nothing except the database files; every
thread opens its own short-lived connection.
"""

import sqlite3
import threading

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.database import BUSY_TIMEOUT_MS, connection
from coordinator.app.inventory_read import Provenance


def setup_dbs(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "conc.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "conc-chat.db"))


def pragmas(path):
    db = sqlite3.connect(str(path))
    try:
        journal = db.execute(
            "PRAGMA journal_mode").fetchone()[0]
        timeout = db.execute(
            "PRAGMA busy_timeout").fetchone()[0]
    finally:
        db.close()
    return journal.lower(), timeout


def test_connection_uses_wal_and_busy_timeout(tmp_path,
                                              monkeypatch):
    setup_dbs(tmp_path, monkeypatch)
    from coordinator.app.database import (
        _open_db, chat_database_path)
    from coordinator.app.database import database_path
    db = _open_db(database_path())
    try:
        assert db.execute(
            "PRAGMA journal_mode").fetchone()[0] == "wal"
        assert db.execute(
            "PRAGMA busy_timeout").fetchone()[0] == \
            BUSY_TIMEOUT_MS
    finally:
        db.close()
    chat = _open_db(chat_database_path())
    try:
        assert chat.execute(
            "PRAGMA journal_mode").fetchone()[0] == "wal"
        assert chat.execute(
            "PRAGMA busy_timeout").fetchone()[0] == \
            BUSY_TIMEOUT_MS
    finally:
        chat.close()
    # WAL persists on the file itself (visible to any reader).
    journal, _ = pragmas(tmp_path / "conc.db")
    assert journal == "wal"


def test_concurrent_claim_single_winner(tmp_path, monkeypatch):
    setup_dbs(tmp_path, monkeypatch)
    with TestClient(main_mod.app) as client:
        for node_id in ("conc-a", "conc-b"):
            assert client.post("/api/v1/nodes/register", json={
                "node_id": node_id, "hostname": "h",
                "capabilities": [
                    "exec:system_inventory"],
                "node_token": f"conc-token-{node_id}-123"}
            ).status_code == 201
        task = client.post("/api/v1/tasks", json={
            "kind": "system_inventory",
            "required_capabilities": [
                "exec:system_inventory"]}).json()
    barrier = threading.Barrier(2)
    results = {}
    errors = []

    def claim(node_id):
        try:
            barrier.wait(timeout=10)
            results[node_id] = main_mod._claim_task(
                node_id, main_mod.now(),
                node_token=f"conc-token-{node_id}-123")
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=claim, args=(node_id,))
               for node_id in ("conc-a", "conc-b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, errors
    winners = [node_id for node_id, claimed in results.items()
               if claimed is not None]
    assert len(winners) == 1
    assert winners[0] in ("conc-a", "conc-b")
    with connection() as db:
        row = db.execute("SELECT status, assigned_node_id FROM "
                         "tasks WHERE id=?", (task["id"],)).fetchone()
    assert row["status"] == "assigned"
    assert row["assigned_node_id"] == winners[0]


def test_concurrent_event_writes_no_lock(tmp_path, monkeypatch):
    setup_dbs(tmp_path, monkeypatch)
    barrier = threading.Barrier(8)
    errors = []

    def write(index):
        try:
            barrier.wait(timeout=10)
            main_mod.emit_event("conc.write", f"event {index}")
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=write, args=(index,))
               for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, errors


def test_concurrent_sync_apply_converges(tmp_path, monkeypatch):
    setup_dbs(tmp_path, monkeypatch)
    from coordinator.app.diststate import (
        DistEnvelope, apply_envelope)
    envelope = DistEnvelope(
        event_id="dsevt_conc1", origin_node_id="conc-a",
        entity_id="obj_1", entity_type="object",
        entity_revision="rev-1", base_revision="",
        event_type="entity.observed", timestamp="",
        payload={"note": "x"},
        provenance=Provenance(source_type="sensor-observed",
                              creator_id="conc",
                              human_verified=False),
        epoch=0)
    barrier = threading.Barrier(4)
    outcomes = []
    errors = []

    def apply():
        try:
            barrier.wait(timeout=10)
            outcomes.append(apply_envelope(envelope)["status"])
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=apply) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, errors
    assert sorted(outcomes).count("applied") == 1
    assert sorted(outcomes).count("duplicate") == 3


def test_concurrent_memory_writes_no_lock(tmp_path, monkeypatch):
    setup_dbs(tmp_path, monkeypatch)
    from coordinator.app.memory import (
        new_memory, save_memory)
    barrier = threading.Barrier(6)
    errors = []

    def write(index):
        try:
            barrier.wait(timeout=10)
            save_memory(new_memory(
                "fact", f"concurrent fact {index}",
                truth="user_fact",
                provenance=Provenance(
                    source_type="user-created",
                    creator_id="conc", human_verified=True,
                    verified_by="conc")))
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=write, args=(index,))
               for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, errors
    from coordinator.app.memory import list_memories
    assert len(list_memories(memory_type="fact",
                             limit=200)) == 6
