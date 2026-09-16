"""Health domain (BIG #11-15, Phase 2).

Personal tracking and trends — never a medical engine. There
is no illness-assessment function in this module, no hidden
score and no medical claim: the personal health index is a
transparent set of per-dimension ratios (raw values, method
shown, completeness shown, missing data shown).

Every measurement carries source + provenance. Sources arrive
through adapters (manual/wearable/sensor/derived/external/
file); the engine never hardcodes one integration.
"""

import secrets
import time

from pydantic import BaseModel, Field

from .inventory_read import Provenance

# Closed metric allow-list: tracking only.
METRICS = {
    "sleep_hours": "h",
    "sleep_quality": "1-5",
    "steps": "count",
    "activity_min": "min",
    "training_min": "min",
    "recovery": "1-5",
    "hydration_l": "l",
    "meals_count": "count",
    "weight_kg": "kg",
    "bmi": "index",
    "waist_cm": "cm",
    "hip_cm": "cm",
    "waist_hip": "ratio",
    "energy": "1-5",
    "stress": "1-5",
    "heart_rate_bpm": "bpm",
    "calories": "kcal",
}

SOURCES = (
    "manual",
    "wearable",
    "sensor",
    "inventory_derived",
    "external",
    "file_import",
)

# Transparent index dimensions: metric → (dimension, target,
# direction). The method string is part of every output.
INDEX_DIMENSIONS = {
    "sleep": [("sleep_hours", 8.0, "near"),
              ("sleep_quality", 4.0, "max")],
    "activity": [("steps", 8000.0, "max"),
                 ("activity_min", 30.0, "max")],
    "recovery": [("recovery", 4.0, "max"),
                 ("sleep_hours", 8.0, "near")],
    "hydration": [("hydration_l", 2.0, "max")],
    "nutrition": [("meals_count", 3.0, "max")],
    "body": [("weight_kg", None, "trend")],
    "habits": [("energy", 4.0, "max")],
    "training": [("training_min", 150.0, "max-week")],
}


class HealthRefusedError(ValueError):
    """Fail-closed health validation."""


def now() -> str:
    import datetime
    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


def generate_measurement_id() -> str:
    return f"hlth_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


class HealthMeasurement(BaseModel):
    measurement_id: str = Field(min_length=3, max_length=80)
    metric: str = Field(min_length=1, max_length=40)
    value: float
    unit: str = Field(default="", max_length=20)
    source: str = Field(min_length=1, max_length=20)
    provenance: Provenance
    observed_at: str = Field(min_length=1, max_length=80)
    created_at: str = Field(default="", max_length=80)


def _check_metric_value(metric: str, value: float) -> float:
    if metric not in METRICS:
        raise HealthRefusedError(
            f"Unknown metric '{metric}'")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise HealthRefusedError("value must be numeric")
    if number != number or number in (float("inf"),
                                      float("-inf")):
        raise HealthRefusedError("value must be finite")
    bounds = {"sleep_hours": (0, 24), "sleep_quality": (1, 5),
              "steps": (0, 200000), "activity_min": (0, 1440),
              "training_min": (0, 1440), "recovery": (1, 5),
              "hydration_l": (0, 15), "meals_count": (0, 12),
              "weight_kg": (20, 400), "bmi": (10, 80),
              "waist_cm": (30, 300), "hip_cm": (30, 300),
              "waist_hip": (0.3, 3.0), "energy": (1, 5),
              "stress": (1, 5), "heart_rate_bpm": (25, 250),
              "calories": (0, 20000)}
    low, high = bounds[metric]
    if not low <= number <= high:
        raise HealthRefusedError(
            f"{metric} must be within {low}..{high}")
    return number


def new_measurement(metric: str, value: float, *,
                    source: str = "manual",
                    observed_at: str = "",
                    provenance: Provenance | None = None
                    ) -> HealthMeasurement:
    """One validated measurement. Source is explicit; wearable
    or external values are marked, never silently trusted."""
    if source not in SOURCES:
        raise HealthRefusedError(f"Unknown source '{source}'")
    number = _check_metric_value(metric, value)
    stamp = now()
    return HealthMeasurement(
        measurement_id=generate_measurement_id(),
        metric=metric, value=number, unit=METRICS[metric],
        source=source,
        provenance=provenance or Provenance(
            source_type="user-created"
            if source == "manual" else "sensor-observed",
            creator_id=f"health:{source}",
            human_verified=source == "manual"),
        observed_at=observed_at or stamp, created_at=stamp)


def dedup_key_for(metric: str, source: str,
                  observed_at: str) -> str:
    return f"{metric}|{source}|{observed_at}"


def save_measurement(entry: HealthMeasurement) -> bool:
    """Insert unless the same metric/source/moment exists.
    Returns True when stored, False on duplicate."""
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        cursor = db.execute("""INSERT INTO health_measurements
        (measurement_id, metric, value, unit, source,
         provenance, observed_at, created_at, dedup_key)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(measurement_id) DO NOTHING""",
                            (entry.measurement_id,
                             entry.metric, entry.value,
                             entry.unit, entry.source,
                             dump(entry.provenance.model_dump(
                                 mode="json")),
                             entry.observed_at,
                             entry.created_at,
                             dedup_key_for(
                                 entry.metric, entry.source,
                                 entry.observed_at)))
        if cursor.rowcount == 0:
            return False
        existing = db.execute(
            "SELECT measurement_id FROM health_measurements "
            "WHERE dedup_key=? AND measurement_id!=?",
            (dedup_key_for(entry.metric, entry.source,
                           entry.observed_at),
             entry.measurement_id)).fetchone()
        if existing is not None:
            db.execute("DELETE FROM health_measurements WHERE "
                       "measurement_id=?",
                       (entry.measurement_id,))
            return False
    return True


def _row_to_measurement(row) -> HealthMeasurement:
    from .database import load
    return HealthMeasurement(
        measurement_id=row["measurement_id"],
        metric=row["metric"], value=row["value"],
        unit=row["unit"], source=row["source"],
        provenance=Provenance(**load(row["provenance"])),
        observed_at=row["observed_at"],
        created_at=row["created_at"])


def list_measurements(*, metric: str = "", source: str = "",
                      since: str = "",
                      limit: int = 100) -> list[HealthMeasurement]:
    from .database import chat_connection, init_chat_database
    if metric and metric not in METRICS:
        raise HealthRefusedError(
            f"Unknown metric '{metric}'")
    if source and source not in SOURCES:
        raise HealthRefusedError(f"Unknown source '{source}'")
    init_chat_database()
    clauses, params = [], []
    if metric:
        clauses.append("metric=?")
        params.append(metric)
    if source:
        clauses.append("source=?")
        params.append(source)
    if since:
        clauses.append("observed_at>?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with chat_connection() as db:
        rows = db.execute(
            f"SELECT * FROM health_measurements {where} ORDER "
            f"BY observed_at DESC LIMIT ?",
            (*params, max(1, min(int(limit or 100), 500)))
        ).fetchall()
    return [_row_to_measurement(row) for row in rows]


def trend_for(metric: str, *, limit: int = 30) -> dict:
    """Transparent trend: raw points, min/max/avg, method and
    completeness. No interpretation, no advice."""
    points = list_measurements(metric=metric, limit=limit)
    values = [entry.value for entry in points]
    ordered = sorted(values)
    count = len(values)
    return {
        "metric": metric, "unit": METRICS[metric],
        "count": count,
        "points": [{"value": entry.value,
                    "observed_at": entry.observed_at,
                    "source": entry.source}
                   for entry in points],
        "min": ordered[0] if ordered else None,
        "max": ordered[-1] if ordered else None,
        "avg": round(sum(values) / count, 2) if count else None,
        "method": "observed values sorted oldest-first; avg "
                  "is the arithmetic mean of stored points",
        "completeness": f"{count} stored point(s); gaps mean "
                        "no data, never zero",
    }


def _dimension_ratio(metric: str, target: float | None,
                     direction: str) -> dict | None:
    points = list_measurements(metric=metric, limit=7)
    if not points:
        return None
    latest = sum(entry.value for entry in points) / len(points)
    if target is None or direction == "trend":
        return {"value": None, "method": f"{metric}: "
                f"latest-7d mean {round(latest, 2)} "
                f"{METRICS[metric]} shown as trend only, "
                "no target judged",
                "completeness": f"{len(points)}/7 days",
                "inputs": len(points)}
    if direction == "near":
        ratio = max(0.0, 1.0 - abs(latest - target)
                    / target) if target else 0.0
        method = f"{metric}: 1 - |mean-target|/target " \
                 f"(mean {round(latest, 2)}, target {target})"
    else:
        ratio = max(0.0, min(1.0, latest / target)) \
            if target else 0.0
        method = f"{metric}: min(1, mean/target) " \
                 f"(mean {round(latest, 2)}, target {target})"
    return {"value": round(ratio, 3), "method": method,
            "completeness": f"{len(points)}/7 days",
            "inputs": len(points)}


def personal_health_index() -> dict:
    """Per-dimension ratios with method + completeness. The
    overall is a plain mean of available dimensions, labelled
    with how many dimensions fed it. Nothing hidden."""
    dimensions = {}
    for name, specs in INDEX_DIMENSIONS.items():
        parts = []
        for metric, target, direction in specs:
            part = _dimension_ratio(metric, target, direction)
            if part is not None:
                parts.append(part)
        if not parts:
            dimensions[name] = {
                "value": None, "method": "no data",
                "completeness": "0 inputs", "inputs": 0}
            continue
        values = [part["value"] for part in parts
                  if part["value"] is not None]
        dimensions[name] = {
            "value": round(sum(values) / len(values), 3)
            if values else None,
            "method": "mean of: " + "; ".join(
                part["method"] for part in parts),
            "completeness": f"{len(parts)}/{len(specs)} "
                            "signals present",
            "inputs": sum(part["inputs"] for part in parts)}
    available = [info["value"] for info in dimensions.values()
                 if info["value"] is not None]
    return {
        "dimensions": dimensions,
        "overall": round(sum(available) / len(available), 3)
        if available else None,
        "overall_method": "plain mean of available dimension "
                          "ratios (no weights, no model)",
        "overall_completeness": f"{len(available)}/"
                                f"{len(dimensions)} dimensions",
        "warning": "tracking transparency only; not a "
                   "medical statement of any kind",
    }
