"""Mission template tests (BIG #4, §21).

Catalogue, instantiation, validation through the real mission
gates (templates bypass nothing), and the HTTP endpoints.
"""

import os

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.mission_templates import (
    TEMPLATES,
    get_template,
    instantiate,
    list_templates,
)
from coordinator.app.missions import new_mission


def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH", str(tmp_path / "t-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def make_conversation(test_client):
    return test_client.post("/api/v1/chat", json={
        "message": "hallo"}).json()["conversation_id"]


def test_catalogue_has_five_safe_templates():
    # BIG #42 adds two V2 chain templates (idea_to_verification,
    # project_finance_energy); the safety properties below cover
    # all templates, old and new.
    assert len(list_templates()) == 8
    ids = {template["template_id"] for template in list_templates()}
    assert ids == {"inspect_project", "investigate_inventory",
                   "analyze_problem", "prepare_build_plan",
                   "inspect_desktop_project", "research_topic",
                   "idea_to_verification",
                   "project_finance_energy"}
    for template in TEMPLATES:
        assert template["steps"], template["template_id"]


def test_templates_contain_no_input_steps():
    from coordinator.app.computer_actions import approval_required_for
    for template in TEMPLATES:
        for step in template["steps"]:
            if step["kind"] == "desktop":
                assert approval_required_for(
                    step["action_type"]) is False, template["template_id"]


def test_instantiate_renders_goal_and_validates():
    steps, max_steps = instantiate("inspect_project", "mijn camper")
    assert max_steps >= len(steps)
    assert any("mijn camper" in step["description"] for step in steps)
    mission = new_mission("mission_tpl", "conv-1", "mijn camper", steps,
                          max_steps=max_steps)
    assert mission.steps[0].kind == "readout"
    with pytest.raises(ValueError):
        instantiate("onbestaand", "x")
    with pytest.raises(ValueError):
        instantiate("inspect_project", "  ")


def test_template_endpoints(tmp_path, monkeypatch):
    for test_client in client(tmp_path, monkeypatch):
        listed = test_client.get("/api/v1/mission-templates")
        assert listed.status_code == 200
        assert len(listed.json()) == 8
        conversation = make_conversation(test_client)
        assert test_client.post("/api/v1/missions/from-template", json={
            "template_id": "nope", "conversation_id": conversation,
            "goal": "x"}).status_code == 422
        assert test_client.post("/api/v1/missions/from-template", json={
            "template_id": "inspect_project",
            "conversation_id": "conv-weg",
            "goal": "x"}).status_code == 404
        created = test_client.post("/api/v1/missions/from-template",
                                   json={
                                       "template_id": "investigate_inventory",
                                       "conversation_id": conversation,
                                       "goal": "wat kan ik bouwen"})
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["status"] == "pending_approval"
        assert get_template("investigate_inventory") is not None
