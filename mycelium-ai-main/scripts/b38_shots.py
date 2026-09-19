"""Seed a tmp demo world for BIG #38 screenshots (real records only)."""

import os
import sys

# Default paths if not set
tmp = os.environ.get("B38_SHOT_TMP", r"C:\Users\Jelles\AppData\Local\Temp\b38_shots")
os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(tmp, "shots.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    tmp, "shots-chat.db")

# Import after setting env vars
from fastapi.testclient import TestClient
import coordinator.app.main as main_mod

CHAT = (
    "Jelles: We moeten de camperzonnepanelen schoonmaken voor de zomer.\n"
    "Claude: Goed plan. Ik zal eerst de opbrengst meten.\n"
    "Jelles: Welke reiniger is veilig voor panelen? Dat zoeken we nog uit.\n"
)

def main():
    with TestClient(main_mod.app) as client:
        # Register nodes
        node = client.post("/api/v1/nodes/register", json={
            "node_id": "workshop-laptop", "hostname": "workshop-laptop",
            "tier": "worker",
            "capabilities": ["research.fetch_url",
                             "analysis.summarize", "inventory.read"],
            "node_token": "screenshot-token-abcdef-123456"})
        print("node:", node.status_code)

        # Import conversation for intelligence
        imp = client.post("/api/v1/conversations/import", json={
            "title": "Zomerklus", "content": CHAT, "format": "plain",
            "source_platform": "claude"})
        print("import:", imp.status_code, imp.text[:200])
        if imp.status_code != 200:
            return 1
        cid = imp.json()["conversation_id"]

        # Analyze intelligence
        intel = client.post(f"/api/v1/conversations/{cid}/analyze")
        print("intel:", intel.status_code)

        # Materialize a research proposal
        intel2 = client.get(f"/api/v1/conversation-intel/{cid}").json()
        if intel2.get("research"):
            finger = intel2["research"][0]["fingerprint"]
            queued = client.post(
                f"/api/v1/conversation-intel/{cid}/materialize",
                json={"fingerprint": finger, "action": "research-queue"})
            print("research queued:", queued.status_code)

        # Create an automation run from template
        run = client.post("/api/v1/automation/from-template", json={
            "template_id": "intel_to_research",
            "args": {"goal": "Zomerklus automatisering",
                     "conversation_id": cid}})
        print("automation from template:", run.status_code)

        # Create a manual automation run with multiple steps
        run2 = client.post("/api/v1/automation/runs", json={
            "goal": "Zomerklus keten - observe -> research -> propose -> wait -> tick",
            "steps": [
                {"kind": "intel_analyze",
                 "params": {"conversation_id": cid}},
                {"kind": "research_queue",
                 "params": {"question": "Veilige paneelreiniger?",
                             "priority": "MEDIUM"}},
                {"kind": "knowledge_candidate",
                 "params": {"title": "Panelen schoonmaken",
                             "kind": "task",
                             "text": "Maak de camperpanelen schoon."}},
                {"kind": "symbiosis_propose",
                 "params": {"from_id": "obj_panel1",
                             "to_id": "proj_camper1",
                             "predicate": "related_to"}},
                {"kind": "mission_propose",
                 "params": {"goal": "Schoonmaakmissie",
                             "conversation_id": cid}},
                {"kind": "wait",
                 "params": {"reason": "plan YES first"}},
                {"kind": "mission_tick", "params": {}},
                {"kind": "notify",
                 "params": {"kind": "task_completed",
                             "title": "Zomerklus keten klaar"}},
            ]})
        print("automation manual:", run2.status_code)
        run_id2 = run2.json()["run_id"]

        # Drive it to waiting_for_human
        first = client.post(f"/api/v1/automation/runs/{run_id2}/drive",
                            json={"budget_steps": 10})
        print("first drive:", first.status_code, first.json().get("state"))

        # Approve the mission
        mission_id = client.get(
            f"/api/v1/automation/runs/{run_id2}").json()[
                "steps"][4]["result"]["mission_id"]
        approved = client.post(
            f"/api/v1/missions/{mission_id}/approve",
            json={"response": "YES", "decided_by": "screenshot"})
        print("mission approve:", approved.status_code)

        # Resume to completion
        resumed = client.post(
            f"/api/v1/automation/runs/{run_id2}/resume",
            json={"budget_steps": 10})
        print("resume:", resumed.status_code, resumed.json().get("state"))

        # Another run in running state (for screenshot variety)
        run3 = client.post("/api/v1/automation/runs", json={
            "goal": "Lopende observatie",
            "steps": [
                {"kind": "observe", "params": {"source": "missions"}},
                {"kind": "observe", "params": {"source": "candidates"}},
                {"kind": "readout", "params": {"source": "project"}},
            ]})
        print("running run:", run3.status_code)
        run_id3 = run3.json()["run_id"]
        client.post(f"/api/v1/automation/runs/{run_id3}/drive", json={"budget_steps": 10})

        # A failed run
        run4 = client.post("/api/v1/automation/runs", json={
            "goal": "Foutieve stap",
            "steps": [{"kind": "search", "params": {}}],
            "bounds": {"max_steps": 5, "max_runtime_seconds": 600,
                       "max_retries": 0, "max_consecutive_failures": 1}})
        print("failed run:", run4.status_code)
        run_id4 = run4.json()["run_id"]
        client.post(f"/api/v1/automation/runs/{run_id4}/drive", json={})

        # A cancelled run
        run5 = client.post("/api/v1/automation/runs", json={
            "goal": "Geannuleerd",
            "steps": [{"kind": "notify", "params": {"kind": "research_finding",
                                                     "title": "ping"}}]})
        print("cancelled run:", run5.status_code)
        run_id5 = run5.json()["run_id"]
        client.post(f"/api/v1/automation/runs/{run_id5}/cancel",
                    json={"reason": "operator stop"})

        print("seed done")
        return 0

if __name__ == "__main__":
    sys.exit(main())