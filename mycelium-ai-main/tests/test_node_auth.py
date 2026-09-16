"""FASE 7 tests (BIG #16): node-auth hardening.

Identity is cryptographically bound to its token:
- new identities require a non-trivial token (403 without)
- choosing an existing node_id alone gains nothing
  (legacy freeze; token bind needs operator rotation)
- rotation needs the current token (bound) or the
  operator key (legacy)
- enable/disable need the operator key
- only token-bound identities may campaign
"""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

OPERATOR_KEY = "op-key-node-auth-123"


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "auth.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "auth-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", OPERATOR_KEY)
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_first_registration_requires_token(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert client.post("/api/v1/nodes/register", json={
            "node_id": "node-new", "hostname": "h",
            "capabilities": []}).status_code == 403
        # Trivial tokens refuse as well.
        assert client.post("/api/v1/nodes/register", json={
            "node_id": "node-new", "hostname": "h",
            "capabilities": [], "node_token": "short"}
        ).status_code == 422
        assert client.post("/api/v1/nodes/register", json={
            "node_id": "node-new", "hostname": "h",
            "capabilities": ["exec:system_inventory"],
            "node_token": "first-token-123456"}
        ).status_code == 201


def test_identity_squat_gains_nothing(tmp_path, monkeypatch):
    from coordinator.app.database import connection
    for client in make_client(tmp_path, monkeypatch):
        # Pre-existing legacy identity with real capabilities.
        with connection() as db:
            db.execute(
                "INSERT INTO nodes (node_id, hostname, tier, "
                "capabilities, cpu_cores, memory_mb, "
                "energy_source, last_seen, status) VALUES (?, "
                "?, ?, ?, ?, ?, ?, ?, ?)",
                ("node-victim", "h", "seed",
                 '["exec:system_inventory"]', 1, 0, "unknown",
                 "2026-09-16T00:00:00+00:00", "online"))
        # Attacker re-registers the id with hostile caps and a
        # token, but no operator key: refused.
        assert client.post("/api/v1/nodes/register", json={
            "node_id": "node-victim", "hostname": "evil",
            "capabilities": ["exec:everything"],
            "node_token": "attacker-token-123456"}
        ).status_code == 403
        # Tokenless re-register "works" but changes nothing.
        assert client.post("/api/v1/nodes/register", json={
            "node_id": "node-victim", "hostname": "evil",
            "capabilities": ["exec:everything"]}
        ).status_code == 201
        stored = client.get(
            "/api/v1/nodes/node-victim").json()
        assert stored["hostname"] == "h"
        assert stored["capabilities"] == ["exec:system_inventory"]
        # Operator rotation binds a token to the legacy id.
        assert client.post(
            "/api/v1/nodes/node-victim/rotate-token",
            json={"new_token": "victim-token-123456",
                  "operator_key": "wrong-key"}).status_code == 403
        assert client.post(
            "/api/v1/nodes/node-victim/rotate-token",
            json={"new_token": "victim-token-123456",
                  "operator_key": OPERATOR_KEY}).json()[
                      "bound"] is True
        # Rotation without the current token now refuses.
        assert client.post(
            "/api/v1/nodes/node-vision-rotate/rotate-token",
            json={"new_token": "x" * 20}).status_code == 404
        assert client.post(
            "/api/v1/nodes/node-victim/rotate-token",
            json={"current_token": "wrong-current-token-1",
                  "new_token": "another-token-123456"}
        ).status_code == 403
        assert client.post(
            "/api/v1/nodes/node-victim/rotate-token",
            json={"current_token": "victim-token-123456",
                  "new_token": "victim-token-789012"}
        ).json()["bound"] is True
        # Old token dead, new token live.
        assert client.post(
            "/api/v1/nodes/node-victim/heartbeat",
            json={"available": True,
                  "node_token": "victim-token-123456"}
        ).status_code == 403
        assert client.post(
            "/api/v1/nodes/node-victim/heartbeat",
            json={"available": True,
                  "node_token": "victim-token-789012"}
        ).status_code == 204


def test_enable_disable_need_operator(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        client.post("/api/v1/nodes/register", json={
            "node_id": "node-op", "hostname": "h",
            "capabilities": [],
            "node_token": "op-node-token-123456"})
        assert client.post(
            "/api/v1/nodes/node-op/disable",
            json={}).status_code == 403
        assert client.post(
            "/api/v1/nodes/node-op/disable",
            json={"operator_key": OPERATOR_KEY}).json()[
                "status"] == "disabled"
        assert client.post(
            "/api/v1/nodes/node-op/enable",
            json={}).status_code == 403
        assert client.post(
            "/api/v1/nodes/node-op/enable",
            json={"operator_key": OPERATOR_KEY}).json()[
                "status"] == "online"


def test_campaign_needs_bound_identity(tmp_path, monkeypatch):
    from coordinator.app.database import connection
    for client in make_client(tmp_path, monkeypatch):
        with connection() as db:
            db.execute(
                "INSERT INTO nodes (node_id, hostname, tier, "
                "capabilities, cpu_cores, memory_mb, "
                "energy_source, last_seen, status, "
                "coordinator_capable) VALUES (?, ?, ?, ?, ?, "
                "?, ?, ?, ?, ?)",
                ("node-leg", "h", "seed", "[]", 1, 0,
                 "unknown", "2026-09-16T00:00:00+00:00",
                 "online", 1))
        assert client.post("/api/v1/coordinator/campaign",
                           json={
                               "node_id": "node-leg"}
                           ).status_code == 409
        client.post("/api/v1/nodes/node-leg/rotate-token", json={
            "new_token": "leg-token-123456",
            "operator_key": OPERATOR_KEY})
        assert client.post(
            "/api/v1/nodes/node-leg/heartbeat",
            json={"available": True,
                  "node_token": "leg-token-123456"}
        ).status_code == 204
        assert client.post("/api/v1/coordinator/campaign",
                           json={
                               "node_id": "node-leg"}
                           ).status_code == 200
