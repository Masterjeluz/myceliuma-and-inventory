"""Seed a tmp demo world for BIG #45 screenshots (real records only).

Creates two nodes, a verified hardware link, finance + energy
records on proj_solar, quests + campaign, a symbiosis
candidate, and a second project sharing one record (for
cross-links). Writes entity ids to shots_ids.json for the
screenshot script. No real DBs touched.
"""

import json
import os
import sys

tmp = os.environ.get("B45_SHOT_TMP",
                     r"C:\Users\Jelles\AppData\Local\Temp\b45_shots")
os.makedirs(tmp, exist_ok=True)
for name in ("shots.db", "shots-chat.db"):
    path = os.path.join(tmp, name)
    if os.path.exists(path):
        os.remove(path)
os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(tmp, "shots.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    tmp, "shots-chat.db")
os.environ["MYCELIUM_OPERATOR_KEY"] = "b45-shot-operator"

from fastapi.testclient import TestClient
import coordinator.app.main as main_mod

TOKEN_A = "b45-shot-token-aaaaaaaa"
TOKEN_B = "b45-shot-token-bbbbbbbb"
OPERATOR = "b45-shot-operator"

ids: dict = {}


def main() -> int:
    with TestClient(main_mod.app) as client:
        for node_id, caps, token in (
                ("atelier-laptop",
                 ["research.fetch", "research.fetch_url",
                  "analysis.ollama", "inventory.read"],
                 TOKEN_A),
                ("zolder-pi",
                 ["camera.snapshot", "research.fetch"], TOKEN_B)):
            response = client.post("/api/v1/nodes/register", json={
                "node_id": node_id, "hostname": node_id,
                "tier": "worker", "capabilities": caps,
                "node_token": token})
            print(node_id, response.status_code)
        beat = client.post(
            "/api/v1/nodes/atelier-laptop/heartbeat", json={
                "available": True, "node_token": TOKEN_A,
                "telemetry": {"cpu_percent": 28.0},
                "hardware": [{"kind": "gpu",
                              "identifier": "RTX 3060",
                              "details": {}, "status": "connected"}]})
        print("heartbeat:", beat.status_code)

        link = client.post("/api/v1/hardware/links", json={
            "human_ref": "jelles", "node_id": "atelier-laptop",
            "device_ref": "RTX 3060", "device_kind": "gpu",
            "evidence": "saw the card in the case"}).json()
        client.post(
            f"/api/v1/hardware/links/{link['link_id']}/verify",
            json={"verified_by": "jelles",
                  "operator_key": OPERATOR})
        print("gpu verified:", link["link_id"])

        fin = client.post("/api/v1/finance/records", json={
            "kind": "budget", "title": "Solar upgrade pot",
            "amount_minor": 50000, "currency": "EUR",
            "project_ref": "proj_solar",
            "recorded_by": "jelles"}).json()
        enr = client.post("/api/v1/energy/records", json={
            "source": "solar", "kind": "production",
            "value": 410.5, "unit": "W",
            "project_ref": "proj_solar"}).json()
        print("finance+energy recorded")

        quest = client.post("/api/v1/quests", json={
            "title": "Fund the panels",
            "steps": [
                {"key": "m", "label": "Budget secured",
                 "kind": "finance", "ref": fin["record_id"]},
                {"key": "p", "label": "Panel hardware",
                 "kind": "entity", "ref": "obj_panel"},
                {"key": "s", "label": "Solar scope",
                 "kind": "entity", "ref": "proj_solar"}]}).json()
        quest2 = client.post("/api/v1/quests", json={
            "title": "Mount the panels",
            "steps": [{"key": "p", "label": "Panel hardware",
                       "kind": "entity", "ref": "obj_panel"},
                      {"key": "h", "label": "Hydro scope",
                       "kind": "entity",
                       "ref": "proj_hydro"}]}).json()
        campaign = client.post("/api/v1/campaigns", json={
            "title": "Solar Grove",
            "description": "Grow the atelier into a solar "
                           "workshop, one real record at a time.",
            "quest_ids": [quest["quest_id"]]}).json()
        print("campaign:", campaign["campaign_id"])

        proposal = client.post("/api/v1/candidates", json={
            "title": "Panels feed the solar project",
            "candidate_type": "connection",
            "summary": "energy link",
            "entity_refs": ["proj_solar", "obj_panel"]})
        print("candidate:", proposal.status_code)

        dispatch = client.post("/api/v1/mesh/delegate", json={
            "requesting_node": "zolder-pi",
            "node_token": TOKEN_B,
            "target_node": "atelier-laptop",
            "task_kind": "research.fetch_url",
            "capability": "research.fetch",
            "payload": {"url": "https://example.com/panel"},
            "reason": "shots"})
        print("delegate:", dispatch.status_code)
        claim = client.post("/api/v1/tasks/claim/atelier-laptop",
                            params={"node_token": TOKEN_A})
        print("claim:", claim.status_code)

        ids.update({
            "fin": fin["record_id"],
            "enr": enr["record_id"],
            "quest": quest["quest_id"],
            "quest2": quest2["quest_id"],
            "campaign": campaign["campaign_id"],
            "link": link["link_id"],
        })
        with open(os.path.join(tmp, "shots_ids.json"), "w",
                   encoding="utf-8") as handle:
            json.dump(ids, handle)
        print("seed done:", ids)
        return 0


if __name__ == "__main__":
    sys.exit(main())
