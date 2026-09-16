"""Phase 2 tests (BIG #11-15): health, nutrition, garmin."""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "p2.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "p2-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_health_measure_trend_index(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        # Unknown metric refuses; out-of-range refuses.
        assert test_client.post("/api/v1/health/measurements",
                                json={"metric": "nope",
                                      "value": 1}).status_code == 422
        assert test_client.post("/api/v1/health/measurements",
                                json={"metric": "sleep_hours",
                                      "value": 99}).status_code == 422
        first = test_client.post("/api/v1/health/measurements",
                                 json={"metric": "sleep_hours",
                                       "value": 7.5,
                                       "source": "manual",
                                       "observed_at":
                                       "2026-09-10T22:00:00+00:00"}
                                 ).json()
        assert first["stored"] is True
        assert first["unit"] == "h"
        # Same metric/source/moment dedups.
        again = test_client.post("/api/v1/health/measurements",
                                 json={"metric": "sleep_hours",
                                       "value": 7.5,
                                       "source": "manual",
                                       "observed_at":
                                       "2026-09-10T22:00:00+00:00"}
                                 ).json()
        assert again["duplicate"] is True
        trend = test_client.get(
            "/api/v1/health/trends/sleep_hours").json()
        assert trend["count"] == 1
        assert trend["avg"] == 7.5
        assert "method" in trend and "completeness" in trend
        index = test_client.get("/api/v1/health/index").json()
        assert index["dimensions"]["sleep"]["value"] is not None
        assert index["dimensions"]["training"]["value"] is None
        assert "overall_method" in index
        assert "overall_completeness" in index
        listed = test_client.get(
            "/api/v1/health/measurements",
            params={"metric": "sleep_hours"}).json()
        assert len(listed) == 1


def test_health_module_has_no_assessment_language():
    import pathlib
    source = (pathlib.Path(__file__).resolve().parent.parent /
              "coordinator" / "app" / "health.py").read_text(
                  encoding="utf-8").lower()
    assert "diagnos" not in source
    assert "disease" not in source
    assert "treatment" not in source


def test_nutrition_meal_totals_vegan_coverage(tmp_path,
                                              monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        # Vegan claim without evidence refuses.
        assert test_client.post("/api/v1/nutrition/foods", json={
            "name": "X", "nutrients": {"protein_g": 10},
            "vegan_status": "vegan"}).status_code == 422
        oats = test_client.post("/api/v1/nutrition/foods", json={
            "name": "Havermout",
            "nutrients": {"calories": 389, "protein_g": 13,
                          "fiber_g": 10, "iron_mg": 4.7},
            "vegan_status": "vegan",
            "vegan_evidence": "ingredients: whole grain oats"}).json()
        assert oats["food_id"].startswith("food_")
        # Unknown nutrient refuses.
        assert test_client.post("/api/v1/nutrition/foods", json={
            "name": "Y",
            "nutrients": {"frobnicate": 1}}).status_code == 422
        meal = test_client.post("/api/v1/nutrition/meals", json={
            "name": "Ontbijt",
            "items": [{"name": "Havermout",
                       "food_id": oats["food_id"],
                       "portion_g": 80,
                       "nutrients": oats["nutrients"],
                       "vegan_status": "vegan"},
                      {"name": "Banaan", "portion_g": 120,
                       "nutrients": {"calories": 89,
                                     "carbs_g": 23},
                       "vegan_status": "unknown"}],
            "observed_at": "2026-09-16T08:00:00+00:00"}).json()
        assert meal["totals"]["calories"] == round(
            389 * 0.8 + 89 * 1.2, 3)
        # Weakest vegan claim wins: unknown present.
        assert meal["vegan_status"] == "unknown"
        daily = test_client.get("/api/v1/nutrition/daily",
                                params={
                                    "day": "2026-09-16"}).json()
        assert daily["totals"]["meals"] == 1
        coverage = daily["coverage"]
        assert coverage["nutrients"]["protein_g"]["status"] in (
            "adequate", "possibly low", "possibly high",
            "unknown")
        assert coverage["reference_source"]
        assert "uncertainty" in coverage
        weekly = test_client.get("/api/v1/nutrition/weekly",
                                 params={
                                     "end_day": "2026-09-16"}).json()
        assert len(weekly["days"]) == 7
        assert weekly["days"][-1]["meals"] == 1


def test_garmin_status_mock_import(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        status = test_client.get(
            "/api/v1/integrations/garmin/status").json()
        assert status["state"] == "UNAVAILABLE"
        mock = test_client.get(
            "/api/v1/integrations/garmin/status",
            params={"provider": "mock"}).json()
        assert mock["state"] == "MOCK"
        # Live provider refuses to fetch.
        assert test_client.post(
            "/api/v1/integrations/garmin/import",
            json={"provider": "unavailable"}).status_code == 422
        first = test_client.post(
            "/api/v1/integrations/garmin/import",
            json={"provider": "mock", "limit": 6}).json()
        assert first["imported"] == 6
        assert first["provider_state"] == "MOCK"
        # Re-import dedups.
        second = test_client.post(
            "/api/v1/integrations/garmin/import",
            json={"provider": "mock", "limit": 6}).json()
        assert second["imported"] == 0
        assert second["duplicates"] == 6
        # Imported values land in health with wearable source.
        steps = test_client.get(
            "/api/v1/health/measurements",
            params={"metric": "steps",
                    "source": "wearable"}).json()
        assert len(steps) == 2
        assert steps[0]["provenance"]["source_type"] == \
            "external-source"
