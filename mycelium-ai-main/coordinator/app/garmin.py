"""Garmin integration layer (BIG #11-15, Phase 2).

Honest states only: IMPLEMENTED (adapter interface, mock
provider, import pipeline) vs LIVE (real account data — only
when a real, legal API path with user credentials exists,
which it does not here). This module never pretends live
Garmin data works.

Provider states: AVAILABLE / UNAVAILABLE / MOCK /
CONFIGURED / AUTH_REQUIRED. Import maps provider samples to
health measurements (source=wearable,
provenance=external-source/imported) with cursor paging,
deduplication and a simulated rate limit on the mock.
"""

import os
import secrets
import time

from pydantic import BaseModel, Field

from .inventory_read import Provenance

GARMIN_STATES = (
    "AVAILABLE",
    "UNAVAILABLE",
    "MOCK",
    "CONFIGURED",
    "AUTH_REQUIRED",
)

# Provider sample type → health metric.
GARMIN_METRIC_MAP = {
    "steps": "steps",
    "sleep_hours": "sleep_hours",
    "stress": "stress",
    "resting_heart_rate": "heart_rate_bpm",
    "calories": "calories",
}

MOCK_RATE_LIMIT = 60


class GarminRefusedError(ValueError):
    """Fail-closed Garmin validation."""


def now() -> str:
    import datetime
    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


class GarminSample(BaseModel):
    sample_id: str = Field(min_length=3, max_length=80)
    sample_type: str = Field(min_length=1, max_length=40)
    value: float
    observed_at: str = Field(min_length=1, max_length=80)


class GarminProvider:
    """Adapter interface. Subclasses implement status() and
    fetch(). No network in the base."""

    name = "base"

    def status(self) -> dict:
        raise NotImplementedError

    def fetch(self, *, since: str = "", cursor: int = 0,
              limit: int = 50) -> tuple[list[GarminSample], int]:
        raise NotImplementedError


class UnavailableGarminProvider(GarminProvider):
    """Default: no credentials, no API path configured."""

    name = "unavailable"

    def status(self) -> dict:
        token = bool(os.environ.get("GARMIN_TOKEN", ""))
        if token:
            return {"state": "AUTH_REQUIRED",
                    "detail": "a token is configured but no "
                              "reviewed live Garmin transport "
                              "exists; live import stays off",
                    "provider": self.name}
        return {"state": "UNAVAILABLE",
                "detail": "no Garmin credentials and no live "
                          "transport; use the mock provider for "
                          "tests and development",
                "provider": self.name}

    def fetch(self, *, since: str = "", cursor: int = 0,
              limit: int = 50) -> tuple[list[GarminSample], int]:
        raise GarminRefusedError(
            "live Garmin provider is unavailable; no data "
            "was fetched and none is pretended")


class MockGarminProvider(GarminProvider):
    """Deterministic synthetic samples for tests/dev. Labelled
    MOCK everywhere; cursor paging, dedup-safe ids and a
    simulated rate limit included."""

    name = "mock"

    def __init__(self, days: int = 7):
        self.days = max(1, min(int(days), 30))
        self.calls = 0

    def status(self) -> dict:
        return {"state": "MOCK",
                "detail": "synthetic deterministic samples; "
                          "not a live integration",
                "provider": self.name}

    def _samples(self) -> list[GarminSample]:
        import datetime
        # Fixed anchor: deterministic across instances, so
        # re-imports deduplicate like a real cursor feed.
        base = datetime.datetime(
            2026, 9, 1, 8, 0, tzinfo=datetime.timezone.utc)
        out = []
        for day in range(self.days):
            moment = (base - datetime.timedelta(
                days=day)).isoformat()
            seed = day + 1
            out.append(GarminSample(
                sample_id=f"grm-mock-steps-{seed}",
                sample_type="steps",
                value=float(4000 + (seed * 137) % 6000),
                observed_at=moment))
            out.append(GarminSample(
                sample_id=f"grm-mock-sleep-{seed}",
                sample_type="sleep_hours",
                value=round(6.5 + (seed % 5) * 0.4, 2),
                observed_at=moment))
            out.append(GarminSample(
                sample_id=f"grm-mock-stress-{seed}",
                sample_type="stress",
                value=float(1 + (seed % 4)),
                observed_at=moment))
        return out

    def fetch(self, *, since: str = "", cursor: int = 0,
              limit: int = 50) -> tuple[list[GarminSample], int]:
        self.calls += 1
        if self.calls > MOCK_RATE_LIMIT:
            raise GarminRefusedError(
                "mock rate limit hit; back off")
        try:
            start = max(0, int(cursor or 0))
            count = max(1, min(int(limit or 50), 100))
        except (TypeError, ValueError):
            raise GarminRefusedError(
                "cursor/limit must be integers")
        items = [sample for sample in self._samples()
                 if not since or sample.observed_at > since]
        page = items[start:start + count]
        return page, start + len(page)


def get_garmin_provider(name: str | None = None,
                        **kwargs) -> GarminProvider:
    if (name or "unavailable") == "mock":
        return MockGarminProvider(**kwargs)
    return UnavailableGarminProvider()


def import_samples(provider: GarminProvider, *,
                   since: str = "", cursor: int = 0,
                   limit: int = 50) -> dict:
    """Fetch one page and map it to health measurements.
    Deduplicates on metric/source/observed_at; returns counts
    plus the next cursor. Provenance always
    external-source/imported with the provider named."""
    from .health import new_measurement, save_measurement
    try:
        page, next_cursor = provider.fetch(
            since=since, cursor=cursor, limit=limit)
    except GarminRefusedError:
        raise
    except Exception as error:
        raise GarminRefusedError(f"fetch failed: {error}")
    imported = 0
    duplicates = 0
    skipped = 0
    for sample in page:
        metric = GARMIN_METRIC_MAP.get(sample.sample_type)
        if metric is None:
            skipped += 1
            continue
        try:
            measurement = new_measurement(
                metric, sample.value, source="wearable",
                observed_at=sample.observed_at,
                provenance=Provenance(
                    source_type="external-source",
                    creator_id=f"garmin:{provider.name}",
                    human_verified=False,
                    notes=f"imported {sample.sample_type} "
                          f"(ref {sample.sample_id})"))
        except Exception:
            skipped += 1
            continue
        if save_measurement(measurement):
            imported += 1
        else:
            duplicates += 1
    return {"imported": imported, "duplicates": duplicates,
            "skipped": skipped, "next_cursor": next_cursor,
            "provider": provider.name,
            "provider_state": provider.status()["state"]}
