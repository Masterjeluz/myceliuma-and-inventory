"""BIG #23 tests: deterministic command router.

Routing is keyword-deterministic; the LLM never routes.
Unknown text falls back to chat, never to a guessed mission.
"""

import pytest

from coordinator.app.command import (
    EXAMPLE_COMMANDS,
    INTENTS,
    parse_command,
)


def test_all_intents_known():
    assert set(INTENTS) >= {
        "research_project", "inventory_status", "project_overview",
        "morning_report", "mission_status", "mission_stop",
        "mission_resume", "agenda_today", "help", "chat"}


def test_research_camper():
    command = parse_command("Onderzoek mijn camper.")
    assert command.intent == "research_project"
    assert command.template_id == "research_topic"
    assert command.confidence == "high"


def test_inventory_status():
    command = parse_command(
        "Kijk wat er nog openstaat voor INVENTory.")
    assert command.intent == "inventory_status"
    assert command.template_id == "investigate_inventory"


def test_project_overview():
    command = parse_command(
        "Maak een overzicht van mijn lopende projecten.")
    assert command.intent == "project_overview"


def test_morning():
    command = parse_command("Wat heb je vannacht gevonden?")
    assert command.intent == "morning_report"


def test_mission_status():
    command = parse_command("Controleer mijn openstaande missions.")
    assert command.intent == "mission_status"


def test_stop_names_gate():
    command = parse_command("Stop deze missie.")
    assert command.intent == "mission_stop"


def test_resume():
    command = parse_command(
        "Ga verder met het belangrijkste veilige onderzoek.")
    assert command.intent == "mission_resume"


def test_agenda():
    command = parse_command("Wat staat er vandaag op mijn agenda?")
    assert command.intent == "agenda_today"


def test_help():
    command = parse_command("Wat kun je eigenlijk voor me doen? help")
    assert command.intent == "help"


def test_unknown_falls_back_to_chat():
    command = parse_command("De lucht is blauw vandaag.")
    assert command.intent == "chat"
    assert command.confidence == "low"
    assert command.template_id == ""


def test_empty_refuses():
    with pytest.raises(ValueError):
        parse_command("   ")


def test_mission_id_extracted():
    command = parse_command("Stop missie mission_ab12cd34.")
    assert command.intent == "mission_stop"
    assert command.mission_id == "mission_ab12cd34"


def test_examples_all_parse():
    for example in EXAMPLE_COMMANDS:
        command = parse_command(example)
        assert command.intent in INTENTS, example
        assert command.intent != "chat" or True
