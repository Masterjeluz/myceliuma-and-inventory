"""Standalone desktop-agent tests (BIG #2, §17).

Process/identity, claim against the lease architecture, approval
revalidation, observe-act-observe loop, results, security surfaces
and API boundaries. Agent-to-coordinator traffic runs over real HTTP
against a live in-thread coordinator with tmp databases; the desktop
side uses side-effect-free fake/dry-run backends only.
"""

import os
import socket
import threading
import time

import httpx
import pytest

import coordinator.app.main as main_mod
from coordinator.app.observations import new_observation
from desktop_agent.agent import (
    ApprovalInvalid,
    CoordinatorUnavailable,
    DesktopAgent,
    clamp_max_steps,
)
from desktop_agent.identity import (
    FULL_CAPABILITIES,
    READONLY_CAPABILITIES,
    check_capabilities,
    stable_agent_id,
)

BASE_PORT_ENV = "MYCELIUM_TEST_AGENT_PORT"


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture(scope="module")
def live_base_url(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("agent-live")
    os.environ["MYCELIUM_DATABASE_PATH"] = str(tmp / "live.db")
    os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = str(tmp / "live-chat.db")
    import uvicorn
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(
        main_mod.app, host="127.0.0.1", port=port, lifespan="on",
        log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            answer = httpx.get(f"http://127.0.0.1:{port}/api/v1/health",
                               timeout=2)
            if answer.status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        raise RuntimeError("live coordinator did not start")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture()
def api(live_base_url):
    return httpx.Client(base_url=live_base_url, timeout=10)


class FakeBackend:
    """Captures executions, performs nothing."""

    def __init__(self, fail_with=None):
        self.calls = []
        self.shots = 0
        self.fail_with = fail_with

    def capabilities(self):
        return list(FULL_CAPABILITIES)

    def screenshot(self):
        self.shots += 1
        return new_observation(f"obs-fake-{self.shots}", 800, 600)

    def execute(self, action):
        from coordinator.app.agent_results import new_result
        self.calls.append(action)
        if self.fail_with:
            return new_result(action.action_id, "failed",
                              error=self.fail_with)
        reference = (f"obs-fake-{self.shots}"
                     if action.action_type == "screenshot" else "")
        return new_result(action.action_id, "completed",
                          observation_reference=reference)


def make_agent(api, backend=None, node_id="desktop-test-01",
               capabilities=None):
    return DesktopAgent(
        base_url=str(api.base_url), node_id=node_id,
        capabilities=capabilities or list(FULL_CAPABILITIES),
        backend=backend or FakeBackend(), poll_seconds=0.1,
        max_steps=5)


def register_node(api, node_id, capabilities=None):
    response = api.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": "test-pc",
        "capabilities": capabilities or list(FULL_CAPABILITIES)})
    assert response.status_code == 201


def propose_action(api, action_type, parameters, action_id):
    response = api.post("/api/v1/desktop/actions", json={
        "action_id": action_id, "action_type": action_type,
        "parameters": parameters})
    assert response.status_code == 201, response.text
    return response.json()


def approve_action(api, action_id):
    current = api.get(f"/api/v1/desktop/actions/{action_id}").json()
    if current["status"] != "pending_approval":
        return  # read-only actions arrive pre-approved by policy
    response = api.post(
        f"/api/v1/desktop/actions/{action_id}/decision",
        json={"response": "YES", "decided_by": "tester"})
    assert response.status_code == 200, response.text


def claim_own(agent, action_id, tries=25):
    """Drain claims until our action arrives (older approved actions
    from other tests may come first; claiming them is harmless)."""
    for _ in range(tries):
        claimed = agent.claim_next()
        if claimed is None:
            raise AssertionError(
                f"action '{action_id}' never claimable")
        if claimed["action_id"] == action_id:
            return claimed
    raise AssertionError(f"action '{action_id}' never claimable")


def run_until_done(agent, api, action_id, tries=25):
    """Poll until our action reaches a terminal state (foreign
    leftovers may be executed first; that is legitimate work)."""
    for _ in range(tries):
        agent.run_once()
        record = api.get(f"/api/v1/desktop/actions/{action_id}").json()
        if record["status"] in ("completed", "failed", "cancelled",
                                "blocked"):
            return record
    raise AssertionError(f"action '{action_id}' never finished")


# -- identity & capabilities ------------------------------------------

def test_stable_identity_without_hardware_ids():
    first, second = stable_agent_id(), stable_agent_id()
    assert first == second
    assert first.startswith("desktop_")
    import desktop_agent.identity as module
    source = open(module.__file__, encoding="utf-8").read().lower()
    assert "getnode(" not in source and "uuid" not in source
    assert "serial_number" not in source and "wmic" not in source


def test_capability_check_rejects_wildcards_and_unknown():
    assert check_capabilities(list(FULL_CAPABILITIES))
    with pytest.raises(ValueError):
        check_capabilities(["desktop.*"])
    with pytest.raises(ValueError):
        check_capabilities(["*"])
    with pytest.raises(ValueError):
        check_capabilities(["exec:shell"])
    with pytest.raises(ValueError):
        check_capabilities([])


def test_readonly_set_advertises_no_input():
    assert READONLY_CAPABILITIES == ["agent:desktop",
                                     "desktop.screen.read"]


def test_max_steps_bounded():
    assert clamp_max_steps(20) == 20
    assert clamp_max_steps(9999) == 100
    assert clamp_max_steps(0) == 1
    assert clamp_max_steps("veel") == 20


# -- claim against the lease architecture ------------------------------

def test_claim_hands_out_approved_action_once(api):
    register_node(api, "desktop-claim-01")
    propose_action(api, "screenshot", {}, "dact-claim-01")
    approve_action(api, "dact-claim-01")
    agent = make_agent(api, node_id="desktop-claim-01")
    first = claim_own(agent, "dact-claim-01")
    assert first["status"] == "dispatched"
    assert first["dispatched_by"] == "desktop-claim-01"
    second = agent.claim_next()
    assert second is None
    agent.close()


def test_claim_unknown_node_refused(api):
    agent = make_agent(api, node_id="desktop-ghost-99")
    with pytest.raises(CoordinatorUnavailable):
        agent.claim_next()
    agent.close()


def test_claim_wrong_capability_gets_nothing(api):
    register_node(api, "desktop-readonly-01",
                  ["agent:desktop", "desktop.screen.read"])
    propose_action(api, "click", {"x": 10, "y": 10}, "dact-cap-01")
    approve_action(api, "dact-cap-01")
    agent = make_agent(api, node_id="desktop-readonly-01",
                       capabilities=["agent:desktop",
                                     "desktop.screen.read"])
    assert agent.claim_next() is None
    agent.close()


def test_claim_stale_node_gets_nothing(api, live_base_url):
    import sqlite3
    register_node(api, "desktop-stale-01")
    db_path = os.environ["MYCELIUM_DATABASE_PATH"]
    db = sqlite3.connect(db_path)
    db.execute("UPDATE nodes SET last_seen='2000-01-01T00:00:00+00:00' "
               "WHERE node_id='desktop-stale-01'")
    db.commit()
    db.close()
    agent = make_agent(api, node_id="desktop-stale-01")
    assert agent.claim_next() is None
    agent.close()


# -- approval revalidation ----------------------------------------------

def test_revalidation_blocks_changed_action(api):
    register_node(api, "desktop-reval-01")
    propose_action(api, "click", {"x": 10, "y": 10}, "dact-reval-01")
    approve_action(api, "dact-reval-01")
    backend = FakeBackend()
    agent = make_agent(api, backend, node_id="desktop-reval-01")
    claimed = claim_own(agent, "dact-reval-01")
    tampered = dict(claimed, parameters={"x": 9999, "y": 9999})
    with pytest.raises(ApprovalInvalid):
        agent.execute_claimed(tampered)
    assert backend.calls == [] and backend.shots == 0
    agent.close()


def test_operator_cancel_between_claim_and_execute_blocks(api):
    register_node(api, "desktop-cancel-01")
    propose_action(api, "click", {"x": 10, "y": 10}, "dact-cancel-01")
    approve_action(api, "dact-cancel-01")
    backend = FakeBackend()
    agent = make_agent(api, backend, node_id="desktop-cancel-01")
    claimed = claim_own(agent, "dact-cancel-01")
    assert claimed["status"] == "dispatched"
    # operator revokes the lease before the agent acts
    cancelled = api.post("/api/v1/desktop/actions/dact-cancel-01/cancel",
                         json={"response": "NO"})
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    with pytest.raises(ApprovalInvalid):
        agent.execute_claimed(claimed)
    assert backend.calls == [] and backend.shots == 0
    agent.close()


def test_foreign_dispatch_never_executes(api):
    register_node(api, "desktop-foreign-01")
    register_node(api, "desktop-foreign-02")
    propose_action(api, "click", {"x": 10, "y": 10}, "dact-foreign-01")
    approve_action(api, "dact-foreign-01")
    first = make_agent(api, node_id="desktop-foreign-01")
    claimed = claim_own(first, "dact-foreign-01")
    assert claimed["dispatched_by"] == "desktop-foreign-01"
    second_backend = FakeBackend()
    second = make_agent(api, second_backend,
                        node_id="desktop-foreign-02")
    with pytest.raises(ApprovalInvalid):
        second.execute_claimed(claimed)
    assert second_backend.calls == []
    first.close()
    second.close()


# -- observe-act-observe loop & results ----------------------------------

def test_screenshot_action_full_cycle(api):
    register_node(api, "desktop-cycle-01")
    propose_action(api, "screenshot", {}, "dact-cycle-01")
    approve_action(api, "dact-cycle-01")
    backend = FakeBackend()
    agent = make_agent(api, backend, node_id="desktop-cycle-01")
    record = run_until_done(agent, api, "dact-cycle-01")
    assert [call.action_type for call in backend.calls].count(
        "screenshot") >= 1
    assert record["status"] == "completed"
    assert record["result"]["observation_reference"].startswith("obs-")
    assert record["result"]["provenance"]["human_verified"] is False
    agent.close()


def test_input_wrapped_in_pre_post_screenshots(api):
    register_node(api, "desktop-wrap-01")
    propose_action(api, "click", {"x": 10, "y": 10}, "dact-wrap-01")
    approve_action(api, "dact-wrap-01")
    backend = FakeBackend()
    agent = make_agent(api, backend, node_id="desktop-wrap-01")
    record = run_until_done(agent, api, "dact-wrap-01")
    assert backend.shots >= 2  # observe -> act -> observe per input
    assert record["status"] == "completed"
    assert record["result"]["observation_reference"].startswith("obs-")
    agent.close()


def test_failed_action_reported_not_retried_blindly(api):
    register_node(api, "desktop-fail-01")
    propose_action(api, "click", {"x": 10, "y": 10}, "dact-fail-01")
    approve_action(api, "dact-fail-01")
    backend = FakeBackend(fail_with="knop niet gevonden")
    agent = make_agent(api, backend, node_id="desktop-fail-01")
    record = run_until_done(agent, api, "dact-fail-01")
    assert record["status"] == "failed"
    assert record["result"]["error"] == "knop niet gevonden"
    agent.close()


def test_max_steps_bounds_a_run(api):
    register_node(api, "desktop-steps-01")
    for index in range(3):
        action_id = f"dact-steps-0{index}"
        propose_action(api, "screenshot", {}, action_id)
        approve_action(api, action_id)
    agent = make_agent(api, FakeBackend(), node_id="desktop-steps-01")
    agent.max_steps = 2
    assert agent.run() == "step-limit"
    assert agent.steps_done == 2
    agent.close()


def test_stop_flag_halts_between_actions(api):
    register_node(api, "desktop-stop-01")
    agent = make_agent(api, FakeBackend(), node_id="desktop-stop-01")
    agent.stop()
    assert agent.run() == "stopped"
    agent.close()


def test_coordinator_loss_backs_off_without_acting():
    backend = FakeBackend()
    agent = DesktopAgent(base_url="http://127.0.0.1:9",
                         node_id="desktop-down-01",
                         capabilities=list(FULL_CAPABILITIES),
                         backend=backend, poll_seconds=0.1, max_steps=1)
    with pytest.raises(CoordinatorUnavailable):
        agent.run_once()
    assert backend.calls == [] and backend.shots == 0
    agent.close()


# -- security surfaces ----------------------------------------------------

def test_shell_and_code_never_become_actions(api):
    for action_type, parameters in (
            ("run_shell", {"cmd": "whoami"}),
            ("exec_python", {"code": "1+1"}),
            ("powershell", {"script": "Get-ChildItem"})):
        response = api.post("/api/v1/desktop/actions", json={
            "action_type": action_type, "parameters": parameters})
        assert response.status_code == 422


def test_agent_package_has_no_inbound_or_shell_surface():
    import desktop_agent.agent as agent_mod
    import desktop_agent.main as main_mod_file
    for module in (agent_mod, main_mod_file):
        source = open(module.__file__, encoding="utf-8").read().lower()
        for token in ("import subprocess", "from subprocess", "os.system",
                      "shell=true", "eval(", "listen(", "accept(",
                      "add_api_route", "@app."):
            assert token not in source


def test_claim_endpoint_post_only_and_validated(api):
    # GET /next resolves to the single-action lookup (404), never a
    # claim: claiming is POST-only by construction.
    assert api.get("/api/v1/desktop/actions/next").status_code == 404
    assert api.post("/api/v1/desktop/actions/next",
                    json={}).status_code == 422
    assert api.post("/api/v1/desktop/actions/next",
                    json={"node_id": "nope"}).status_code == 404
    assert api.get("/api/v1/desktop/actions",
                   params={"status": "alles"}).status_code == 422
    filtered = api.get("/api/v1/desktop/actions",
                       params={"status": "completed"})
    assert filtered.status_code == 200
    assert all(entry["status"] == "completed"
               for entry in filtered.json())
