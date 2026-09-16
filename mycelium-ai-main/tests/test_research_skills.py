"""Phase 3 tests (BIG #11-15): research, ingestion, skills."""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.research import mock_instagram_export


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "p3.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "p3-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_research_source_pipeline_and_dedup(tmp_path,
                                            monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        assert test_client.post("/api/v1/research/sources",
                                json={"source_type": "nope",
                                      "title": "X"}).status_code == 422
        created = test_client.post("/api/v1/research/sources",
                                   json={
                                       "source_type": "web",
                                       "title": "Oat milk protein",
                                       "content": "Oat milk has "
                                                  "about 1g protein "
                                                  "per 100ml.",
                                       "reference": "https://example.invalid/oats",
                                       "topics": ["vegan-food"]}
                                   ).json()
        assert created["source_id"].startswith("src_")
        assert created["status"] == "extracted"
        assert created["stored"] is True
        # Same content dedups.
        again = test_client.post("/api/v1/research/sources",
                                 json={
                                     "source_type": "web",
                                     "title": "Oat milk protein",
                                     "content": "Oat milk has "
                                                "about 1g protein "
                                                "per 100ml."}).json()
        assert again["duplicate"] is True
        # Stages advance one step, approval needs a human.
        source_id = created["source_id"]
        assert test_client.post(
            f"/api/v1/research/sources/{source_id}/advance",
            json={"to_stage": "stored"}).status_code == 422
        assert test_client.post(
            f"/api/v1/research/sources/{source_id}/advance",
            json={"to_stage": "proposed"}).json()[
                "status"] == "proposed"
        assert test_client.post(
            f"/api/v1/research/sources/{source_id}/advance",
            json={"to_stage": "approved",
                  "approved_by": ""}).status_code == 422
        assert test_client.post(
            f"/api/v1/research/sources/{source_id}/advance",
            json={"to_stage": "approved",
                  "approved_by": "jelles"}).json()[
                      "status"] == "approved"


def test_research_claims_must_cite_sources(tmp_path,
                                           monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        source = test_client.post("/api/v1/research/sources",
                                  json={
                                      "source_type": "document",
                                      "title": "Spool notes",
                                      "content": "PLA prints at "
                                                 "200C."}).json()
        # Uncited claim refuses (min_length=1 on source_ids
        # already 422s; unknown source refuses too).
        assert test_client.post("/api/v1/research/records",
                                json={
                                    "question": "At what temp?",
                                    "claims": [{
                                        "claim": "200C",
                                        "source_ids": [
                                            "src_missing"],
                                        "evidence": "?"}]}
                                ).status_code == 422
        record = test_client.post("/api/v1/research/records",
                                  json={
                                      "question": "At what temp "
                                                  "to print PLA?",
                                      "claims": [{
                                          "claim": "PLA prints "
                                                   "around 200C",
                                          "source_ids": [
                                              source["source_id"]],
                                          "evidence": "spool "
                                                      "notes state "
                                                      "200C",
                                          "confidence": 0.7,
                                          "interpretation":
                                          "single source; verify "
                                          "per spool"}],
                                      "synthesis": "Start at 200C "
                                                   "per one note; "
                                                   "unverified."}
                                  ).json()
        assert record["record_id"].startswith("rsch_")
        fetched = test_client.get(
            f"/api/v1/research/records/{record['record_id']}").json()
        assert fetched["question"].startswith("At what temp")
        assert fetched["claims"][0]["source_ids"] == [
            source["source_id"]]


def test_instagram_manual_export_only(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        status = test_client.get(
            "/api/v1/integrations/instagram/status").json()
        assert status["state"] == "UNAVAILABLE"
        # No live URLs, no scraped links.
        assert test_client.post("/api/v1/ingest/instagram",
                                json={
                                    "export": {"export_kind": "live",
                                               "items": []}}
                                ).status_code == 422
        mock = mock_instagram_export(3)
        assert mock["mock"] is True
        result = test_client.post("/api/v1/ingest/instagram",
                                  json={"export": mock,
                                        "collection": "vegan-food"}
                                  ).json()
        assert result["received"] == 3
        assert result["stored"] == 3
        refs = [item["reference"] for item in
                result["sources"]]
        assert all(ref.startswith("manual-export:")
                   for ref in refs)
        # Re-ingest dedups on content hash.
        again = test_client.post("/api/v1/ingest/instagram",
                                 json={"export": mock}).json()
        assert again["stored"] == 0
        assert again["duplicates"] == 3
        listed = test_client.get("/api/v1/research/sources",
                                 params={
                                     "source_type": "instagram"}).json()
        assert len(listed) == 3


def test_skills_candidate_evidence_progression(tmp_path,
                                               monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        # Discovery finds candidates, creates no skills.
        found = test_client.post("/api/v1/skills/discover",
                                 json={
                                     "project_text":
                                     "3D printed robotic arm "
                                     "with CAD bracket, Python "
                                     "control and slicer tuning",
                                     "project_ref": "proj_arm"}).json()
        names = {item["name"] for item in
                 found["candidates"]}
        assert {"CAD", "robotics", "Python",
                "slicer configuration"} <= names
        assert test_client.get(
            "/api/v1/skills").json() == []
        candidate_id = found["candidates"][0]["candidate_id"]
        # Accept needs a human; creates interested skill.
        assert test_client.post(
            f"/api/v1/skills/candidates/{candidate_id}/accept",
            json={"accepted_by": ""}).status_code == 422
        skill = test_client.post(
            f"/api/v1/skills/candidates/{candidate_id}/accept",
            json={"accepted_by": "jelles"}).json()
        assert skill["stage"] == "interested"
        skill_id = skill["skill_id"]
        # applied needs evidence; top stages need 2 + human.
        assert test_client.post(
            f"/api/v1/skills/{skill_id}/advance",
            json={"to_stage": "learning"}).json()[
                "stage"] == "learning"
        assert test_client.post(
            f"/api/v1/skills/{skill_id}/advance",
            json={"to_stage": "practicing"}).json()[
                "stage"] == "practicing"
        assert test_client.post(
            f"/api/v1/skills/{skill_id}/advance",
            json={"to_stage": "applied"}).status_code == 422
        test_client.post(f"/api/v1/skills/{skill_id}/evidence",
                         json={"kind": "project",
                               "ref": "proj_arm",
                               "note": "bracket printed"})
        assert test_client.post(
            f"/api/v1/skills/{skill_id}/advance",
            json={"to_stage": "applied"}).json()[
                "stage"] == "applied"
        assert test_client.post(
            f"/api/v1/skills/{skill_id}/advance",
            json={"to_stage": "demonstrated",
                  "confirmed_by": "jelles"}).status_code == 422
        test_client.post(f"/api/v1/skills/{skill_id}/evidence",
                         json={"kind": "print",
                               "ref": "fab_1",
                               "note": "arm assembled"})
        demo = test_client.post(
            f"/api/v1/skills/{skill_id}/advance",
            json={"to_stage": "demonstrated",
                  "confirmed_by": "jelles"}).json()
        assert demo["stage"] == "demonstrated"
        # No skipping, no going back.
        assert test_client.post(
            f"/api/v1/skills/{skill_id}/advance",
            json={"to_stage": "learning"}).status_code == 422


def test_new_modules_have_no_shell_or_network():
    import pathlib
    app = pathlib.Path(__file__).resolve().parent.parent / \
        "coordinator" / "app"
    for name in ("research.py", "skills.py", "health.py",
                 "nutrition.py", "garmin.py", "memory.py"):
        source = (app / name).read_text(encoding="utf-8")
        for token in ("subprocess", "os.system", "eval(",
                      "import sqlite3", "https://", "boto",
                      "kubernetes", "0.0.0.0"):
            assert token not in source, f"{name}: {token}"
