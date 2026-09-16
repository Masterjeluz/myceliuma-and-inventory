"""Nutrition domain (BIG #11-15, Phase 2).

MEAL → INGREDIENT → PORTION → NUTRIENT → DAILY TOTAL →
WEEKLY TREND, over an extensible nutrient model (no giant
hardcoded food database). AI may propose values, but source
and verification stay visible on every number.

Vegan-first: vegan_status is explicit per food
(vegan/non_vegan/unknown) with evidence required for any
claim — never an AI guess presented as fact.

Coverage compares actual intake against configurable
reference targets and answers only adequate/possibly
low/possibly high/unknown, always with source, context,
calculation and uncertainty. Never a medical statement.
"""

import secrets
import time

from pydantic import BaseModel, Field

from .inventory_read import Provenance

# Extensible nutrient model: key → unit. Macros, micros and
# the nutrients that matter for a vegan-first diet.
NUTRIENTS = {
    "calories": "kcal",
    "protein_g": "g",
    "carbs_g": "g",
    "fat_g": "g",
    "fiber_g": "g",
    "sugars_g": "g",
    "sat_fat_g": "g",
    "sodium_mg": "mg",
    "vit_a_ug": "ug",
    "vit_c_mg": "mg",
    "vit_d_ug": "ug",
    "vit_b12_ug": "ug",
    "vit_k_ug": "ug",
    "folate_ug": "ug",
    "iron_mg": "mg",
    "calcium_mg": "mg",
    "zinc_mg": "mg",
    "magnesium_mg": "mg",
    "potassium_mg": "mg",
    "iodine_ug": "ug",
    "omega3_g": "g",
}

VEGAN_STATUSES = ("vegan", "non_vegan", "unknown")

FOOD_SOURCES = (
    "manual",
    "food_database",
    "recipe",
    "product_label",
    "external",
    "ai_proposal",
)

# Illustrative daily reference targets for one adult. These
# are user-overridable placeholders with their context shown
# on every coverage answer — not personal advice.
DEFAULT_REFERENCE = {
    "source": "built-in illustrative default (adult, varied "
              "diet); override with your own targets",
    "population": "general adult placeholder",
    "targets": {
        "calories": 2200.0, "protein_g": 60.0,
        "carbs_g": 275.0, "fat_g": 75.0, "fiber_g": 30.0,
        "sugars_g": 50.0, "sat_fat_g": 20.0,
        "sodium_mg": 2000.0, "vit_c_mg": 95.0,
        "vit_b12_ug": 2.4, "iron_mg": 11.0,
        "calcium_mg": 1000.0, "zinc_mg": 10.0,
        "magnesium_mg": 350.0, "potassium_mg": 3500.0,
        "iodine_ug": 150.0, "omega3_g": 1.6,
    },
}


class NutritionRefusedError(ValueError):
    """Fail-closed nutrition validation."""


def now() -> str:
    import datetime
    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


def generate_food_id() -> str:
    return f"food_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def generate_meal_id() -> str:
    return f"meal_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


class Food(BaseModel):
    food_id: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    nutrients: dict[str, float] = Field(default_factory=dict)
    vegan_status: str = Field(default="unknown",
                              max_length=20)
    vegan_evidence: str = Field(default="", max_length=500)
    source: str = Field(default="manual", max_length=20)
    provenance: Provenance
    created_at: str = Field(default="", max_length=80)


class MealItem(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    food_id: str = Field(default="", max_length=80)
    portion_g: float = Field(default=100.0, gt=0, le=5000)
    nutrients: dict[str, float] = Field(default_factory=dict)
    vegan_status: str = Field(default="unknown",
                              max_length=20)


class Meal(BaseModel):
    meal_id: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    items: list[MealItem] = Field(default_factory=list,
                                  max_length=30)
    totals: dict[str, float] = Field(default_factory=dict)
    vegan_status: str = Field(default="unknown",
                              max_length=20)
    source: str = Field(default="manual", max_length=20)
    provenance: Provenance
    observed_at: str = Field(default="", max_length=80)
    created_at: str = Field(default="", max_length=80)


def _check_nutrients(nutrients: dict) -> dict[str, float]:
    if not isinstance(nutrients, dict):
        raise NutritionRefusedError("nutrients must be an object")
    if len(nutrients) > len(NUTRIENTS):
        raise NutritionRefusedError("nutrient object too large")
    cleaned: dict[str, float] = {}
    for key, value in nutrients.items():
        if key not in NUTRIENTS:
            raise NutritionRefusedError(
                f"Unknown nutrient '{key}'")
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise NutritionRefusedError(
                f"nutrient '{key}' must be numeric")
        if number != number or number < 0 or number > 10**7:
            raise NutritionRefusedError(
                f"nutrient '{key}' out of range")
        cleaned[key] = round(number, 3)
    return cleaned


def _check_vegan(status: str, evidence: str) -> str:
    if status not in VEGAN_STATUSES:
        raise NutritionRefusedError(
            f"Unknown vegan status '{status}'")
    if status in ("vegan", "non_vegan") and not \
            str(evidence or "").strip():
        raise NutritionRefusedError(
            "a vegan/non-vegan claim needs explicit evidence "
            "(ingredient list, label or source); never guess")
    return status


def new_food(name: str, nutrients: dict, *,
             vegan_status: str = "unknown",
             vegan_evidence: str = "",
             source: str = "manual",
             provenance: Provenance | None = None) -> Food:
    if not isinstance(name, str) or not name.strip():
        raise NutritionRefusedError("food needs a name")
    if source not in FOOD_SOURCES:
        raise NutritionRefusedError(f"Unknown source '{source}'")
    return Food(
        food_id=generate_food_id(), name=name.strip()[:200],
        nutrients=_check_nutrients(nutrients or {}),
        vegan_status=_check_vegan(vegan_status,
                                  vegan_evidence),
        vegan_evidence=str(vegan_evidence or "")[:500],
        source=source,
        provenance=provenance or Provenance(
            source_type="user-created"
            if source == "manual" else "ai-generated",
            creator_id=f"nutrition:{source}",
            human_verified=source in ("manual", "product_label",
                                      "recipe")),
        created_at=now())


def scale_nutrients(nutrients: dict, portion_g: float,
                    base_g: float = 100.0) -> dict[str, float]:
    """Scale a per-100g profile to a portion. Pure math."""
    try:
        factor = float(portion_g) / float(base_g)
    except (TypeError, ValueError, ZeroDivisionError):
        raise NutritionRefusedError("portion must be numeric")
    if factor <= 0 or factor > 50:
        raise NutritionRefusedError("portion out of range")
    return {key: round(value * factor, 3)
            for key, value in nutrients.items()}


def new_meal(name: str, items: list[dict], *,
             source: str = "manual",
             observed_at: str = "",
             provenance: Provenance | None = None) -> Meal:
    """One meal from portioned items. Totals are computed,
    vegan status folds to the weakest claim (unknown beats
    vegan; non_vegan dominates)."""
    if not isinstance(name, str) or not name.strip():
        raise NutritionRefusedError("meal needs a name")
    if not isinstance(items, list) or not items or \
            len(items) > 30:
        raise NutritionRefusedError(
            "meal needs 1..30 items")
    if source not in FOOD_SOURCES:
        raise NutritionRefusedError(f"Unknown source '{source}'")
    parsed: list[MealItem] = []
    totals: dict[str, float] = {}
    statuses: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            raise NutritionRefusedError(
                "meal items must be objects")
        nutrients = _check_nutrients(raw.get("nutrients") or {})
        try:
            portion = float(raw.get("portion_g", 100.0))
        except (TypeError, ValueError):
            raise NutritionRefusedError(
                "portion_g must be numeric")
        scaled = scale_nutrients(nutrients, portion)
        for key, value in scaled.items():
            totals[key] = round(totals.get(key, 0.0) + value, 3)
        status = str(raw.get("vegan_status", "unknown"))
        if status not in VEGAN_STATUSES:
            raise NutritionRefusedError(
                f"Unknown vegan status '{status}'")
        statuses.add(status)
        parsed.append(MealItem(
            name=str(raw.get("name", "item"))[:200],
            food_id=str(raw.get("food_id", ""))[:80],
            portion_g=portion, nutrients=scaled,
            vegan_status=status))
    if "non_vegan" in statuses:
        meal_status = "non_vegan"
    elif "unknown" in statuses:
        meal_status = "unknown"
    else:
        meal_status = "vegan"
    stamp = now()
    return Meal(
        meal_id=generate_meal_id(), name=name.strip()[:200],
        items=parsed, totals=totals, vegan_status=meal_status,
        source=source,
        provenance=provenance or Provenance(
            source_type="user-created"
            if source == "manual" else "ai-generated",
            creator_id=f"nutrition:{source}",
            human_verified=source == "manual"),
        observed_at=observed_at or stamp, created_at=stamp)


def save_food(food: Food) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO foods
        (food_id, name, nutrients, vegan_status,
         vegan_evidence, source, provenance, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(food_id) DO NOTHING""",
                     (food.food_id, food.name,
                      dump(food.nutrients), food.vegan_status,
                      food.vegan_evidence, food.source,
                      dump(food.provenance.model_dump(
                          mode="json")), food.created_at))


def get_food(food_id: str) -> Food | None:
    from .database import chat_connection, init_chat_database, load
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM foods WHERE food_id=?",
                         (food_id,)).fetchone()
    if row is None:
        return None
    return Food(food_id=row["food_id"], name=row["name"],
                nutrients=load(row["nutrients"]),
                vegan_status=row["vegan_status"],
                vegan_evidence=row["vegan_evidence"],
                source=row["source"],
                provenance=Provenance(**load(row["provenance"])),
                created_at=row["created_at"])


def find_food(name: str) -> Food | None:
    from .database import chat_connection, init_chat_database, load
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM foods WHERE lower(name)"
                         "=lower(?) LIMIT 1",
                         (name,)).fetchone()
    if row is None:
        return None
    return Food(food_id=row["food_id"], name=row["name"],
                nutrients=load(row["nutrients"]),
                vegan_status=row["vegan_status"],
                vegan_evidence=row["vegan_evidence"],
                source=row["source"],
                provenance=Provenance(**load(row["provenance"])),
                created_at=row["created_at"])


def save_meal(meal: Meal) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO meals
        (meal_id, name, items, source, provenance,
         observed_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(meal_id) DO NOTHING""",
                     (meal.meal_id, meal.name,
                      dump([item.model_dump(mode="json")
                            for item in meal.items]),
                      meal.source,
                      dump(meal.provenance.model_dump(
                          mode="json")),
                      meal.observed_at, meal.created_at))


def list_meals(*, since: str = "",
               limit: int = 50) -> list[Meal]:
    from .database import chat_connection, init_chat_database, load
    init_chat_database()
    clauses, params = [], []
    if since:
        clauses.append("observed_at>?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with chat_connection() as db:
        rows = db.execute(
            f"SELECT * FROM meals {where} ORDER BY observed_at "
            f"DESC LIMIT ?",
            (*params, max(1, min(int(limit or 50), 200)))
        ).fetchall()
    meals = []
    for row in rows:
        items = [MealItem(**item) for item in load(row["items"])]
        totals: dict[str, float] = {}
        for item in items:
            for key, value in item.nutrients.items():
                totals[key] = round(
                    totals.get(key, 0.0) + value, 3)
        statuses = {item.vegan_status for item in items}
        status = "non_vegan" if "non_vegan" in statuses \
            else "unknown" if "unknown" in statuses else "vegan"
        meals.append(Meal(
            meal_id=row["meal_id"], name=row["name"],
            items=items, totals=totals, vegan_status=status,
            source=row["source"],
            provenance=Provenance(**load(row["provenance"])),
            observed_at=row["observed_at"],
            created_at=row["created_at"]))
    return meals


def daily_totals(day: str) -> dict:
    """Sum all meals whose observed_at falls on YYYY-MM-DD."""
    if not isinstance(day, str) or len(day) != 10:
        raise NutritionRefusedError(
            "day must be YYYY-MM-DD")
    totals: dict[str, float] = {}
    count = 0
    for meal in list_meals(limit=200):
        if str(meal.observed_at)[:10] != day:
            continue
        count += 1
        for key, value in meal.totals.items():
            totals[key] = round(totals.get(key, 0.0) + value, 3)
    return {"day": day, "meals": count, "totals": totals}


def weekly_trend(end_day: str) -> dict:
    """Seven daily totals ending on end_day (YYYY-MM-DD)."""
    import datetime
    try:
        end = datetime.date.fromisoformat(end_day)
    except ValueError:
        raise NutritionRefusedError(
            "end_day must be YYYY-MM-DD")
    days = [(end - datetime.timedelta(days=offset)).isoformat()
            for offset in range(6, -1, -1)]
    return {"end_day": end_day,
            "days": [daily_totals(day) for day in days]}


def coverage_for(totals: dict, *,
                 targets: dict | None = None,
                 reference: dict | None = None) -> dict:
    """Actual vs reference: adequate/possibly low/possibly
    high/unknown per nutrient, with source, context,
    calculation and uncertainty on every answer."""
    ref = reference or DEFAULT_REFERENCE
    wanted = targets or ref.get("targets", {})
    result = {}
    for nutrient in NUTRIENTS:
        actual = float((totals or {}).get(nutrient, 0.0))
        target = wanted.get(nutrient)
        if target is None or float(target) <= 0:
            result[nutrient] = {
                "status": "unknown", "actual": actual,
                "target": None,
                "reason": "no reference target configured"}
            continue
        ratio = actual / float(target)
        if 0.9 <= ratio <= 1.1:
            status = "adequate"
        elif ratio < 0.9:
            status = "possibly low"
        else:
            status = "possibly high"
        result[nutrient] = {
            "status": status, "actual": actual,
            "target": float(target),
            "ratio": round(ratio, 3),
            "calculation": f"actual/target = {actual}/"
                           f"{float(target)}"}
    return {
        "nutrients": result,
        "reference_source": ref.get("source", ""),
        "reference_population": ref.get("population", ""),
        "uncertainty": "single-day totals vary; labels, "
                       "portions and database values are "
                       "approximate; this is arithmetic, not "
                       "personal advice",
    }
