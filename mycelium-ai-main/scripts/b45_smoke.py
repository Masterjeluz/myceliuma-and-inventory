"""BIG #45 live smoke: living ecosystem connections on tmp DBs.

Proves with real localhost HTTP (TestClient, no mocks):
project→project relation (shared record cross-link),
project→machine (hardware), project→energy, project→finance,
project→research, project→campaign, project→node,
symbiosis (seedling), craft, presence, guide, world,
mobile — plus refusal probes. No invented relations.
"""

import os
import sys

tmp = os.environ.get("B45_SMOKE_TMP", "")
assert tmp, "B45_SMOKE_TMP required"
os.makedirs(tmp, exist_ok=True)
for name in ("smoke.db", "smoke-chat.db"):
    path = os.path.join(tmp, name)
    if os.path.exists(path):
        os.remove(path)
        print(f"cleared stale {name}", flush=True)
os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(tmp, "smoke.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    tmp, "smoke-chat.db")
os.environ["MYCELIUM_OPERATOR_KEY"] = "b45-smoke-operator"

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

TOKEN_A = "b45-smoke-token-aaaaaaaa"
TOKEN_B = "b45-smoke-token-bbbbbbbb"
OPERATOR = "b45-smoke-operator"

checks = []


def check(name, ok, detail=""):
    line = f"{'OK  ' if ok else 'FAIL'} {name} {detail}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"),
              flush=True)
    checks.append(bool(ok))
    if not ok:
        sys.exit(1)


with TestClient(main_mod.app) as client:
    for node_id, caps, token in (
            ("mesh-a", ["research.fetch"], TOKEN_A),
            ("mesh-b", ["research.fetch", "research.fetch_url"],
             TOKEN_B)):
        reg = client.post("/api/v1/nodes/register", json={
            "node_id": node_id, "hostname": node_id,
            "tier": "worker", "capabilities": caps,
            "node_token": token})
        check(f"node {node_id} registered",
              reg.status_code == 201, str(reg.status_code))
    beat = client.post("/api/v1/nodes/mesh-b/heartbeat", json={
        "available": True, "node_token": TOKEN_B,
        "telemetry": {"cpu_percent": 22.0},
        "hardware": [{"kind": "gpu", "identifier": "gpu-0",
                      "details": {}, "status": "connected"}]})
    check("telemetry heartbeat", beat.status_code == 204,
          str(beat.status_code))

    link = client.post("/api/v1/hardware/links", json={
        "human_ref": "jelles", "node_id": "mesh-b",
        "device_ref": "gpu-0", "device_kind": "gpu",
        "evidence": "saw it"}).json()
    check("link verified", client.post(
        f"/api/v1/hardware/links/{link['link_id']}/verify",
        json={"verified_by": "jelles",
              "operator_key": OPERATOR}).status_code == 200)
    fin = client.post("/api/v1/finance/records", json={
        "kind": "budget", "title": "Solar pot",
        "amount_minor": 50000,
        "project_ref": "proj_solar"}).json()
    enr = client.post("/api/v1/energy/records", json={
        "source": "solar", "kind": "production", "value": 410.5,
        "unit": "W", "project_ref": "proj_solar"}).json()
    quest = client.post("/api/v1/quests", json={
        "title": "Fund it",
        "steps": [{"key": "m", "label": "Budget",
                   "kind": "finance",
                   "ref": fin["record_id"]},
                  {"key": "p", "label": "Panel",
                   "kind": "entity", "ref": "obj_panel"},
                  {"key": "s", "label": "Solar scope",
                   "kind": "entity", "ref": "proj_solar"}]}
    ).json()
    campaign = client.post("/api/v1/campaigns", json={
        "title": "Solar Grove",
        "quest_ids": [quest["quest_id"]]}).json()
    proposal = client.post("/api/v1/candidates", json={
        "title": "Panels feed the project",
        "candidate_type": "connection",
        "summary": "energy link",
        "entity_refs": ["proj_solar", "obj_panel"]})
    check("seedling proposed", proposal.status_code == 201)

    # project → X for every domain.
    conns = client.get(
        "/api/v1/connections",
        params={"entity_id": "proj_solar"}).json()
    origins = {entry["origin"] for entry in
               conns["connections"]}
    for origin in ("finance-link", "energy-link",
                   "symbiosis-proposal", "quest-step",
                   "campaign-chain"):
        check(f"project→{origin}", origin in origins,
              str(sorted(origins)))
    check("no leaked amounts",
          "50000" not in str(conns["connections"]))

    # project → research (run naming the project).
    run = client.post("/api/v1/research/queue", json={
        "question": "Which panels for proj_solar?",
        "project_ref": "proj_solar"})
    check("research queued", run.status_code in (200, 201),
          str(run.status_code))
    conns2 = client.get(
        "/api/v1/connections",
        params={"entity_id": "proj_solar"}).json()
    origins2 = {entry["origin"] for entry in
                conns2["connections"]}
    check("project→research-run", "research-run" in origins2,
          str(sorted(origins2)))

    # project → node (task association, no ownership).
    dispatch = client.post("/api/v1/mesh/delegate", json={
        "requesting_node": "mesh-a", "node_token": TOKEN_A,
        "target_node": "mesh-b",
        "task_kind": "research.fetch_url",
        "capability": "research.fetch",
        "payload": {"url": "https://example.com/panel"},
        "reason": "smoke"})
    check("delegated", dispatch.status_code == 201,
          str(dispatch.status_code))
    # Delegation only pins the task (queued); the target
    # must still pull/claim it before WORKING is real.
    claim = client.post(
        "/api/v1/tasks/claim/mesh-b",
        params={"node_token": TOKEN_B})
    check("claimed", claim.status_code == 200,
          str(claim.status_code))
    node_conns = client.get(
        "/api/v1/connections",
        params={"entity_id": "mesh-b"}).json()
    node_origins = {entry["origin"] for entry in
                    node_conns["connections"]}
    check("node WORKING association",
          "node-task" in node_origins, str(sorted(node_origins)))
    working = next(
        entry for entry in node_conns["connections"]
        if entry["origin"] == "node-task")
    check("no ownership implied",
          "never owned" in working["detail"])

    # project → project via shared record.
    quest2 = client.post("/api/v1/quests", json={
        "title": "Mount it",
        "steps": [{"key": "p", "label": "Panel",
                   "kind": "entity", "ref": "obj_panel"}]})
    check("second quest", quest2.status_code == 201)
    network = client.get(
        "/api/v1/connections/network",
        params={"projects": "proj_solar,proj_hydro"}).json()
    check("network clusters",
          len(network["clusters"]) == 2)
    check("network honesty", "honesty" in network)

    # project → machine (hardware link device side).
    hw_conns = client.get(
        "/api/v1/connections",
        params={"entity_id": "gpu-0"}).json()
    check("machine link visible",
          any(entry["origin"] == "hardware-link"
              for entry in hw_conns["connections"]))

    # Detail page vocabulary.
    detail = client.get(
        "/api/v1/connections/detail",
        params={"a": "proj_solar",
                "b": fin["record_id"]}).json()
    for key in ("what", "why", "source", "status",
                "evidence", "next"):
        check(f"detail has {key}", key in detail)
    page = client.get(
        "/connections",
        params={"a": "proj_solar", "b": fin["record_id"]})
    check("detail page", page.status_code == 200 and
          "EVIDENCE" in page.text)

    # Campaign ecosystem context.
    eco = client.get(
        f"/api/v1/connections/campaign/"
        f"{campaign['campaign_id']}").json()
    check("campaign ecosystem",
          "FINANCE" in eco["groups"])

    # World / guide / mobile / morning / presence.
    world = client.get(
        "/world", params={"entity_id": "proj_solar"})
    check("world connections panel",
          world.status_code == 200 and
          "Ecosystem connections" in world.text)
    guide = client.get("/api/v1/guide").json()
    check("guide relationship card",
          any("Possible connection" in item.get("what", "")
              for item in guide.get("items", [])))
    dash = client.get("/api/v1/mobile/dashboard").json()
    check("mobile connected panel", "connected" in dash)
    morning = client.get("/api/v1/reports/morning").json()
    check("morning connections section",
          "Ecosystem connections" in [
              section["title"] for section in
              morning.get("sections", [])])
    from coordinator.app.presence import attention_items
    check("presence symbiosis item",
          "symbiosis_proposed" in {
              item["type"] for item in attention_items()})

    # Refusals.
    check("fake source 422", client.get(
        "/api/v1/connections/detail",
        params={"a": "ghost-xyz",
                "b": fin["record_id"]}).status_code == 422)
    check("fake predicate path 422", client.get(
        "/api/v1/connections",
        params={"entity_id": "fin_*"}).status_code == 422)
    check("fake campaign 422", client.get(
        f"/api/v1/connections/campaign/cmp_nope"
    ).status_code == 422)
    check("empty network 422", client.get(
        "/api/v1/connections/network",
        params={"projects": ""}).status_code == 422)
    check("self-link 422", client.get(
        "/api/v1/connections/detail",
        params={"a": "proj_solar",
                "b": "proj_solar"}).status_code == 422)
    wild = client.post("/api/v1/campaigns", json={
        "title": "x", "quest_ids": ["qst_*"]})
    check("wildcard refused", wild.status_code == 422,
          str(wild.status_code))
    traversal = client.get("/api/v1/campaigns/../secret")
    check("traversal refused",
          traversal.status_code in (404, 422),
          str(traversal.status_code))
    dupe = client.post("/api/v1/campaigns", json={
        "title": "x",
        "quest_ids": [quest["quest_id"],
                      quest["quest_id"]]})
    check("duplicate refused", dupe.status_code == 422,
          str(dupe.status_code))
    secret = client.post("/api/v1/mesh/delegate", json={
        "requesting_node": "mesh-a", "node_token": TOKEN_A,
        "target_node": "mesh-b",
        "task_kind": "research.fetch_url",
        "capability": "research.fetch",
        "payload": {"api_key": "hunter2"}})
    check("secret refused", secret.status_code == 422,
          str(secret.status_code))

print(f"SMOKE DONE: {sum(checks)}/{len(checks)} checks green",
      flush=True)
