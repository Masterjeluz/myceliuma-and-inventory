"""Bed push-off sweep: knock a finished part off the plate.

EXPERIMENTAL, operator-present only. A travel-only G-code that
drives the toolhead slowly through the part location to push
one finished object off the bed. No heaters, no extrusion,
no homing into the part: the nozzle never goes below a safe
push height, so a missing part means harmless air moves.

Rules (fail-closed, tested):

- Pure builder: coordinates bounded to the bed, push height
  clamped between a floor (never bed-strike) and the part top
  (real contact), feeds capped. Anything outside refuses.
- The output must pass the existing ``validate_gcode`` as
  ``safe`` (allow-listed travel commands only); anything else
  never reaches a proposal.
- Execution stays entirely in the existing printer.execute
  flow (proposal -> exact YES -> revalidated execute ->
  start-confirm). This module moves nothing by itself.
- One part, one direction, one slow pass. No retries, no
  second sweep, no adjustments from telemetry here.
"""

from __future__ import annotations

BED_MM = 180.0
PUSH_FLOOR_Z = 2.0
TRAVEL_Z = 25.0
MAX_PUSH_FEED = 600
TRAVEL_FEED = 3000
APPROACH_FEED = 600


class PushOffRefusedError(ValueError):
    """Push sweep refused; nothing was built or stored."""


def _num(value, name: str, *, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise PushOffRefusedError(
            f"{name} must be numeric") from None
    if not low <= number <= high:
        raise PushOffRefusedError(
            f"{name} must be {low}..{high}")
    return number


def build_push_sweep(*, part_x: float = 90.0,
                     part_y: float = 90.0,
                     part_h: float = 20.0,
                     push_z: float = 8.0,
                     direction: str = "+x",
                     prime: bool = False,
                     prime_temp_c: float = 170.0) -> str:
    """Build the travel-only sweep G-code text.

    The toolhead approaches beside the part at clearance height,
    descends to ``push_z`` (below the part top, above the bed),
    makes ONE slow pass through the part center, lifts and parks.
    Cold nozzle, cold bed assumed (caller verifies temperatures).

    With ``prime=True`` the file also heats to a mild
    ``prime_temp_c`` and lays one short prime line at the front
    edge first: some firmware ignores extrusion-less files, and a
    prime makes it a real (tiny) print. The prime stays far from
    the part and uses no bed heating.
    """
    cx = _num(part_x, "part_x", low=20.0, high=BED_MM - 20.0)
    cy = _num(part_y, "part_y", low=20.0, high=BED_MM - 20.0)
    height = _num(part_h, "part_h", low=2.0, high=60.0)
    contact = _num(push_z, "push_z", low=PUSH_FLOOR_Z,
                   high=height)
    heading = str(direction or "").strip().lower()
    if heading not in ("+x", "-x"):
        raise PushOffRefusedError(
            "direction must be +x or -x")
    if heading == "+x":
        start_x, end_x = 20.0, BED_MM - 20.0
    else:
        start_x, end_x = BED_MM - 20.0, 20.0
    heat = _num(prime_temp_c, "prime_temp_c", low=0.0,
                high=220.0)
    lines = [
        "; Mycelium push-off sweep EXPERIMENTAL",
        "; travel-only unless prime=True (short edge prime)",
        f"; part center X{cx:.1f} Y{cy:.1f} height {height:.1f}",
        "G21 ; millimeters",
        "G90 ; absolute positioning",
    ]
    if prime:
        lines += [
            f"M104 S{heat:.0f} ; mild prime temp, no bed heating",
            "G28 ; home",
            "G1 Z5.0 F600 ; low prime height at front edge",
            "G1 X10.0 Y10.0 F3000 ; prime corner",
            "G4 S45 ; let the nozzle reach prime temp",
            "G92 E0 ; reset extruder",
            "G1 X60.0 Y10.0 E8.0 F300 ; short prime line",
            "G92 E0 ; reset extruder",
            f"M104 S0 ; heater off",
        ]
    else:
        lines += [
            "G28 ; home (part is at center, clear of endstops)",
        ]
    lines += [
        f"G1 Z{TRAVEL_Z:.1f} F{APPROACH_FEED} ; clearance",
        f"G1 X{start_x:.1f} Y{cy:.1f} F{TRAVEL_FEED} ; approach",
        f"G1 Z{contact:.1f} F{APPROACH_FEED} ; push height",
        f"G1 X{end_x:.1f} Y{cy:.1f} F{MAX_PUSH_FEED} ; ONE slow push",
        f"G1 Z{TRAVEL_Z:.1f} F{APPROACH_FEED} ; lift",
        f"G1 X{cx:.1f} Y{cy:.1f} F{TRAVEL_FEED} ; park",
        "M84 ; steppers off",
    ]
    return "\n".join(lines) + "\n"


def build_push_tail(*, part_x: float = 90.0,
                    part_y: float = 90.0,
                    part_h: float = 20.0,
                    push_z: float = 8.0,
                    direction: str = "+x",
                    wait_bed_c: float = 35.0) -> str:
    """Appendable tail: bed-cooldown wait + ONE slow push + park.

    Meant to follow a finished sliced print (its end code already
    ran): lift to clearance first (always safe upward), re-home,
    wait for the bed to reach release temperature, then the same
    single push as :func:`build_push_sweep`. Same bounds, same
    travel-only commands plus ``M190`` (bed wait, capped).
    """
    cx = _num(part_x, "part_x", low=20.0, high=BED_MM - 20.0)
    cy = _num(part_y, "part_y", low=20.0, high=BED_MM - 20.0)
    height = _num(part_h, "part_h", low=2.0, high=60.0)
    contact = _num(push_z, "push_z", low=PUSH_FLOOR_Z,
                   high=height)
    release = _num(wait_bed_c, "wait_bed_c", low=20.0,
                   high=60.0)
    heading = str(direction or "").strip().lower()
    if heading not in ("+x", "-x"):
        raise PushOffRefusedError(
            "direction must be +x or -x")
    if heading == "+x":
        start_x, end_x = 20.0, BED_MM - 20.0
    else:
        start_x, end_x = BED_MM - 20.0, 20.0
    lines = [
        "; Mycelium print+push tail: cooldown wait + ONE push",
        "G90 ; absolute positioning",
        f"G1 Z{TRAVEL_Z:.1f} F{APPROACH_FEED} ; clearance first",
        "G28 ; re-home from height",
        f"M190 R{release:.0f} ; wait for bed release temp",
        f"G1 X{start_x:.1f} Y{cy:.1f} F{TRAVEL_FEED} ; approach",
        f"G1 Z{contact:.1f} F{APPROACH_FEED} ; push height",
        f"G1 X{end_x:.1f} Y{cy:.1f} F{MAX_PUSH_FEED} ; ONE slow push",
        f"G1 Z{TRAVEL_Z:.1f} F{APPROACH_FEED} ; lift",
        f"G1 X{cx:.1f} Y{cy:.1f} F{TRAVEL_FEED} ; park",
        "M84 ; steppers off",
    ]
    return "\n".join(lines) + "\n"


def store_push_gcode(filename: str, text: str) -> tuple[str, bytes]:
    """Store built sweep text as a fabrication artifact."""
    from .mesh3d import artifact_path, check_artifact_ref
    from .slicer3d import MAX_GCODE_BYTES, SlicerRefusedError
    reference = check_artifact_ref(filename)
    if not reference.lower().endswith(".gcode"):
        raise SlicerRefusedError(
            "push sweep must be a .gcode file")
    data = text.encode("utf-8")
    if not data:
        raise SlicerRefusedError("push sweep is empty; refusing")
    if len(data) > MAX_GCODE_BYTES:
        raise SlicerRefusedError("push sweep exceeds size cap")
    path = artifact_path(reference)
    with open(path, "wb") as handle:
        handle.write(data)
    return reference, data
