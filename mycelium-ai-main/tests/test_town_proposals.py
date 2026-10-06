"""Fase 5b/5c: delegatie (voorstel + exact-YES) en
autonomie-dial. Geen model, geen nodes: _draft_text wordt
gemockt; Hermes/Ollama expres dood."""

import pytest
from fastapi.testclient import TestClient

DRAFT = ("zeker ```json\n"
         '{"kind": "research.fetch_url", '
         '"goal": "haal de filestats op", '
         '"justification": "voorman vroeg erom", '
         '"blast_radius": "een GET, volledig omkeerbaar", '
         '"confidence": 0.8}\n```')


@pytest.fixture()
def dbtmp(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MYCELIUM_DATABASE_PATH",
        str(tmp_path / "mycelium.db"))
    monkeypatch.setenv(
        "MYCELIUM_CHAT_DATABASE_PATH",
        str(tmp_path / "chat.db"))
    monkeypatch.setenv(
        "INVENTORY_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.delenv("HERMES_API_KEY", raising=False)
    monkeypatch.delenv("TOWN_AUTONOMY", raising=False)
    monkeypatch.setenv(
        "OLLAMA_BASE_URL", "http://127.0.0.1:9")
    # Queue-DB initialiseren zoals de lifespan van de app
    # dat doet (tasks-tabel voor directe queue-aanroepen).
    from coordinator.app.database import (
        init_chat_database, init_database)
    init_database()
    init_chat_database()


@pytest.fixture()
def client(dbtmp):
    import coordinator.app.main as main
    with TestClient(main.app) as c:
        yield c


def test_propose_validation(dbtmp):
    from coordinator.app.town_proposals import (
        ProposalRefusedError, propose_task)
    good = propose_task(
        "voorman", "research.fetch_url",
        "haal stats op", "nodig voor planning",
        "een GET, omkeerbaar", 0.8)
    assert good["status"] == "proposed"
    assert good["proposal_id"].startswith("tprop-")
    for args in (
            ("nope", "research.fetch_url", "g", "w", "b", 0.5),
            ("voorman", "print.execute", "g", "w", "b", 0.5),
            ("voorman", "desktop.click", "g", "w", "b", 0.5),
            ("voorman", "research.fetch_url", "", "w", "b",
             0.5),
            ("voorman", "research.fetch_url", "g", "w", "b",
             1.5),
            ("voorman", "research.fetch_url", "g", "w", "b",
             "hoog")):
        try:
            propose_task(*args)
        except ProposalRefusedError:
            pass
        else:
            raise AssertionError(f"accepted {args}")


def test_extract_spec_strict(dbtmp):
    from coordinator.app.town_proposals import (
        ProposalRefusedError, extract_proposal_spec)
    spec = extract_proposal_spec(DRAFT)
    assert spec["kind"] == "research.fetch_url"
    assert spec["confidence"] == 0.8
    for bad in ("geen blok hier",
                "```json\n{geen json}\n```",
                "```json\n{}\n```",
                "```json\n"
                '{"kind": "print.execute", "goal": "g", '
                '"justification": "w", "blast_radius": "b", '
                '"confidence": 0.5}\n```'):
        try:
            extract_proposal_spec(bad)
        except ProposalRefusedError:
            pass
        else:
            raise AssertionError(f"accepted {bad[:40]}")


def test_exact_yes_queues_task(dbtmp):
    from coordinator.app.town_proposals import (
        ProposalRefusedError, get_proposal,
        propose_task, decide_proposal)
    prop = propose_task(
        "voorman", "research.fetch_url",
        "haal stats op", "nodig voor planning",
        "een GET, omkeerbaar", 0.8)
    pid = prop["proposal_id"]
    decided = decide_proposal(pid, "YES", "you")
    assert decided["status"] == "approved"
    assert decided["decided_by"] == "you"
    assert decided["queue_task_id"] > 0
    from coordinator.app.database import connection
    with connection() as db:
        row = db.execute(
            "SELECT kind, status, payload FROM tasks "
            "WHERE id=?",
            (decided["queue_task_id"],)).fetchone()
    assert row["kind"] == "research.fetch_url"
    assert row["status"] == "queued"
    assert "town-voorman" in row["payload"]
    for again in ("YES", "nee", ""):
        try:
            decide_proposal(pid, again, "you")
        except ProposalRefusedError:
            pass
        else:
            raise AssertionError("second decide accepted")


def test_near_yes_is_rejection(dbtmp):
    from coordinator.app.town_proposals import (
        propose_task, decide_proposal)
    for word in ("yes", "YES!", "ja", "ok", ""):
        prop = propose_task(
            "voorman", "research.fetch_url",
            "haal stats op", "nodig", "een GET", 0.8)
        out = decide_proposal(
            prop["proposal_id"], word, "you")
        assert out["status"] == "rejected", word
        assert out["queue_task_id"] == 0


def test_autonomy_default_off(dbtmp):
    from coordinator.app.town_proposals import (
        autonomy_rules, is_autonomous, propose_task)
    assert autonomy_rules() == {}
    assert not is_autonomous("voorman",
                             "research.fetch_url")
    prop = propose_task(
        "voorman", "research.fetch_url",
        "haal stats op", "nodig", "een GET", 0.8)
    assert prop["status"] == "proposed"


def test_autonomy_allowlist_and_audit(dbtmp,
                                      monkeypatch):
    from coordinator.app.town_proposals import (
        autonomy_rules, is_autonomous, propose_task,
        list_proposals)
    monkeypatch.setenv(
        "TOWN_AUTONOMY",
        "voorman:research.fetch_url,"
        "voorman:print.execute,"
        "voorman:desktop.click,"
        "nope:research.fetch_url")
    rules = autonomy_rules()
    assert rules == {
        "voorman": ["research.fetch_url"]}
    assert is_autonomous("voorman",
                         "research.fetch_url")
    assert not is_autonomous("voorman",
                             "print.execute")
    prop = propose_task(
        "voorman", "research.fetch_url",
        "haal stats op", "nodig", "een GET", 0.8)
    assert prop["status"] == "auto-queued"
    assert prop["decided_by"] == (
        "standing-rule:TOWN_AUTONOMY")
    assert prop["queue_task_id"] > 0
    listed = [p for p in list_proposals()
              if p["proposal_id"] ==
              prop["proposal_id"]]
    assert listed and listed[0]["status"] == (
        "auto-queued")


def test_draft_proposal_needs_model(dbtmp):
    from coordinator.app.town_proposals import (
        ProposalRefusedError, draft_proposal)
    try:
        draft_proposal("voorman", "zoek iets op")
    except ProposalRefusedError:
        pass
    else:
        raise AssertionError(
            "draft without model accepted")


def test_draft_proposal_mocked(dbtmp, monkeypatch):
    import coordinator.app.town_proposals as tp
    monkeypatch.setattr(
        tp, "_draft_text", lambda n, r: DRAFT)
    prop = tp.draft_proposal(
        "voorman", "zoek de filestats op")
    assert prop["npc_id"] == "voorman"
    assert prop["goal"] == "haal de filestats op"


def test_delegate_api(client, monkeypatch):
    import coordinator.app.town_proposals as tp
    monkeypatch.setattr(
        tp, "_draft_text", lambda n, r: DRAFT)
    res = client.post(
        "/api/v1/town/npc/voorman/delegate",
        json={"request": "zoek iets op"})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["npc_id"] == "voorman"
    assert body["status"] == "proposed"
    pid = body["proposal_id"]
    listed = client.get("/api/v1/town/proposals")
    assert listed.status_code == 200
    assert any(p["proposal_id"] == pid
               for p in listed.json()["proposals"])
    decided = client.post(
        f"/api/v1/town/proposals/{pid}/decide",
        json={"decision": "YES", "decided_by": "you"})
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "approved"
    again = client.post(
        f"/api/v1/town/proposals/{pid}/decide",
        json={"decision": "YES"})
    assert again.status_code == 409
    unknown = client.post(
        "/api/v1/town/npc/nope/delegate",
        json={"request": "x"})
    assert unknown.status_code == 409


def test_autonomy_api(client, monkeypatch):
    res = client.get("/api/v1/town/autonomy")
    assert res.status_code == 200
    body = res.json()
    assert body["rules"] == {}
    assert "research.fetch_url" in body["may_ever"]
    assert "hardware" in body["never"].lower() or \
        "hardware" in str(body).lower()
    monkeypatch.setenv(
        "TOWN_AUTONOMY",
        "smid:system_inventory")
    res2 = client.get("/api/v1/town/autonomy")
    assert res2.json()["rules"] == {
        "smid": ["system_inventory"]}


def test_bureau_panel_present(client):
    res = client.get("/solarpunk")
    assert res.status_code == 200
    assert 'id="spc-bureau"' in res.text
    assert 'id="spc-del-go"' in res.text
    assert 'id="spc-autonomy"' in res.text
    assert 'id="spc-near-del"' in res.text
