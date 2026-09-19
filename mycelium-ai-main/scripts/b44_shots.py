"""Seed a tmp demo world for BIG #44 screenshots (real records only)."""

import os
import sys

tmp = os.environ.get("B44_SHOT_TMP",
                     r"C:\Users\Jelles\AppData\Local\Temp\b44_shots")
os.makedirs(tmp, exist_ok=True)
for name in ("shots.db", "shots-chat.db"):
    path = os.path.join(tmp, name)
    if os.path.exists(path):
        os.remove(path)
os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(tmp, "shots.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    tmp, "shots-chat.db")
os.environ["MYCELIUM_OPERATOR_KEY"] = "b44-shot-operator"

from fastapi.testclient import TestClient
import coordinator.app.main as main_mod


def main():
    with TestClient(main_mod.app) as client:
        node = client.post("/api/v1/nodes/register", json={
            "node_id": "atelier-laptop", "hostname": "atelier-laptop",
            "tier": "worker",
            "capabilities": ["research.fetch", "research.fetch_url",
                             "analysis.ollama", "inventory.read",
                             "camera.snapshot"],
            "node_token": "screenshot-token-abcdef-123456"})
        print("node laptop:", node.status_code)
        beat = client.post(
            "/api/v1/nodes/atelier-laptop/heartbeat", json={
                "available": True,
                "node_token": "screenshot-token-abcdef-123456",
                "telemetry": {
                    "hostname": "atelier-laptop", "os": "Linux",
                    "cpu_percent": 28.0, "cpu_count": 8,
                    "memory_percent": 52.0,
                    "memory_total_mb": 16384,
                    "memory_available_mb": 7864,
                    "uptime_seconds": 90000},
                "hardware": [
                    {"kind": "gpu",
                     "identifier": "NVIDIA RTX 3060",
                     "details": {"vendor": "nvidia"},
                     "status": "connected"},
                    {"kind": "camera",
                     "identifier": "/dev/video0",
                     "details": {"subsystem": "v4l2"},
                     "status": "connected"}],
                "compute_capabilities": [
                    {"capability": "ollama",
                     "details": {"models": ["llama3"]},
                     "status": "available"}],
                "energy_state": {"source": "grid"}})
        print("heartbeat laptop:", beat.status_code)

        from coordinator.app.database import connection
        with connection() as db:
            db.execute(
                "INSERT INTO nodes (node_id, hostname, tier, "
                "capabilities, cpu_cores, memory_mb, "
                "energy_source, last_seen, status) VALUES (?, "
                "?, ?, ?, ?, ?, ?, ?, ?)",
                ("zolder-pi", "zolder-pi", "seed",
                 '["camera.snapshot"]', 4, 4096, "battery",
                 "2020-01-01T00:00:00+00:00", "offline"))
        print("node pi offline: seeded")

        gpu = client.post("/api/v1/hardware/links", json={
            "human_ref": "jelles", "node_id": "atelier-laptop",
            "device_ref": "NVIDIA RTX 3060", "device_kind": "gpu",
            "capability": "analysis.ollama",
            "evidence": "saw the card in the case"}).json()
        client.post(
            f"/api/v1/hardware/links/{gpu['link_id']}/verify",
            json={"verified_by": "jelles",
                  "operator_key": "b44-shot-operator"})
        print("gpu verified")

        fin = client.post("/api/v1/finance/records", json={
            "kind": "budget", "title": "Solar upgrade pot",
            "amount_minor": 50000, "currency": "EUR",
            "project_ref": "proj_zolder",
            "recorded_by": "jelles"}).json()
        client.post(
            f"/api/v1/finance/records/{fin['record_id']}/status",
            json={"status": "CONFIRMED"})
        enr = client.post("/api/v1/energy/records", json={
            "source": "solar", "kind": "production",
            "value": 410.5, "unit": "W",
            "project_ref": "proj_zolder"}).json()
        bat = client.post("/api/v1/energy/records", json={
            "source": "battery", "kind": "storage",
            "value": 78.0, "unit": "%",
            "project_ref": "proj_zolder"}).json()
        print("finance+energy recorded")

        quest_ids = []
        for title, steps in (
                ("Understand current energy", [
                    {"key": "money", "label": "Budget secured",
                     "kind": "finance",
                     "ref": fin["record_id"]}]),
                ("Inspect available hardware", [
                    {"key": "gpu", "label": "GPU verified",
                     "kind": "hardware",
                     "ref": gpu["link_id"]}]),
                ("Research solar upgrade", [
                    {"key": "panels", "label": "Panels producing",
                     "kind": "energy", "ref": enr["record_id"]}]),
                ("Store the harvest", [
                    {"key": "battery", "label": "Battery holds",
                     "kind": "energy", "ref": bat["record_id"]}]),
                ("Gather materials", [
                    {"key": "mount", "label": "Roof mounting",
                     "kind": "note", "ref": ""}]),):
            quest = client.post("/api/v1/quests", json={
                "title": title, "steps": steps}).json()
            quest_ids.append(quest["quest_id"])
        campaign = client.post("/api/v1/campaigns", json={
            "title": "Solar Grove",
            "description": "Grow the atelier into a solar "
                           "workshop, one real record at a time.",
            "quest_ids": quest_ids}).json()
        print("campaign:", campaign["campaign_id"],
              campaign["completed_count"],
              "/", campaign["total_count"])

        proposal = client.post("/api/v1/candidates", json={
            "title": "Solar panels power the zolder project",
            "candidate_type": "connection",
            "summary": "energy feeds the workshop",
            "entity_refs": ["proj_zolder", "enr_solar"]})
        print("symbiosis candidate:", proposal.status_code)
        chat = client.post(
            "/api/v1/chat",
            json={"message": "richt de zolderwerkplaats in"}).json()
        mission = client.post("/api/v1/missions", json={
            "conversation_id": chat["conversation_id"],
            "goal": "Zolderwerkplaats inrichten",
            "steps": [{"kind": "readout",
                       "description": "Read status",
                       "parameters": {"source": "project"}}]})
        print("mission:", mission.status_code)

        print("seed done")
        return 0


if __name__ == "__main__":
    sys.exit(main())
