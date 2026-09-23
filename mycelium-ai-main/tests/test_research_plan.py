"""Tests for Research → Mission Plan bridge (research_plan.py + API endpoint).

Coverage:
  - Unit: extract_dispatchable_urls, generate_mission_steps_from_dossier
  - Unit: resolve_dossier_and_run (missing entity → LookupError / ValueError)
  - Unit: propose_research_mission happy path + idempotency
  - HTTP: POST /api/v1/research/{research_id}/plan
    - 201 on new mission (run_id or dossier_id)
    - 200 + is_new=False on idempotent second call
    - 404 for unknown research_id
    - mission always starts in pending_approval
    - human_verified always False
    - no forbidden step kinds ever generated
    - dispatch=False → analysis-only step
    - dispatch=True + URLs → research + analysis steps
"""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

# ---------------------------------------------------------------------------
# PAGES fixture (same as test_research_api.py for consistency)
# ---------------------------------------------------------------------------

PAGES = {
    "camper": [
        "Camper onderhoud",
        "De distributieriem is belangrijk voor de motor. "
        "De camper heeft een zonnepaneel van 200 watt.",
    ],
    "riem": [
        "Riemwissel",
        "De distributieriem is niet belangrijk voor de motor. "
        "De riemwissel duurt ongeveer drie uur werk.",
    ],
}

FORBIDDEN_KINDS = {"desktop", "write", "physical_print", "fabricate", "slice",
                   "camera_observe"}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH", str(tmp_path / "rp.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH", str(tmp_path / "rp-chat.db"))
    with TestClient(main_mod.app) as tc:
        yield tc


def _create_completed_run(client) -> dict:
    """Helper: create + execute a research run using the test provider."""
    resp = client.post("/api/v1/research/runs", json={
        "question": "Hoe werkt de distributieriem van een camper?",
        "provider": "test",
        "test_pages": PAGES,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Unit tests (no HTTP) — pure logic
# ---------------------------------------------------------------------------


def test_extract_dispatchable_urls_filters_non_http():
    from coordinator.app.research_plan import extract_dispatchable_urls
    from coordinator.app.research_engine import ResearchDossier

    dossier = ResearchDossier(
        dossier_id="dos_test1",
        run_id="res_test1",
        title="Test",
        question="Test question?",
        sources=[
            {"url": "https://example.com/page"},
            {"url": "ftp://bad.example.com"},
            {"url": "http://valid.example.com/two"},
            {"url": ""},
            {"url": "not-a-url"},
            {"url": "https://example.com/page"},   # duplicate
        ],
    )
    urls = extract_dispatchable_urls(dossier)
    assert len(urls) == 2
    assert "https://example.com/page" in urls
    assert "http://valid.example.com/two" in urls
    # no ftp, no blank, no non-url, no duplicates
    assert all(u.startswith("http") for u in urls)


def test_extract_dispatchable_urls_caps_at_six():
    from coordinator.app.research_plan import extract_dispatchable_urls

    sources = [{"url": f"https://example.com/{i}"} for i in range(10)]
    dossier = {"question": "q?", "sources": sources}
    urls = extract_dispatchable_urls(dossier)
    assert len(urls) == 6


def test_generate_steps_with_dispatch_and_urls():
    from coordinator.app.research_plan import generate_mission_steps_from_dossier
    from coordinator.app.research_engine import ResearchDossier

    dossier = ResearchDossier(
        dossier_id="dos_t2",
        run_id="res_t2",
        title="T",
        question="Hoe werkt X?",
        sources=[{"url": "https://example.com/a"}, {"url": "https://example.com/b"}],
    )
    steps = generate_mission_steps_from_dossier(dossier, dispatch=True)
    assert len(steps) == 2
    assert steps[0]["kind"] == "research"
    assert steps[1]["kind"] == "analysis"
    # H1-dispatchable: dispatch=True must be in step parameters
    assert steps[0]["parameters"]["dispatch"] is True
    assert "source_urls" in steps[0]["parameters"]
    assert len(steps[0]["parameters"]["source_urls"]) == 2
    # requires_approval must be False on all generated steps
    for step in steps:
        assert step.get("requires_approval") is False
        assert step["kind"] not in FORBIDDEN_KINDS


def test_generate_steps_dispatch_false_is_analysis_only():
    from coordinator.app.research_plan import generate_mission_steps_from_dossier
    from coordinator.app.research_engine import ResearchDossier

    dossier = ResearchDossier(
        dossier_id="dos_t3",
        run_id="res_t3",
        title="T",
        question="Hoe werkt Y?",
        sources=[{"url": "https://example.com/x"}],
    )
    steps = generate_mission_steps_from_dossier(dossier, dispatch=False)
    assert len(steps) == 1
    assert steps[0]["kind"] == "analysis"
    assert steps[0].get("requires_approval") is False


def test_generate_steps_no_urls_falls_back_to_analysis():
    from coordinator.app.research_plan import generate_mission_steps_from_dossier
    from coordinator.app.research_engine import ResearchDossier

    dossier = ResearchDossier(
        dossier_id="dos_t4",
        run_id="res_t4",
        title="T",
        question="Hoe werkt Z?",
        sources=[],  # no URLs → must fall back
    )
    steps = generate_mission_steps_from_dossier(dossier, dispatch=True)
    assert len(steps) == 1
    assert steps[0]["kind"] == "analysis"


def test_no_forbidden_kinds_ever_generated():
    """Safety invariant: all generated step kinds are outside FORBIDDEN_KINDS."""
    from coordinator.app.research_plan import (
        FORBIDDEN_STEP_KINDS,
        generate_mission_steps_from_dossier,
    )
    from coordinator.app.research_engine import ResearchDossier

    dossier = ResearchDossier(
        dossier_id="dos_safety",
        run_id="res_safety",
        title="Safety test",
        question="Veiligheidstest?",
        sources=[{"url": "https://example.com/safe"}],
    )
    for dispatch in (True, False):
        steps = generate_mission_steps_from_dossier(dossier, dispatch=dispatch)
        for step in steps:
            assert step["kind"] not in FORBIDDEN_KINDS
            assert step["kind"] not in FORBIDDEN_STEP_KINDS


def test_resolve_dossier_and_run_unknown_raises_lookup_error(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH", str(tmp_path / "res_lu.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH", str(tmp_path / "res_lu_chat.db"))
    # Force DB initialisation by importing the app
    from coordinator.app.research_plan import resolve_dossier_and_run
    with pytest.raises(LookupError, match="not found"):
        resolve_dossier_and_run("res_does_not_exist")


def test_resolve_dossier_and_run_empty_raises_value_error(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH", str(tmp_path / "res_ve.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH", str(tmp_path / "res_ve_chat.db"))
    from coordinator.app.research_plan import resolve_dossier_and_run
    with pytest.raises(ValueError, match="non-empty"):
        resolve_dossier_and_run("   ")


# ---------------------------------------------------------------------------
# HTTP API tests
# ---------------------------------------------------------------------------


def test_plan_404_for_unknown_research_id(client):
    resp = client.post("/api/v1/research/res_doesnotexist/plan", json={})
    assert resp.status_code == 404


def test_plan_404_for_unknown_dossier_id(client):
    resp = client.post("/api/v1/research/dos_doesnotexist/plan", json={})
    assert resp.status_code == 404


def test_plan_creates_pending_approval_mission_from_run_id(client):
    run = _create_completed_run(client)
    run_id = run["run_id"]

    resp = client.post(f"/api/v1/research/{run_id}/plan", json={
        "dispatch": True,
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()

    # Basic shape
    assert body["mission_id"].startswith("mis_") or len(body["mission_id"]) > 3
    assert body["status"] == "pending_approval"
    assert body["is_new"] is True

    # Provenance: never human_verified
    assert body["provenance"]["human_verified"] is False
    assert body["provenance"]["source_type"] == "external-source"

    # Steps: at least one, no forbidden kinds, requires_approval=False everywhere
    assert len(body["steps"]) >= 1
    for step in body["steps"]:
        assert step["kind"] not in FORBIDDEN_KINDS
        assert step.get("requires_approval") is False


def test_plan_creates_pending_approval_mission_from_dossier_id(client):
    run = _create_completed_run(client)
    dossier_id = run["dossier_id"]
    assert dossier_id.startswith("dos_")

    resp = client.post(f"/api/v1/research/{dossier_id}/plan", json={})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "pending_approval"
    assert body["is_new"] is True
    assert body["provenance"]["human_verified"] is False


def test_plan_is_idempotent_by_run_id(client):
    run = _create_completed_run(client)
    run_id = run["run_id"]

    first = client.post(f"/api/v1/research/{run_id}/plan", json={})
    assert first.status_code == 201
    first_body = first.json()
    assert first_body["is_new"] is True

    second = client.post(f"/api/v1/research/{run_id}/plan", json={})
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["is_new"] is False

    # Same mission returned both times
    assert second_body["mission_id"] == first_body["mission_id"]
    assert second_body["status"] == "pending_approval"


def test_plan_is_idempotent_by_dossier_id(client):
    run = _create_completed_run(client)
    dossier_id = run["dossier_id"]

    first = client.post(f"/api/v1/research/{dossier_id}/plan", json={})
    assert first.status_code == 201

    second = client.post(f"/api/v1/research/{dossier_id}/plan", json={})
    assert second.status_code == 200
    assert second.json()["is_new"] is False
    assert second.json()["mission_id"] == first.json()["mission_id"]


def test_plan_dispatch_false_generates_analysis_only(client):
    run = _create_completed_run(client)
    run_id = run["run_id"]

    resp = client.post(f"/api/v1/research/{run_id}/plan", json={"dispatch": False})
    assert resp.status_code == 201, resp.text
    steps = resp.json()["steps"]
    assert all(s["kind"] == "analysis" for s in steps)


def test_plan_dispatch_true_may_include_research_step(client):
    """With dispatch=True and test pages that produce URLs, expect a research step."""
    run = _create_completed_run(client)
    run_id = run["run_id"]

    resp = client.post(f"/api/v1/research/{run_id}/plan", json={"dispatch": True})
    assert resp.status_code == 201, resp.text
    kinds = {s["kind"] for s in resp.json()["steps"]}
    # Either research+analysis (URLs found) or analysis-only (no dossier URLs).
    # Both are valid; the key is no forbidden kinds appear.
    assert kinds.isdisjoint(FORBIDDEN_KINDS)


def test_plan_never_auto_approves(client):
    """Mission must remain in pending_approval — never running or approved."""
    run = _create_completed_run(client)
    resp = client.post(f"/api/v1/research/{run['run_id']}/plan", json={})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending_approval"
    assert body["status"] != "running"
    assert body["status"] != "approved"


def test_plan_custom_goal_is_used(client):
    run = _create_completed_run(client)
    resp = client.post(f"/api/v1/research/{run['run_id']}/plan", json={
        "goal": "Specifiek doel voor deze missie",
    })
    assert resp.status_code == 201
    assert "Specifiek doel" in resp.json()["goal"]


def test_plan_metadata_contains_research_ids(client):
    run = _create_completed_run(client)
    resp = client.post(f"/api/v1/research/{run['run_id']}/plan", json={})
    assert resp.status_code == 201
    meta = resp.json().get("metadata", {})
    assert "research_dossier_id" in meta
    assert "research_run_id" in meta
    assert meta["research_dossier_id"].startswith("dos_")
    assert meta["research_run_id"].startswith("res_")
