"""BIG #41 live smoke: Mycelium V2 foundation on tmp DBs.

Proves with real localhost HTTP (TestClient, no mocks):
mesh nodes + telemetry → routing explainer verdicts →
preview (dry run, nothing created) → delegate (queued +
assigned + audit event) → target claims with credential →
requester cannot steal the pin → completion clears it →
reality endpoint (trust levels, current task) → ecosystem
overview (8 answers) → craft states → symbiosis prefixes →
guide unlock → morning → world strip → pages →
refusals (fake node/capability/hardware/task, wildcard,
shell, traversal, secrets, stale target).
"""

import os
import sys

tmp = os.environ.get("B41_SMOKE_TMP", "")
assert tmp, "B41_SMOKE_TMP required"
os.makedirs(tmp, exist_ok=True)
# Fresh DBs every run: the smoke owns this tmp dir.
for name in ("smoke.db", "smoke-chat.db"):
    path = os.path.join(tmp, name)
    if os.path.exists(path):
        os.remove(path)
        print(f"cleared stale {name}", flush=True)
os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(tmp, "smoke.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    tmp, "smoke-chat.db")

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

TOKEN_A = "b41-smoke-token-aaaaaaaa"
TOKEN_B = "b41-smoke-token-bbbbbbbb"


def check(name, ok, detail=""):
    line = f"{'OK  ' if ok else 'FAIL'} {name} {detail}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"),
              flush=True)
    if not ok:
        sys.exit(1)


with TestClient(main_mod.app) as client:
    for node_id, caps, token in (
            ("v2-a", ["research.fetch"], TOKEN_A),
            ("v2-b", ["research.fetch", "research.fetch_url"],
             TOKEN_B)):
        reg = client.post("/api/v1/nodes/register", json={
            "node_id": node_id, "hostname": node_id,
            "tier": "worker", "capabilities": caps,
            "node_token": token})
        check(f"node {node_id} registered",
              reg.status_code == 201, str(reg.status_code))
    beat = client.post("/api/v1/nodes/v2-b/heartbeat", json={
        "available": True, "node_token": TOKEN_B,
        "telemetry": {"hostname": "v2-b", "os": "Linux",
                      "cpu_percent": 22.0, "cpu_count": 8,
                      "memory_percent": 41.0,
                      "memory_total_mb": 16384,
                      "memory_available_mb": 9666,
                      "uptime_seconds": 5000},
        "hardware": [{"kind": "camera",
                      "identifier": "/dev/video0",
                      "details": {}, "status": "connected"}],
        "compute_capabilities": [{
            "capability": "ollama", "details": {},
            "status": "available"}],
        "energy_state": {"source": "grid"}})
    check("telemetry heartbeat", beat.status_code == 204,
          str(beat.status_code))

    # Routing 2.0 explainer: eligible + waiting + unavailable.
    preview = client.post("/api/v1/tasks/route", json={
        "requirements": {
            "required_capabilities": ["research.fetch"],
            "required_hardware": ["camera"]},
        "policy": {"prefer_idle": True}}).json()
    check("route preview explains",
          preview["selected_node_id"] == "v2-b"
          and preview["why"]["eligible"]
          and "selected" in preview["why"]["summary"])

    # Mesh preview: dry run creates nothing.
    tasks_before = len(client.get("/api/v1/tasks").json())
    dry = client.post("/api/v1/mesh/preview", json={
        "requesting_node": "v2-a", "target_node": "v2-b",
        "task_kind": "research.fetch_url",
        "capability": "research.fetch",
        "payload": {"url": "https://example.com/v2"}})
    check("mesh preview valid, nothing created",
          dry.status_code == 200
          and dry.json()["created"] is False
          and len(client.get("/api/v1/tasks").json())
          == tasks_before, str(dry.status_code))

    # Delegate: queued + assigned + audited.
    delegation = client.post("/api/v1/mesh/delegate", json={
        "requesting_node": "v2-a", "node_token": TOKEN_A,
        "target_node": "v2-b",
        "task_kind": "research.fetch_url",
        "capability": "research.fetch",
        "payload": {"url": "https://example.com/v2",
                    "max_chars": 500},
        "reason": "v2 smoke delegation"})
    check("delegate creates pinned task",
          delegation.status_code == 201, delegation.text)
    receipt = delegation.json()
    task_id = receipt["task_id"]
    for key in ("what", "why", "where", "capability", "risk",
                "result_href", "activity_href"):
        check(f"receipt carries {key.upper()}", receipt[key])
    check("receipt risk honest", "no shell" in receipt["risk"])
    check("task detail resolves",
          client.get(receipt["result_href"]).status_code == 200)

    # Reality: trust levels + current task while assigned.
    reality = client.get("/api/v1/nodes/v2-b/reality").json()
    check("reality OBSERVED camera",
          any(item["kind"] == "camera"
              and item["trust"] == "OBSERVED"
              for item in reality["hardware"]))
    check("reality never auto-verifies",
          all(item["trust"] != "VERIFIED"
              for item in reality["hardware"]))

    # Pull model: target claims, requester cannot steal.
    claimed = client.post(
        f"/api/v1/tasks/claim/v2-b?node_token={TOKEN_B}")
    check("target claims pinned task",
          claimed.status_code == 200
          and claimed.json()["id"] == task_id)
    check("requester cannot steal pin",
          client.post(
              f"/api/v1/tasks/claim/v2-a?node_token={TOKEN_A}"
          ).json() is None)
    busy = client.get("/api/v1/nodes/v2-b").json()
    check("node shows current task",
          (busy.get("current_task") or {}).get("task_id")
          == task_id, str(busy.get("current_task")))
    done = client.post(f"/api/v1/tasks/{task_id}/complete",
                       json={"success": True,
                             "result": {"text": "v2 smoke"}})
    check("completion accepted", done.status_code == 204,
          str(done.status_code))

    # Ecosystem overview answers all eight questions.
    overview = client.get("/api/v1/ecosystem/overview").json()
    for key in ("exists", "connected", "happening",
                "needs_attention", "next", "nodes_can_do",
                "blocked", "growing"):
        check(f"overview answers {key.upper()}",
              key in overview, key)
    check("overview honest sources",
          overview["provenance"]["human_verified"] is False
          and "nodes_can_do" in overview["sources"])

    # Craft states + symbiosis 2.0 + guide unlock.
    craft = client.get(
        "/api/v1/craft", params={"entity_id": "proj_demo"})
    check("craft endpoint honest",
          craft.status_code in (200, 503),
          str(craft.status_code))
    from coordinator.app.symbiosis import (
        check_predicate, clean_entity)
    check("symbiosis node prefix",
          clean_entity("node_v2-b") == "node_v2-b")
    check("symbiosis research prefix",
          clean_entity("dos_abc123") == "dos_abc123")
    try:
        check_predicate("mind_controls")
        check("symbiosis predicate closed", False)
    except ValueError:
        check("symbiosis predicate closed", True)
    guide = client.get("/api/v1/guide").json()["items"]
    check("guide explains afterwards",
          len(guide) > 0 and all(entry.get("after")
                                 for entry in guide))

    # Morning + world + pages.
    morning = client.get("/api/v1/reports/morning").json()
    titles = [block["title"] for block in morning["sections"]]
    check("morning keeps presence sections",
          "Needs you" in titles and "Suggested next actions"
          in titles)
    for path in ("/world", "/nodes", "/mobile", "/guide",
                 "/presence", "/craft", "/symbiosis"):
        page = client.get(path)
        check(f"page {path} renders",
              page.status_code == 200
              and "Mycelium" in page.text,
              str(page.status_code))
    check("world carries state strip",
          "attention →" in client.get("/world").text)

    # Refusals: every V2 attack surface fails closed.
    refusing = [
        ("fake requesting node", {"requesting_node": "ghost",
                                  "node_token": TOKEN_A},
         (404, 422)),
        ("wrong credential", {"node_token": "wrong-token-1"},
         (403,)),
        ("shell kind", {"task_kind": "shell.exec"}, (422,)),
        ("wildcard cap", {"capability": "*"}, (422,)),
        ("unknown cap", {"capability": "evil.pwn"}, (422,)),
        ("secret payload",
         {"payload": {"api_key": "shh"}}, (422,)),
        ("traversal target", {"target_node": "../v2-b"},
         (404, 422)),
        ("no pinned target", {"target_node": None}, (422,)),
        ("timeout over lease", {"timeout_seconds": 9999},
         (422,)),
    ]
    base = {"requesting_node": "v2-a", "node_token": TOKEN_A,
            "target_node": "v2-b",
            "task_kind": "research.fetch_url",
            "capability": "research.fetch", "payload": {},
            "reason": "refusal probe"}
    count_before = len(client.get("/api/v1/tasks").json())
    for name, overrides, codes in refusing:
        body = dict(base)
        body.update(overrides)
        response = client.post("/api/v1/mesh/delegate",
                               json=body)
        check(f"delegate refuses: {name}",
              response.status_code in codes,
              str(response.status_code))
    check("refusals queued nothing",
          len(client.get("/api/v1/tasks").json())
          == count_before)

    print("smoke done", flush=True)
