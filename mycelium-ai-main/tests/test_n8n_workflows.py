"""BIG #18: n8n workflow artifacts are safe to commit.

Committed workflows must stay secret-free, localhost-only,
key-injected via env, and limited to known jobs/labels —
so importing them into a real n8n instance cannot leak or
execute anything unexpected.
"""

import json
import pathlib
import re

N8N_DIR = pathlib.Path(__file__).resolve().parent.parent / "n8n"

WORKFLOWS = [
    "workflow-a-schedule-morning-report.json",
    "workflow-b-outbox-notify.json",
]

KNOWN_JOBS = {
    "watcher_scan",
    "memory_consolidation",
    "morning_report",
    "health_import",
    "research_process",
    "skill_discover",
    "inventory_reconcile",
    "device_health",
}

KNOWN_TARGETS = {"notify"}


def load(name):
    return json.loads((N8N_DIR / name).read_text(encoding="utf-8"))


def string_values(node):
    found = []

    def walk(value):
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(node)
    return found


def test_workflows_parse_and_link():
    for name in WORKFLOWS:
        flow = load(name)
        assert flow["name"]
        assert flow["active"] is False
        names = {node["name"] for node in flow["nodes"]}
        for node in flow["nodes"]:
            for key in ("id", "name", "type", "typeVersion",
                        "position", "parameters"):
                assert key in node, (name, node.get("name"))
        for source, outputs in flow["connections"].items():
            assert source in names, (name, source)
            for branch in outputs["main"]:
                for link in branch:
                    assert link["node"] in names, (name, link)


def test_workflows_localhost_only_and_secret_free():
    for name in WORKFLOWS:
        flow = load(name)
        blob = json.dumps(flow)
        assert not re.search(r"\b[0-9a-f]{64}\b", blob), name
        assert "sk-" not in blob, name
        for value in string_values(flow):
            lowered = value.lower()
            if "http://" in lowered or "https://" in lowered:
                assert "127.0.0.1" in value, (name, value)
                assert "tunnel" not in lowered, (name, value)
            assert "password" not in lowered, (name, value)
            assert "passwd" not in lowered, (name, value)
            assert "private_key" not in lowered, (name, value)
            assert "refresh_token" not in lowered, (name, value)


def test_workflow_a_triggers_one_known_job():
    flow = load(WORKFLOWS[0])
    by_name = {node["name"]: node for node in flow["nodes"]}
    assert "Schedule Trigger" in by_name
    http = by_name["Trigger Morning Report"]
    assert http["parameters"]["method"] == "POST"
    body = http["parameters"]["jsonBody"]
    assert '"job_name": "morning_report"' in body
    assert "$env.MYCELIUM_N8N_KEY" in body or any(
        "$env.MYCELIUM_N8N_KEY" in value
        for value in string_values(http))
    for banned in ("command", "shell", "code", "exec",
                   "arbitrary"):
        assert banned not in body.lower(), banned
    headers = http["parameters"]["headerParameters"][
        "parameters"]
    assert any(item["name"] == "X-Integration-Key" and
               "$env.MYCELIUM_N8N_KEY" in item["value"]
               for item in headers)


def test_workflow_b_outbox_loop_is_closed():
    flow = load(WORKFLOWS[1])
    by_name = {node["name"]: node for node in flow["nodes"]}
    for required in ("Schedule Trigger", "Poll Outbox",
                     "Has Pending Items", "Loop Over Outbox",
                     "Test Notification Log", "Ack Delivery"):
        assert required in by_name, required
    # Empty outbox ends at the IF node; items loop back.
    loop_links = flow["connections"]["Loop Over Outbox"][
        "main"]
    assert loop_links[0] == []
    assert [link["node"] for link in loop_links[1]] == [
        "Test Notification Log"]
    assert flow["connections"]["Ack Delivery"]["main"] == [
        [{"node": "Loop Over Outbox", "type": "main",
          "index": 0}]]
    # No external messaging: the only sink is a local log.
    assert not any("smtp" in node["type"].lower() or
                   "discord" in node["type"].lower() or
                   "slack" in node["type"].lower() or
                   "emailSend" in node["type"]
                   for node in flow["nodes"])
