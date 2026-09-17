"""BIG #22 tests: desktop agent hands.

Claim → revalidate → act → report over HTTP, lease +
attempt bounds, agent-offline visibility, mission
continuation after desktop results, and the hard
boundaries (no shell, no physical via desktop, no
credential leaks).
"""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

TOKEN = "hands-token-1234567890"
CAPS = ["agent:desktop", "desktop.screen.read",
        "desktop.mouse.click", "desktop.keyboard.type",
        "desktop.mouse.move", "desktop.keyboard.press",
        "desktop.screen.wait"]


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "hands.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "hands-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def register(client, node_id="hands-01", capabilities=None):
    response = client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": "pc",
        "capabilities": capabilities or CAPS,
        "node_token": TOKEN})
    assert response.status_code == 201, response.text


def propose(client, action_type, parameters=None,
            action_id=None):
    body = {"action_type": action_type,
            "parameters": parameters or {}}
    if action_id:
        body["action_id"] = action_id
    response = client.post("/api/v1/desktop/actions",
                           json=body)
    assert response.status_code == 201, response.text
    return response.json()


def claim(client, node_id="hands-01"):
    return client.post("/api/v1/desktop/actions/next",
                       json={"node_id": node_id,
                             "node_token": TOKEN}).json()


def test_screenshot_success_end_to_end(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        proposed = propose(client, "screenshot", {})
        assert proposed["status"] == "approved"
        claimed = claim(client)
        assert claimed is not None
        assert claimed["lease_until"] != ""
        assert claimed["attempt_count"] == 1
        reported = client.post(
            f"/api/v1/desktop/actions/"
            f"{proposed['action_id']}/result",
            json={"status": "completed",
                  "observation_reference": "obs-shot-1"})
        assert reported.status_code == 200, reported.text
        stored = client.get(
            f"/api/v1/desktop/actions/"
            f"{proposed['action_id']}").json()
        assert stored["status"] == "completed"


def test_click_type_wait_require_approval_flow(tmp_path,
                                               monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        for action_type, params in (
                ("click", {"x": 10, "y": 10}),
                ("type_text", {"text": "hello"})):
            proposed = propose(client, action_type, params)
            assert proposed["status"] == "pending_approval"
            # Not claimable before approval.
            assert claim(client) is None
            decided = client.post(
                f"/api/v1/desktop/actions/"
                f"{proposed['action_id']}/decision",
                json={"response": "YES",
                      "decided_by": "tester"})
            assert decided.status_code == 200
            claimed = claim(client)
            assert claimed is not None
            assert claimed["action_id"] == proposed["action_id"]
            assert client.post(
                f"/api/v1/desktop/actions/"
                f"{proposed['action_id']}/result",
                json={"status": "completed",
                      "observation_reference": "obs-1"}
            ).status_code == 200
        # Read-only wait is approved by policy, never by
        # human: directly claimable, still bounded.
        waiting = propose(client, "wait", {"ms": 100})
        assert waiting["status"] == "approved"
        assert claim(client)["action_id"] == waiting["action_id"]


def test_wrong_or_missing_approval(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        proposed = propose(client, "click", {"x": 1, "y": 2})
        assert client.post(
            f"/api/v1/desktop/actions/"
            f"{proposed['action_id']}/decision",
            json={"response": "maybe",
                  "decided_by": "tester"}).json()[
                      "status"] == "rejected"
        assert claim(client) is None
        proposed2 = propose(client, "click", {"x": 1, "y": 2})
        assert client.post(
            f"/api/v1/desktop/actions/"
            f"{proposed2['action_id']}/decision",
            json={"response": "YES",
                  "decided_by": ""}).status_code == 422
        assert claim(client) is None


def test_stale_action_lease_expiry_and_attempt_cap(tmp_path,
                                                   monkeypatch):
    from coordinator.app.database import chat_connection
    from coordinator.app.main import expire_desktop_leases
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        proposed = propose(client, "screenshot", {})
        claimed = claim(client)
        assert claimed is not None
        action_id = proposed["action_id"]
        # Agent dies: backdate the lease, expire, recover.
        with chat_connection() as db:
            row = db.execute(
                "SELECT record FROM desktop_actions WHERE "
                "action_id=?", (action_id,)).fetchone()
            import json
            record = json.loads(row["record"])
            record["lease_until"] = "2020-01-01T00:00:00+00:00"
            db.execute("UPDATE desktop_actions SET record=? "
                       "WHERE action_id=?",
                       (json.dumps(record), action_id))
        summary = expire_desktop_leases("2026-01-01T00:00:00+00:00")
        assert summary == {"recovered": 1, "blocked": 0}
        stored = client.get(
            f"/api/v1/desktop/actions/{action_id}").json()
        assert stored["status"] == "approved"
        assert stored["attempt_count"] == 1
        # Exhaust attempts: dispatch twice more, expire again.
        for _ in range(2):
            assert claim(client) is not None
            with chat_connection() as db:
                row = db.execute(
                    "SELECT record FROM desktop_actions WHERE "
                    "action_id=?", (action_id,)).fetchone()
                record = json.loads(row["record"])
                record["lease_until"] = \
                    "2020-01-01T00:00:00+00:00"
                db.execute(
                    "UPDATE desktop_actions SET record=? WHERE "
                    "action_id=?",
                    (json.dumps(record), action_id))
            expire_desktop_leases("2026-01-01T00:00:00+00:00")
        stored = client.get(
            f"/api/v1/desktop/actions/{action_id}").json()
        assert stored["status"] == "blocked"
        assert stored["attempt_count"] == 3
        assert claim(client) is None


def test_agent_revalidate_refuses_expired_lease(tmp_path,
                                                monkeypatch):
    from desktop_agent.agent import ApprovalInvalid, DesktopAgent
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        proposed = propose(client, "screenshot", {})
        claimed = claim(client)
        agent = DesktopAgent(
            base_url="http://127.0.0.1:9", node_id="hands-01",
            capabilities=list(CAPS), node_token=TOKEN)
        expired = dict(claimed)
        expired["lease_until"] = "2020-01-01T00:00:00+00:00"
        with pytest.raises(ApprovalInvalid):
            agent.revalidate(expired)


def test_agent_offline_visible_as_waiting(tmp_path,
                                          monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        proposed = propose(client, "screenshot", {})
        claimed = claim(client)
        assert claimed is not None
        # No agent process acts: the mission loop would see
        # waiting_agent; the action stays visibly dispatched.
        status = client.get("/api/v1/agent/status").json()
        assert status["current_action"] is not None
        stored = client.get(
            f"/api/v1/desktop/actions/"
            f"{proposed['action_id']}").json()
        assert stored["status"] == "dispatched"
        assert stored["dispatched_by"] == "hands-01"


def test_result_returns_to_mission_and_loop_continues(
        tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        conversation = client.post(
            "/api/v1/chat", json={"message": "hi"}).json()[
                "conversation_id"]
        mission_id = client.post("/api/v1/missions", json={
            "conversation_id": conversation,
            "goal": "take a look",
            "steps": [{"kind": "desktop",
                       "description": "Look",
                       "action_type": "screenshot",
                       "parameters": {}}]}).json()["mission_id"]
        client.post(f"/api/v1/missions/{mission_id}/approve",
                    json={"response": "YES",
                          "decided_by": "tester"})
        first = client.post(
            f"/api/v1/missions/{mission_id}/run",
            json={"max_rounds": 10}).json()
        assert first["outcome"] == "stopped"
        assert first["stop_reason"] == "waiting_agent"
        action_id = first["action"]["action_id"]
        claimed = claim(client)
        assert claimed["action_id"] == action_id
        client.post(f"/api/v1/desktop/actions/{action_id}/result",
                    json={"status": "completed",
                          "observation_reference": "obs-m-1"})
        done = client.post(f"/api/v1/missions/{mission_id}/run",
                           json={"max_rounds": 10}).json()
        assert done["outcome"] == "completed", done
        assert done.get("memory_id", "").startswith("mem_")


def test_physical_action_still_refused(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        # No shell-like action type exists in the contract.
        assert client.post("/api/v1/desktop/actions", json={
            "action_type": "shell",
            "parameters": {"command": "whoami"}}
        ).status_code == 422
        assert client.post("/api/v1/desktop/actions", json={
            "action_type": "robot.move",
            "parameters": {}}).status_code == 422
        # Out-of-range coordinates refuse.
        assert client.post("/api/v1/desktop/actions", json={
            "action_type": "click",
            "parameters": {"x": 999999, "y": 0}}
        ).status_code == 422


def test_desktop_shell_subprocess_scan():
    import pathlib
    import re
    app = pathlib.Path(__file__).resolve().parent.parent / \
        "coordinator" / "app"
    agent = pathlib.Path(__file__).resolve().parent.parent / \
        "desktop_agent"
    for path in (app / "desktop_runtime.py",
                 app / "agent_loop.py", app / "computer_actions.py",
                 agent / "agent.py", agent / "main.py"):
        code = []
        in_docstring = False
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith('"""'):
                if stripped.count('"""') == 1:
                    in_docstring = not in_docstring
                continue
            if in_docstring or stripped.startswith("#"):
                continue
            code.append(re.sub(r'"[^"]*"|\'[^\']*\'', '""',
                              line))
        blob = "\n".join(code)
        for token in ("subprocess", "os.system", "os.popen",
                      "os.exec", "eval(", "__import__",
                      "importlib"):
            assert token not in blob, f"{path.name}: {token}"


def test_credentials_never_leaked(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        proposed = propose(client, "screenshot", {})
        blob = ""
        blob += str(client.get("/api/v1/nodes").json())
        blob += str(client.get(
            "/api/v1/nodes/hands-01").json())
        blob += str(client.get("/api/v1/agent/status").json())
        blob += str(client.get("/api/v1/desktop/actions").json())
        blob += str(client.get(
            f"/api/v1/desktop/actions/"
            f"{proposed['action_id']}").json())
        assert TOKEN not in blob
        assert "auth_token_hash" not in blob
