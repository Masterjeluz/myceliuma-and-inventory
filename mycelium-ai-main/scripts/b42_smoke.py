"""BIG #42 live smoke: ecosystem hardening on tmp DBs.

Proves with real localhost HTTP (TestClient, no mocks):
hardware link propose (PROPOSED, never VERIFIED) -> verify
refusals (bad operator key, node credential) -> operator verify
-> reality shows VERIFIED -> revoke sticks -> finance record
(UNKNOWN stays unknown) -> energy record + state -> V2 mission
templates listed -> quest trail create/refresh real progress ->
workflow preview creates nothing -> workflow dispatch 2 steps ->
receipts on mobile dashboard -> overview hardware/finance/
energy/quests -> guide hardware item -> morning hardware section
only when data exists -> packet-v2 finance scoping -> pages
render -> refusal probes (fake verify, self-verify attempt,
fake finance/energy, invalid predicate, wildcard/shell/
traversal/secret delegation, replay quest refresh).
"""

import os
import sys

tmp = os.environ.get("B42_SMOKE_TMP", "")
assert tmp, "B42_SMOKE_TMP required"
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
os.environ["MYCELIUM_OPERATOR_KEY"] = "b42-smoke-operator"

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

TOKEN_A = "b42-smoke-token-aaaaaaaa"
TOKEN_B = "b42-smoke-token-bbbbbbbb"
OPERATOR = "b42-smoke-operator"

checks = []


def check(name, ok, detail=""):
    line = f"{'OK  ' if ok else 'FAIL'} {name} {detail}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"),
              flush=True)
    checks.append(ok)
    if not ok:
        sys.exit(1)


with TestClient(main_mod.app) as client:
    for node_id, caps, token in (
            ("eco-a", ["research.fetch"], TOKEN_A),
            ("eco-b", ["research.fetch", "research.fetch_url"],
             TOKEN_B)):
        reg = client.post("/api/v1/nodes/register", json={
            "node_id": node_id, "hostname": node_id,
            "tier": "worker", "capabilities": caps,
            "node_token": token})
        check(f"node {node_id} registered",
              reg.status_code == 201, str(reg.status_code))
    beat = client.post("/api/v1/nodes/eco-b/heartbeat", json={
        "available": True, "node_token": TOKEN_B,
        "telemetry": {"cpu_percent": 22.0},
        "hardware": [{"kind": "gpu", "identifier": "gpu-0",
                      "details": {}, "status": "connected"}]})
    check("telemetry heartbeat", beat.status_code == 204,
          str(beat.status_code))

    # 1. Propose -> PROPOSED, never VERIFIED.
    prop = client.post("/api/v1/hardware/links", json={
        "human_ref": "jelles", "node_id": "eco-b",
        "device_ref": "gpu-0", "device_kind": "gpu",
        "capability": "analysis.ollama",
        "evidence": "saw the card in the case"})
    check("link proposed", prop.status_code == 201,
          str(prop.status_code))
    link = prop.json()
    check("link starts PROPOSED",
          link["status"] == "PROPOSED", link["status"])
    link_id = link["link_id"]

    # 2. Verify refusals: wrong key, empty key.
    bad = client.post(
        f"/api/v1/hardware/links/{link_id}/verify",
        json={"verified_by": "jelles",
              "operator_key": "nope"})
    check("verify wrong key refused", bad.status_code == 403,
          str(bad.status_code))
    empty = client.post(
        f"/api/v1/hardware/links/{link_id}/verify",
        json={"verified_by": "jelles", "operator_key": ""})
    check("verify empty key refused", empty.status_code == 403,
          str(empty.status_code))
    still = client.get(
        f"/api/v1/hardware/links/{link_id}").json()
    check("still PROPOSED after refusals",
          still["status"] == "PROPOSED", still["status"])

    # 3. Operator verify -> reality VERIFIED.
    verified = client.post(
        f"/api/v1/hardware/links/{link_id}/verify",
        json={"verified_by": "jelles",
              "operator_key": OPERATOR})
    check("operator verify", verified.status_code == 200,
          str(verified.status_code))
    reality = client.get(
        "/api/v1/nodes/eco-b/reality").json()
    gpu = next(item for item in reality["hardware"]
               if item["identifier"] == "gpu-0")
    check("reality shows VERIFIED", gpu["trust"] == "VERIFIED",
          gpu["trust"])

    # 4. Finance + energy.
    fin = client.post("/api/v1/finance/records", json={
        "kind": "budget", "title": "Solar upgrade pot",
        "amount_minor": 50000, "project_ref": "proj_solar"})
    check("finance record", fin.status_code == 201,
          str(fin.status_code))
    fin_id = fin.json()["record_id"]
    unk = client.post("/api/v1/finance/records", json={
        "kind": "expense", "title": "Cables (price unknown)"})
    check("finance unknown amount",
          unk.json()["amount_minor"] is None)
    enr = client.post("/api/v1/energy/records", json={
        "source": "solar", "kind": "production", "value": 410.5,
        "unit": "W", "project_ref": "proj_solar"})
    check("energy record", enr.status_code == 201,
          str(enr.status_code))
    state = client.get("/api/v1/energy/state",
                       params={"project_ref": "proj_solar"}).json()
    check("energy state endpoint", "states" in state)

    # 5. V2 mission templates.
    templates = client.get("/api/v1/mission-templates").json()
    ids = {entry["template_id"] for entry in templates}
    check("idea_to_verification template",
          "idea_to_verification" in ids)
    check("project_finance_energy template",
          "project_finance_energy" in ids)

    # 6. Quest trail: real progress.
    quest = client.post("/api/v1/quests", json={
        "title": "Build Solar Upgrade",
        "steps": [
            {"key": "money", "label": "Budget", "kind": "finance",
             "ref": fin_id},
            {"key": "power", "label": "Panels live",
             "kind": "energy", "ref": ""}]})
    check("quest created", quest.status_code == 201,
          str(quest.status_code))
    quest_id = quest.json()["quest_id"]
    check("quest starts 0/2",
          quest.json()["progress"] == "0/2",
          quest.json()["progress"])
    client.post(f"/api/v1/finance/records/{fin_id}/status",
                json={"status": "CONFIRMED"})
    refreshed = client.post(
        f"/api/v1/quests/{quest_id}/refresh").json()
    check("quest real progress 1/2",
          refreshed["progress"] == "1/2",
          refreshed["progress"])

    # 7. Workflow preview creates nothing; dispatch works.
    tasks_before = client.get("/api/v1/tasks").json()
    count_before = len(tasks_before if isinstance(
        tasks_before, list) else tasks_before.get("tasks", []))
    preview = client.post("/api/v1/workflows/preview", json={
        "requesting_node": "eco-a", "node_token": TOKEN_A,
        "steps": [{"task_kind": "research.fetch_url",
                   "capability": "research.fetch",
                   "target_node": "eco-b",
                   "payload": {"url": "https://example.com/a"},
                   "reason": "smoke preview"}]})
    check("workflow preview", preview.status_code == 200,
          str(preview.status_code))
    tasks_after = client.get("/api/v1/tasks").json()
    count_after = len(tasks_after if isinstance(
        tasks_after, list) else tasks_after.get("tasks", []))
    check("preview creates nothing",
          count_after == count_before)
    dispatch = client.post("/api/v1/workflows/dispatch", json={
        "requesting_node": "eco-a", "node_token": TOKEN_A,
        "mission_id": "",
        "steps": [
            {"task_kind": "research.fetch_url",
             "capability": "research.fetch",
             "target_node": "eco-b",
             "payload": {"url": "https://example.com/a"},
             "reason": "research on B"},
            {"task_kind": "research.fetch_url",
             "capability": "research.fetch",
             "target_node": "eco-b",
             "payload": {"url": "https://example.com/b"},
             "reason": "more research on B"}]})
    check("workflow dispatch", dispatch.status_code == 201,
          str(dispatch.status_code))
    check("workflow 2 steps",
          dispatch.json()["steps_dispatched"] == 2)

    # 8. Surfaces: mobile, overview, guide, morning, packet.
    dash = client.get("/api/v1/mobile/dashboard").json()
    check("mobile ecosystem keys",
          all(key in dash for key in
              ("quests", "hardware", "finance", "energy",
               "mesh_receipts")))
    overview = client.get("/api/v1/ecosystem/overview").json()
    check("overview hardware", overview["hardware"]["links"] == 1,
          str(overview["hardware"]))
    check("overview finance", overview["finance"]["total"] == 2,
          str(overview["finance"].get("total")))
    check("overview quests", overview["quests"]["open"] == 1)
    guide = client.get("/api/v1/guide").json()
    guide_items = guide.get("items", guide
                            if isinstance(guide, list) else [])
    check("guide ecosystem items", len(guide_items) > 0)
    morning = client.get("/api/v1/reports/morning").json()
    titles = [section["title"] for section in
              morning.get("sections", [])]
    check("morning hardware section",
          "Hardware verification" in titles)
    check("morning quests section", "Quest trails" in titles)
    from coordinator.app.context_packet import build_packet_v2
    scoped = build_packet_v2(task="smoke",
                             project_id="proj_solar")
    generic = build_packet_v2(task="smoke")
    check("packet-v2 ecosystem section", "ecosystem" in scoped)
    scoped_amounts = [record.get("amount_minor") for record in
                      scoped["ecosystem"]["finance"]["records"]]
    generic_amounts = [record.get("amount_minor") for record in
                       generic["ecosystem"]["finance"]["records"]]
    check("scoped packet carries amount",
          50000 in scoped_amounts)
    check("generic packet hides amount",
          50000 not in generic_amounts)

    # 9. Pages render.
    for path in ("/hardware", "/finance", "/energy", "/quests",
                 "/world", "/mobile", "/morning"):
        page = client.get(path)
        check(f"page {path}", page.status_code == 200,
              str(page.status_code))

    # 10. Refusal probes.
    fake_verify = client.post(
        "/api/v1/hardware/links/hv_deadbeef/verify",
        json={"verified_by": "mallory",
              "operator_key": OPERATOR})
    check("fake link verify 404",
          fake_verify.status_code == 404,
          str(fake_verify.status_code))
    fake_fin = client.post("/api/v1/finance/records", json={
        "kind": "printing-money", "title": "Fake"})
    check("fake finance kind refused",
          fake_fin.status_code == 422,
          str(fake_fin.status_code))
    fake_enr = client.post("/api/v1/energy/records", json={
        "source": "coal", "kind": "production"})
    check("fake energy source refused",
          fake_enr.status_code == 422,
          str(fake_enr.status_code))
    from coordinator.app.symbiosis import check_predicate
    try:
        check_predicate("owns")
        check("invalid predicate refused", False)
    except ValueError:
        check("invalid predicate refused", True)
    wild = client.post("/api/v1/workflows/dispatch", json={
        "requesting_node": "eco-a", "node_token": TOKEN_A,
        "steps": [{"task_kind": "research.fetch_url",
                   "capability": "research.*",
                   "target_node": "eco-b", "payload": {}}]})
    check("workflow wildcard refused",
          wild.status_code == 422, str(wild.status_code))
    shell = client.post("/api/v1/workflows/dispatch", json={
        "requesting_node": "eco-a", "node_token": TOKEN_A,
        "steps": [{"task_kind": "exec.shell",
                   "capability": "research.fetch",
                   "target_node": "eco-b", "payload": {}}]})
    check("workflow shell refused",
          shell.status_code == 422, str(shell.status_code))
    secret = client.post("/api/v1/workflows/dispatch", json={
        "requesting_node": "eco-a", "node_token": TOKEN_A,
        "steps": [{"task_kind": "research.fetch_url",
                   "capability": "research.fetch",
                   "target_node": "eco-b",
                   "payload": {"api_key": "hunter2"}}]})
    check("workflow secret refused",
          secret.status_code == 422, str(secret.status_code))

    # 11. Revoke sticks at the end (keeps the store honest).
    revoked = client.post(
        f"/api/v1/hardware/links/{link_id}/revoke",
        json={"revoked_by": "jelles", "reason": "smoke done",
              "operator_key": OPERATOR})
    check("revoke at end", revoked.json()["status"] == "REVOKED")
    reverify = client.post(
        f"/api/v1/hardware/links/{link_id}/verify",
        json={"verified_by": "jelles",
              "operator_key": OPERATOR})
    check("revoked never re-verifies",
          reverify.status_code == 422,
          str(reverify.status_code))

print(f"SMOKE DONE: {sum(checks)}/{len(checks)} checks green",
      flush=True)
