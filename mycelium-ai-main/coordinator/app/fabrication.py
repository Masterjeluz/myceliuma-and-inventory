"""Automated fabrication orchestration (BIG #11-15, Phase 4).

IDEA → CAD → MESH → VALIDATION → SLICING → GCODE →
PRINTER → PRINT → CAMERA → TELEMETRY → VERIFICATION →
INVENTory. Every existing safety gate stays mandatory; this
module only plans, predicts and selects — the physical start
still needs the explicit approval in fab_flow (propose_print
→ execute_print), no exceptions.

Filament is a local resource record (material/color/
remaining/spool/compatibility/location): the system can
predict "enough filament?" but never claims a sensor value
is certain without provenance.
"""

import secrets
import time

from pydantic import BaseModel, Field

from .inventory_read import Provenance

FILAMENT_DENSITIES = {
    "PLA": 1.24,
    "PETG": 1.27,
    "ABS": 1.04,
    "TPU": 1.21,
}

PIPELINE_STAGES = (
    "idea",
    "cad",
    "mesh",
    "validation",
    "slicing",
    "gcode",
    "printer_selection",
    "print_proposal",
    "print_approval",
    "print",
    "telemetry",
    "camera",
    "verification",
    "inventory",
)


class FabricationRefusedError(ValueError):
    """Fail-closed fabrication validation."""


def now() -> str:
    import datetime
    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


def generate_spool_id() -> str:
    return f"spl_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


class FilamentSpool(BaseModel):
    spool_id: str = Field(min_length=3, max_length=80)
    material: str = Field(min_length=1, max_length=20)
    color: str = Field(default="", max_length=40)
    diameter_mm: float = Field(default=1.75, gt=0, le=5)
    weight_remaining_g: float = Field(default=0.0, ge=0)
    compatible_profiles: list[str] = Field(
        default_factory=list, max_length=10)
    source: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=200)
    provenance: Provenance
    updated_at: str = Field(default="", max_length=80)


def new_spool(material: str, weight_g: float, *,
              color: str = "",
              diameter_mm: float = 1.75,
              compatible_profiles: list | None = None,
              source: str = "",
              location: str = "",
              provenance: Provenance | None = None
              ) -> FilamentSpool:
    if material not in FILAMENT_DENSITIES:
        raise FabricationRefusedError(
            f"Unknown material '{material}'; expected one of "
            f"{sorted(FILAMENT_DENSITIES)}")
    try:
        weight = float(weight_g)
    except (TypeError, ValueError):
        raise FabricationRefusedError("weight must be numeric")
    if not 0 <= weight <= 10000:
        raise FabricationRefusedError(
            "weight must be 0..10000g")
    return FilamentSpool(
        spool_id=generate_spool_id(), material=material,
        color=str(color or "")[:40],
        diameter_mm=float(diameter_mm),
        weight_remaining_g=weight,
        compatible_profiles=[
            str(item)[:40]
            for item in (compatible_profiles or [])][:10],
        source=str(source or "")[:200],
        location=str(location or "")[:200],
        provenance=provenance or Provenance(
            source_type="user-created", creator_id="filament",
            human_verified=False),
        updated_at=now())


def save_spool(spool: FilamentSpool) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO filament_spools
        (spool_id, material, color, diameter_mm,
         weight_remaining_g, compatible_profiles, source,
         location, provenance, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(spool_id) DO UPDATE SET
         weight_remaining_g=excluded.weight_remaining_g,
         location=excluded.location,
         updated_at=excluded.updated_at""",
                     (spool.spool_id, spool.material,
                      spool.color, spool.diameter_mm,
                      spool.weight_remaining_g,
                      dump(spool.compatible_profiles),
                      spool.source, spool.location,
                      dump(spool.provenance.model_dump(
                          mode="json")), spool.updated_at))


def _row_to_spool(row) -> FilamentSpool:
    from .database import load
    return FilamentSpool(
        spool_id=row["spool_id"], material=row["material"],
        color=row["color"], diameter_mm=row["diameter_mm"],
        weight_remaining_g=row["weight_remaining_g"],
        compatible_profiles=load(row["compatible_profiles"]),
        source=row["source"], location=row["location"],
        provenance=Provenance(**load(row["provenance"])),
        updated_at=row["updated_at"])


def list_spools() -> list[FilamentSpool]:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute("SELECT * FROM filament_spools ORDER "
                          "BY updated_at DESC LIMIT 100").fetchall()
    return [_row_to_spool(row) for row in rows]


def deduct_spool(spool_id: str, grams: float, *, reason: str,
                 usage_key: str) -> dict:
    """Deduct filament exactly once (M3.5/BIG57 accounting gate).

    Idempotent on ``usage_key`` (PRIMARY KEY): replaying the same
    key returns the existing record without deducting again.
    Refuses unknown spools, non-positive amounts and insufficient
    stock. NOTHING calls this yet — M4 physical execution will
    call it once per completed print with key
    f"print:{task_id}". Queueing/proposing/cancelling never
    deduct (proven by tests, enforced by absence of callers).
    """
    import re as _re
    from .database import chat_connection, init_chat_database
    cleaned_id = str(spool_id or "").strip()[:80]
    cleaned_key = str(usage_key or "").strip()[:120]
    cleaned_reason = str(reason or "").strip()[:200]
    if not cleaned_id:
        raise FabricationRefusedError("spool_id is required")
    if not cleaned_key or not _re.match(
            r"^[A-Za-z0-9_:-]{1,120}$", cleaned_key):
        raise FabricationRefusedError(
            "usage_key must match [A-Za-z0-9_:-]{1,120}")
    try:
        amount = float(grams)
    except (TypeError, ValueError):
        raise FabricationRefusedError(
            "grams must be numeric") from None
    if not amount > 0 or amount > 10000:
        raise FabricationRefusedError(
            "grams must be 0..10000 (exclusive 0)")
    if not cleaned_reason:
        raise FabricationRefusedError("reason is required")
    init_chat_database()
    with chat_connection() as db:
        seen = db.execute(
            "SELECT spool_id, grams, reason, created_at FROM "
            "filament_usage WHERE usage_key=?",
            (cleaned_key,)).fetchone()
        if seen is not None:
            return {"spool_id": seen["spool_id"],
                    "grams": seen["grams"],
                    "reason": seen["reason"],
                    "deducted": False,
                    "created_at": seen["created_at"]}
        row = db.execute("SELECT * FROM filament_spools WHERE "
                         "spool_id=?", (cleaned_id,)).fetchone()
        if row is None:
            raise FabricationRefusedError("spool not found")
        spool = _row_to_spool(row)
        remaining = float(spool.weight_remaining_g or 0.0)
        if remaining < amount:
            raise FabricationRefusedError(
                f"spool holds {remaining:g}g, needs {amount:g}g; "
                f"refusing")
        stamp = now()
        db.execute("INSERT INTO filament_usage "
                   "(usage_key, spool_id, grams, reason, "
                   "created_at) VALUES (?, ?, ?, ?, ?)",
                   (cleaned_key, cleaned_id, amount,
                    cleaned_reason, stamp))
        updated = spool.model_copy(update={
            "weight_remaining_g": round(remaining - amount, 2),
            "updated_at": stamp})
        db.execute("UPDATE filament_spools SET "
                   "weight_remaining_g=?, updated_at=? WHERE "
                   "spool_id=?",
                   (updated.weight_remaining_g, stamp, cleaned_id))
    return {"spool_id": cleaned_id, "grams": amount,
            "reason": cleaned_reason, "deducted": True,
            "remaining_g": updated.weight_remaining_g,
            "created_at": stamp}


#: Spool slot label: short printer-slot tag, no paths or spaces.
SLOT_PATTERN = r"^[A-Za-z0-9_-]{1,12}$"


def assign_spool_location(spool_id: str, printer_id: str = "",
                          slot: str = "") -> FilamentSpool:
    """Pin one spool to a printer + AMS slot (M1/BIG57).

    Stores ``printer_id/slot`` (or the bare slot for shelf stock)
    in the existing ``location`` field — no schema change. The
    printer must be registered when named; the slot is a short
    label, never a path. Compatibility enforcement happens at
    pre-flight (M3), not here.
    """
    import re as _re
    from .database import chat_connection, init_chat_database
    cleaned_id = str(spool_id or "").strip()[:80]
    cleaned_printer = str(printer_id or "").strip()[:80]
    cleaned_slot = str(slot or "").strip()[:12]
    if not cleaned_id:
        raise FabricationRefusedError("spool_id is required")
    if cleaned_slot and not _re.match(SLOT_PATTERN, cleaned_slot):
        raise FabricationRefusedError(
            "slot must match [A-Za-z0-9_-]{1,12}")
    if cleaned_printer:
        from .printer3d import list_stored_printers
        known = {str(printer.printer_id or "")
                 for printer in list_stored_printers() or []}
        if cleaned_printer not in known:
            raise FabricationRefusedError(
                f"printer '{cleaned_printer[:40]}' is not "
                f"registered; refusing")
        if not cleaned_slot:
            raise FabricationRefusedError(
                "a printer slot label is required with a printer")
        try:
            holders = [spool for spool in list_spools() or []
                       if str(getattr(spool, "location", "") or "")
                       == f"{cleaned_printer}/{cleaned_slot}"
                       and spool.spool_id != cleaned_id]
        except FabricationRefusedError as error:
            raise FabricationRefusedError(str(error)) from error
        if holders:
            raise FabricationRefusedError(
                f"slot '{cleaned_slot[:12]}' op "
                f"'{cleaned_printer[:40]}' bevat al "
                f"'{holders[0].spool_id[:24]}'; refusing")
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM filament_spools WHERE "
                         "spool_id=?", (cleaned_id,)).fetchone()
        if row is None:
            raise FabricationRefusedError("spool not found")
        spool = _row_to_spool(row)
    location = (f"{cleaned_printer}/{cleaned_slot}"
                if cleaned_printer else cleaned_slot)
    updated = spool.model_copy(update={"location": location,
                                       "updated_at": now()})
    save_spool(updated)
    return updated


def estimate_filament_g(volume_cm3: float, material: str, *,
                        infill: float = 0.2) -> dict:
    """Estimate grams from mesh volume. Arithmetic with the
    method shown — never presented as measured."""
    try:
        volume = float(volume_cm3)
        fill = float(infill)
    except (TypeError, ValueError):
        raise FabricationRefusedError(
            "volume/infill must be numeric")
    if volume < 0 or not 0 < fill <= 1.0:
        raise FabricationRefusedError(
            "volume must be >= 0, infill 0..1")
    density = FILAMENT_DENSITIES.get(material)
    if density is None:
        raise FabricationRefusedError(
            f"Unknown material '{material}'")
    grams = round(volume * density * fill, 2)
    return {"grams": grams, "material": material,
            "method": f"volume {volume}cm³ × density "
                      f"{density}g/cm³ × infill {fill}",
            "warning": "estimate from mesh math, not a scale "
                       "reading"}


def spool_check(spool_id: str, grams_needed: float) -> dict:
    """Can this spool cover the estimate? Answered with the
    remaining weight on record and its provenance."""
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM filament_spools WHERE "
                         "spool_id=?", (spool_id,)).fetchone()
    if row is None:
        raise FabricationRefusedError("spool not found")
    spool = _row_to_spool(row)
    try:
        needed = float(grams_needed)
    except (TypeError, ValueError):
        raise FabricationRefusedError("grams must be numeric")
    return {"spool_id": spool_id, "enough":
            spool.weight_remaining_g >= needed,
            "remaining_g": spool.weight_remaining_g,
            "needed_g": needed,
            "provenance": spool.provenance.model_dump(
                mode="json")}


def select_printer(requirements: dict) -> dict:
    """Deterministic printer choice over stored printers:
    capability match first, then explicit preference, then
    lowest printer_id. Returns the pick plus why — never a
    claim one printer is 'better'."""
    from .printer3d import list_stored_printers
    printers = list_stored_printers()
    if not printers:
        raise FabricationRefusedError(
            "no printers registered; register one first")
    wanted = set(requirements.get("capabilities", []) or [])
    profile = str(requirements.get("profile", "") or "")
    eligible = []
    for printer in printers:
        caps = set(printer.capabilities or [])
        if wanted and not wanted <= caps:
            continue
        eligible.append(printer)
    if not eligible:
        raise FabricationRefusedError(
            "no registered printer covers the required "
            "capabilities")
    preferred = str(requirements.get("printer_id", "") or "")
    for printer in sorted(eligible,
                          key=lambda item: item.printer_id):
        if preferred and printer.printer_id != preferred:
            continue
        return {"printer_id": printer.printer_id,
                "name": printer.name,
                "capabilities": sorted(
                    printer.capabilities or []),
                "why": "capability match"
                       + (" + explicit preference"
                          if preferred else "")
                       + "; deterministic lowest id on ties",
                "physical_start": "still gated: print proposal "
                                  "+ explicit approval required"}
    raise FabricationRefusedError(
        "preferred printer is not eligible")


def plan_pipeline(*, source_object_id: str = "",
                  source_idea_id: str = "",
                  profile: str = "draft-pla",
                  material: str = "PLA") -> dict:
    """Stage-by-stage fabrication plan as data. Preparation
    steps are actionable; the physical start is marked gated
    and never included as an action."""
    if not source_object_id and not source_idea_id:
        raise FabricationRefusedError(
            "pipeline needs a source object or idea")
    from .slicer3d import SLICER_PROFILES
    if profile not in SLICER_PROFILES:
        raise FabricationRefusedError(
            f"Unknown profile '{profile}'")
    if material not in FILAMENT_DENSITIES:
        raise FabricationRefusedError(
            f"Unknown material '{material}'")
    stages = []
    for stage in PIPELINE_STAGES:
        if stage in ("print",):
            action = "GATED: explicit approval via print "
            "proposal; never automatic"
        elif stage == "inventory":
            action = "record result via BIG #5 file proposal " \
                     "after independent verification"
        elif stage == "verification":
            action = "telemetry + camera, both required; " \
                     "telemetry never verifies alone"
        else:
            action = "preparable now"
        stages.append({"stage": stage, "action": action})
    return {"stages": stages,
            "source_object_id": source_object_id,
            "source_idea_id": source_idea_id,
            "profile": profile, "material": material,
            "gates": ["print proposal approval",
                      "physical start approval",
                      "independent verification"]}
