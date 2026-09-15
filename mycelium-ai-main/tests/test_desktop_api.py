"""Desktop-agent API tests (Fase I/K/L/M/Q).

Full HTTP lifecycle: propose -> decision -> dispatch -> result,
rejection, cancellation, approval-boundary enforcement, agent
status, plans, git read-only routes and project context. POST-only
where it matters.
"""

import os
import subprocess

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def client(tmp_path, monkeypatch):
    os.environ["MYCELIUM_DATABASE_PATH"] = str(tmp_path / "desk.db")
    os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = str(
        tmp_path / "desk-state.db")
    with TestClient(main_mod.app) as test_client:
        yield test_client


def propose(test_client, action_type="click", parameters=None,
            action_id=None):
    if parameters is None:
        parameters = {"x": 100, "y": 200}
    body = {"action_type": action_type, "parameters": parameters}
    if action_id:
        body["action_id"] = action_id
    return test_client.post("/api/v1/desktop/actions", json=body)


def test_full_approval_chain_click(tmp_path, monkeypatch):
    for test_client in client(tmp_path, monkeypatch):
        created = propose(test_client, action_id="dact-chain")
        assert created.status_code == 201
        assert created.json()["status"] == "pending_approval"

        decided = test_client.post(
            "/api/v1/desktop/actions/dact-chain/decision",
            json={"response": "YES", "decided_by": "jelles"})
        assert decided.json()["status"] == "approved"

        dispatched = test_client.post(
            "/api/v1/desktop/actions/dact-chain/dispatch")
        assert dispatched.json()["status"] == "dispatched"

        closed = test_client.post(
            "/api/v1/desktop/actions/dact-chain/result",
            json={"status": "completed",
                  "observation_reference": "obs-1"})
        assert closed.json()["status"] == "completed"
        assert closed.json()["result"]["observation_reference"] == "obs-1"


def test_screenshot_preapproved_but_still_gated(tmp_path, monkeypatch):
    for test_client in client(tmp_path, monkeypatch):
        created = propose(test_client, "screenshot", {},
                          action_id="dact-shot")
        assert created.json()["status"] == "approved"
        # ...but results still require dispatch first
        early = test_client.post(
            "/api/v1/desktop/actions/dact-shot/result",
            json={"status": "completed"})
        assert early.status_code == 422
        assert test_client.post(
            "/api/v1/desktop/actions/dact-shot/dispatch").status_code == 200


def test_rejection_and_cancel_paths(tmp_path, monkeypatch):
    for test_client in client(tmp_path, monkeypatch):
        propose(test_client, "click", {"x": 1, "y": 1},
                action_id="dact-no")
        rejected = test_client.post(
            "/api/v1/desktop/actions/dact-no/decision",
            json={"response": "NO"})
        assert rejected.json()["status"] == "rejected"

        propose(test_client, "click", {"x": 1, "y": 1},
                action_id="dact-stop")
        cancelled = test_client.post(
            "/api/v1/desktop/actions/dact-stop/cancel",
            json={"response": "NO"})
        assert cancelled.json()["status"] == "cancelled"


def test_unrecognized_decision_defaults_to_deny(tmp_path, monkeypatch):
    for test_client in client(tmp_path, monkeypatch):
        propose(test_client, "click", {"x": 1, "y": 1},
                action_id="dact-vaag")
        decided = test_client.post(
            "/api/v1/desktop/actions/dact-vaag/decision",
            json={"response": "ja hoor"})
        assert decided.json()["status"] == "rejected"


def test_approval_boundary_enforced(tmp_path, monkeypatch):
    for test_client in client(tmp_path, monkeypatch):
        # unknown action type refused
        assert propose(test_client, "run_shell",
                       {"cmd": "x"}).status_code == 422
        # dispatch without approval refused
        propose(test_client, "click", {"x": 1, "y": 1},
                action_id="dact-gate")
        assert test_client.post(
            "/api/v1/desktop/actions/dact-gate/dispatch").status_code == 422
        # double decision refused
        test_client.post("/api/v1/desktop/actions/dact-gate/decision",
                         json={"response": "YES"})
        assert test_client.post(
            "/api/v1/desktop/actions/dact-gate/decision",
            json={"response": "YES"}).status_code == 422
        # decision binds to action
        assert test_client.post(
            "/api/v1/desktop/actions/nope/decision",
            json={"response": "YES"}).status_code == 404
        # failed result needs an error
        test_client.post("/api/v1/desktop/actions/dact-gate/dispatch")
        assert test_client.post(
            "/api/v1/desktop/actions/dact-gate/result",
            json={"status": "failed"}).status_code == 422


def test_desktop_reads_and_agent_status(tmp_path, monkeypatch):
    for test_client in client(tmp_path, monkeypatch):
        propose(test_client, "click", {"x": 1, "y": 1},
                action_id="dact-list")
        listing = test_client.get("/api/v1/desktop/actions")
        assert listing.status_code == 200
        assert any(entry["action_id"] == "dact-list"
                   for entry in listing.json())
        single = test_client.get("/api/v1/desktop/actions/dact-list")
        assert single.json()["action_type"] == "click"
        status = test_client.get("/api/v1/agent/status")
        assert status.status_code == 200
        body = status.json()
        assert "waiting" in body and "activity" in body
        assert any(entry["action_id"] == "dact-list"
                   for entry in body["waiting"])


def test_agent_status_reports_desktop_nodes(tmp_path, monkeypatch):
    for test_client in client(tmp_path, monkeypatch):
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "desk-01", "hostname": "pc",
            "capabilities": ["agent:desktop", "desktop.screen.read"]})
        status = test_client.get("/api/v1/agent/status").json()
        assert status["agents_online"] == 1
        assert status["desktop_nodes"][0]["node_id"] == "desk-01"


def test_plans_endpoints(tmp_path, monkeypatch):
    for test_client in client(tmp_path, monkeypatch):
        plan = {"plan_id": "plan-ui", "goal": "Verbeter UI",
                "steps": [{"step_id": "s1", "description": "Open chat",
                           "required_capabilities": ["desktop.mouse.click"],
                           "requires_approval": True}]}
        created = test_client.post("/api/v1/plans", json=plan)
        assert created.status_code == 200
        assert created.json()["plan_id"] == "plan-ui"
        proposal = test_client.post("/api/v1/plans/to-proposal", json={
            "plan": plan, "adapter_id": "mycelium-plan",
            "request_id": "req-ui-1"})
        assert proposal.status_code == 200
        assert proposal.json()["requires_approval"] is True
        # empty plan refused, no second approval dialect
        bad = dict(plan, steps=[])
        assert test_client.post("/api/v1/plans",
                                json=bad).status_code == 422


def test_git_routes_readonly(tmp_path, monkeypatch):
    try:
        subprocess.run(["git", "--version"], capture_output=True,
                       timeout=10, check=True)
    except (OSError, subprocess.SubprocessError):
        import pytest
        pytest.skip("git missing")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True,
                   check=True, timeout=30)
    (repo / "x.txt").write_text("x\n", encoding="utf-8")
    for test_client in client(tmp_path, monkeypatch):
        status = test_client.get("/api/v1/git/status",
                                 params={"repo": str(repo)})
        assert status.status_code == 200
        assert "lines" in status.json()
        diff = test_client.get("/api/v1/git/diff",
                               params={"repo": str(repo)})
        assert diff.status_code == 200
        missing = test_client.get("/api/v1/git/status",
                                  params={"repo": str(tmp_path / "weg")})
        assert missing.status_code == 422
        plain = test_client.get("/api/v1/git/status",
                                params={"repo": str(tmp_path)})
        assert plain.status_code == 502


def test_git_routes_are_get_only(tmp_path, monkeypatch):
    for test_client in client(tmp_path, monkeypatch):
        assert test_client.post("/api/v1/git/status").status_code == 405
        assert test_client.post("/api/v1/git/diff").status_code == 405


def test_project_context_route(tmp_path, monkeypatch):
    for test_client in client(tmp_path, monkeypatch):
        response = test_client.get("/api/v1/project/context")
        assert response.status_code == 200
        assert "repository" in response.json()


def test_web_agent_buttons(tmp_path, monkeypatch):
    for test_client in client(tmp_path, monkeypatch):
        propose(test_client, "click", {"x": 1, "y": 1},
                action_id="dact-web")
        approved = test_client.post(
            "/web/desktop/dact-web/decision",
            content="response=YES",
            headers={"Content-Type":
                     "application/x-www-form-urlencoded"})
        assert approved.history[0].status_code == 303
        page = test_client.get("/agents")
        assert "dact-web" in page.text
