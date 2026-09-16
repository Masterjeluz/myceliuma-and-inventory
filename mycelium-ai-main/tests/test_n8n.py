"""BIG #17 tests: n8n integration plane.

Auth, envelope validation, idempotency, scheduler trigger,
outbox, Garmin readiness, and every safety negative:
no approve, no physical execution, no human_verified
escalation, no secrets crossing, no DB access for n8n.
"""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

OPERATOR_KEY = "op-key-n8n-tests-123"


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "n8n.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "n8n-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", OPERATOR_KEY)
    with TestClient(main_mod.app) as test_client:
        yield test_client


def issue_key(client, integration_id="generic",
              capabilities=None):
    body = {"operator_key": OPERATOR_KEY}
    if capabilities is not None:
        body["capabilities"] = capabilities
    response = client.post(
        f"/api/v1/integrations/{integration_id}/keys",
        json=body)
    assert response.status_code == 201, response.text
    return response.json()["key"]


def envelope(**overrides):
    body = {
        "integration_id": "generic",
        "source": "generic",
        "external_event_id": "evt-1",
        "event_type": "memory.observation",
        "occurred_at": "2026-09-17T08:00:00+00:00",
        "payload": {"title": "n8n note",
                    "content": "imported observation"},
        "provenance": {"source_type": "external-source",
                       "creator_id": "n8n:generic",
                       "human_verified": False},
        "schema_version": "1",
        "idempotency_key": "key-1",
    }
    body.update(overrides)
    return body


def post_event(client, body, key="MISSING"):
    headers = {}
    if key != "MISSING":
        headers["X-Integration-Key"] = key
    return client.post("/api/v1/integrations/events",
                       json=body, headers=headers)


def test_key_issuance_needs_operator(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert client.post(
            "/api/v1/integrations/generic/keys",
            json={}).status_code == 403
        assert client.post(
            "/api/v1/integrations/generic/keys",
            json={"operator_key": "wrong"}).status_code == 403
        assert client.post(
            "/api/v1/integrations/nope/keys",
            json={"operator_key": OPERATOR_KEY}
        ).status_code == 422
        issued = client.post(
            "/api/v1/integrations/generic/keys",
            json={"operator_key": OPERATOR_KEY}).json()
        assert len(issued["key"]) == 64
        assert "key_hash" not in str(issued)
        # Rotation replaces the old key.
        rotated = client.post(
            "/api/v1/integrations/generic/keys",
            json={"operator_key": OPERATOR_KEY}).json()
        assert rotated["key"] != issued["key"]
        assert post_event(client, envelope(),
                          key=issued["key"]).status_code == 403
        assert post_event(client, envelope(),
                          key=rotated["key"]
                          ).status_code == 201


def test_auth_and_capability_gates(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert post_event(client, envelope()).status_code == 401
        assert post_event(
            client, envelope(), key="wrong").status_code == 403
        ingest_only = issue_key(
            client, "garmin", ["integration:ingest"])
        # Ingest-only key cannot trigger jobs.
        assert client.post(
            "/api/v1/integrations/trigger",
            json={"integration_id": "garmin",
                  "job_name": "watcher_scan"},
            headers={"X-Integration-Key": ingest_only}
        ).status_code == 403
        # Unknown integration refused.
        assert post_event(
            client, envelope(integration_id="nope"),
            key=ingest_only).status_code in (403, 422)


def test_envelope_validation_negatives(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        key = issue_key(client)
        cases = [
            # executable payload
            {"payload": {"command": "rm -rf /"}},
            {"payload": {"outer": {"exec": "x"}}},
            # secret-shaped payload never crosses
            {"payload": {"refresh_token": "abc"}},
            {"payload": {"api_key": "abc"}},
            # deeply nested
            {"payload": {"a": {"b": {"c": {"d": {"e": {
                "f": {"g": 1}}}}}}}},
            # oversized value
            {"payload": {"title": "t",
                         "content": "x" * 501}},
            # source spoofing
            {"source": "garmin"},
            # wrong event type for the integration
            {"event_type": "robot.execute"},
            {"event_type": "approval.grant"},
            # provenance escalation
            {"provenance": {
                "source_type": "external-source",
                "creator_id": "n8n:generic",
                "human_verified": True}},
            {"provenance": {
                "source_type": "user-created",
                "creator_id": "n8n:generic",
                "human_verified": False}},
            {"provenance": {
                "source_type": "external-source",
                "creator_id": "someone-else",
                "human_verified": False}},
            # bad schema / time
            {"schema_version": "99"},
            {"occurred_at": "not-a-time"},
        ]
        for index, override in enumerate(cases):
            body = envelope(
                **override,
                idempotency_key=f"neg-{index}")
            assert post_event(client, body,
                              key=key).status_code == 422, override
        # Missing idempotency is a schema 422.
        body = envelope()
        del body["idempotency_key"]
        assert post_event(client, body,
                          key=key).status_code == 422


def test_idempotency_duplicate_and_conflict(tmp_path,
                                            monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        key = issue_key(client)
        first = post_event(client, envelope(), key=key).json()
        assert first["outcome"] == "accepted"
        again = post_event(client, envelope(), key=key).json()
        assert again["outcome"] == "duplicate"
        changed = envelope(payload={"title": "n8n note",
                                    "content": "CHANGED"})
        conflict = post_event(client, changed, key=key).json()
        assert conflict["outcome"] == "conflict"
        # Nothing was silently overwritten: the accepted
        # memory still holds the original content.
        memories = client.post("/api/v1/memory/retrieve",
                               json={"query": "n8n note",
                                     "memory_types": [
                                         "observation"]}
                               ).json()["results"]
        assert len(memories) == 1
        stored = client.get(
            f"/api/v1/memory/{memories[0]['memory_id']}").json()
        assert stored["content"] == "imported observation"
        # Ledger shows the full history.
        ledger = client.get(
            "/api/v1/integrations/events",
            params={"integration_id": "generic"},
            headers={"X-Integration-Key": key}).json()
        assert {item["status"] for item in ledger} == {
            "received", "accepted", "duplicate", "conflict"}


def test_ledger_needs_auth(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert client.get(
            "/api/v1/integrations/events").status_code == 403
        assert client.get(
            "/api/v1/integrations/events",
            params={"integration_id": "generic"},
            headers={"X-Integration-Key": "wrong"}
        ).status_code == 403


def test_scheduler_trigger_known_jobs_only(tmp_path,
                                           monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        key = issue_key(client, "generic",
                        ["integration:trigger"])
        assert client.post(
            "/api/v1/integrations/trigger",
            json={"integration_id": "generic"},
            headers={"X-Integration-Key": key}
        ).status_code == 422
        assert client.post(
            "/api/v1/integrations/trigger",
            json={"integration_id": "generic",
                  "job_name": "run_anything",
                  "params": {"code": "x"}},
            headers={"X-Integration-Key": key}
        ).status_code == 422
        ran = client.post(
            "/api/v1/integrations/trigger",
            json={"integration_id": "generic",
                  "job_name": "watcher_scan",
                  "run_key": "n8n-sched-1"},
            headers={"X-Integration-Key": key}).json()
        assert ran["status"] == "completed"
        assert ran["summary"]["tasks_scanned"] >= 0
        # Idempotent under the same run key.
        again = client.post(
            "/api/v1/integrations/trigger",
            json={"integration_id": "generic",
                  "job_name": "watcher_scan",
                  "run_key": "n8n-sched-1"},
            headers={"X-Integration-Key": key}).json()
        assert again["run_id"] == ran["run_id"]


def test_outbox_poll_model(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert client.post("/api/v1/integrations/outbox", json={
            "target_label": "notify",
            "payload": {"text": "hello"}}).status_code == 403
        # Non-allow-listed targets (URLs!) refuse.
        assert client.post("/api/v1/integrations/outbox", json={
            "target_label": "https://evil.example/hook",
            "payload": {"text": "x"},
            "operator_key": OPERATOR_KEY}).status_code == 422
        queued = client.post("/api/v1/integrations/outbox",
                             json={
                                 "target_label": "notify",
                                 "payload": {"text": "hello"},
                                 "operator_key": OPERATOR_KEY}).json()
        assert queued["status"] == "pending"
        key = issue_key(client, "generic",
                        ["integration:trigger"])
        pending = client.get("/api/v1/integrations/outbox",
                             params={"status": "pending",
                                     "integration_id": "generic"},
                             headers={"X-Integration-Key": key}
                             ).json()
        assert [item["outbox_id"] for item in pending] == [
            queued["outbox_id"]]
        acked = client.post(
            f"/api/v1/integrations/outbox/"
            f"{queued['outbox_id']}/ack",
            json={"integration_id": "generic"},
            headers={"X-Integration-Key": key}).json()
        assert acked["status"] == "acked"
        assert acked["acked_by"] == "generic"
        # Double-ack is idempotent.
        assert client.post(
            f"/api/v1/integrations/outbox/"
            f"{queued['outbox_id']}/ack",
            json={"integration_id": "generic"},
            headers={"X-Integration-Key": key}).json()[
                "status"] == "acked"
        assert client.get("/api/v1/integrations/outbox",
                          params={"status": "pending",
                                  "integration_id": "generic"},
                          headers={"X-Integration-Key": key}
                          ).json() == []


def test_garmin_mock_ingest_and_readiness(tmp_path,
                                          monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        readiness = client.get(
            "/api/v1/integrations/garmin/readiness").json()
        assert readiness["state"] == "UNAVAILABLE"
        assert readiness["mock"] is True
        assert any("OAuth" in item or "official" in item
                   for item in readiness["requirements"])
        key = issue_key(client, "garmin")
        result = post_event(client, {
            "integration_id": "garmin",
            "source": "garmin",
            "external_event_id": "grm-1",
            "event_type": "health.measurements",
            "occurred_at": "2026-09-17T07:00:00+00:00",
            "payload": {"measurements": [
                {"metric": "steps", "value": 5000,
                 "observed_at": "2026-09-17T07:00:00+00:00"}]},
            "provenance": {"source_type": "external-source",
                           "creator_id": "n8n:garmin",
                           "human_verified": False},
            "schema_version": "1",
            "idempotency_key": "grm-key-1",
        }, key=key).json()
        assert result["outcome"] == "accepted"
        assert result["record"]["applied"] == {"imported": 1,
                                              "duplicates": 0}
        rows = client.get("/api/v1/health/measurements",
                          params={"metric": "steps",
                                  "source": "wearable"}).json()
        assert len(rows) == 1
        assert rows[0]["provenance"]["creator_id"] == \
            "n8n:garmin"
        assert "MOCK" in rows[0]["provenance"]["notes"]
        assert rows[0]["origin"] == "n8n:garmin"


def test_no_secrets_reach_storage(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        from coordinator.app.database import (
            chat_connection, init_chat_database)
        key = issue_key(client)
        assert post_event(client, envelope(
            payload={"note": "x", "refresh_token": "sekret"},
            idempotency_key="sec-1"), key=key).status_code == 422
        init_chat_database()
        with chat_connection() as db:
            tables = [row["name"] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type="
                "'table'")]
            blob = ""
            for table in tables:
                try:
                    rows = db.execute(
                        f"SELECT * FROM {table} LIMIT 200").fetchall()
                except Exception:  # noqa: BLE001
                    continue
                blob += str([dict(row) for row in rows])
        assert "sekret" not in blob


def test_registry_lists_honest_status(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        registry = client.get("/api/v1/integrations").json()
        by_id = {item["integration_id"]: item
                 for item in registry}
        assert by_id["garmin"]["status"] == "UNAVAILABLE"
        assert by_id["garmin"]["mock"] is True
        assert by_id["generic"]["status"] == "AVAILABLE"
        assert "integration:ingest" in by_id["generic"][
            "capabilities"]
        assert "key_hash" not in str(registry)
        import re
        assert not re.search(r"\b[0-9a-f]{64}\b", str(registry))


def test_plane_has_no_db_network_or_shell_surface():
    import pathlib
    source = (pathlib.Path(__file__).resolve().parent.parent /
              "coordinator" / "app" / "n8n.py").read_text(
                  encoding="utf-8")
    for token in ("sqlite3.connect", "httpx", "requests",
                  "urlopen", "subprocess", "os.system",
                  "eval(", "https://", "0.0.0.0"):
        assert token not in source, f"n8n.py: {token}"
    # No outbound calls, no shell, no direct SQL strings
    # outside the ledger helpers: all state flows through
    # the shared database module.
    assert "socket" not in source
