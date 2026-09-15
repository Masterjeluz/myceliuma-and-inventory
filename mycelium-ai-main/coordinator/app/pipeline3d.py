"""Object-to-3D pipeline contracts (Fase O, interface only).

Direction for the next big feature:

photo/import -> vision analysis -> object proposal -> human
verification -> INVENTory object -> 3D feasibility -> generation
task -> CAD/mesh File -> preview -> human verification.

For this slice only the contracts exist, deliberately without any
generator: there is no fake 3D output here, no cloud call, no
printer, no G-code, no physical hardware. Generation methods are a
closed literal with local-only values; anything cloud- or
hardware-shaped is refused at validation.

Stages (tested):

- PipelineStage is a closed literal; unknown stages fail closed.
- a StageRecord pins stage + status + references to INVENTory IDs
  (xxx_ prefixes where they apply) + unverified provenance.
- Feasibility3D advises printable/not-printable with concerns; it is
  AI output, never a production release.
- Generation3DRequest only allows method "local-template" (a future
  local adapter hook) and refuses printer/gcode/physical flags even
  when a caller tries to smuggle them in via extra fields
  (extra=forbid) or method names.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .inventory_read import Provenance

PipelineStage = Literal[
    "photo_import", "vision_analysis", "object_proposal",
    "human_verification", "inventory_object", "feasibility",
    "generation_task", "cad_mesh_file", "preview", "final_verification",
]
VALID_STAGES = frozenset({
    "photo_import", "vision_analysis", "object_proposal",
    "human_verification", "inventory_object", "feasibility",
    "generation_task", "cad_mesh_file", "preview", "final_verification",
})

StageStatus = Literal["pending", "ready", "done", "rejected", "blocked"]
VALID_STAGE_STATUSES = frozenset(
    {"pending", "ready", "done", "rejected", "blocked"})

GenerationMethod = Literal["local-template"]
VALID_METHODS = frozenset({"local-template"})

PHYSICAL_METHODS = frozenset(
    {"cloud", "printer", "gcode", "remote", "external-printer",
     "direct-print", "auto"})


class StageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(min_length=3, max_length=80)
    stage: str = Field(min_length=1, max_length=40)
    status: str = Field(min_length=1, max_length=20)
    references: dict[str, str] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=2000)
    provenance: Provenance = Field(default_factory=Provenance)


class Feasibility3D(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str = Field(min_length=3, max_length=80)
    printable: bool = False
    concerns: list[str] = Field(default_factory=list, max_length=20)
    suggested_method: str = "local-template"
    provenance: Provenance = Field(default_factory=Provenance)


class Generation3DRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=3, max_length=80)
    object_id: str = Field(min_length=3, max_length=80)
    method: str = Field(min_length=1, max_length=40)
    parameters: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance = Field(default_factory=Provenance)


def new_stage_record(record_id: str, stage: str, status: str, *,
                     references: dict | None = None,
                     notes: str = "") -> StageRecord:
    if stage not in VALID_STAGES:
        raise ValueError(f"Unknown pipeline stage '{stage}'")
    if status not in VALID_STAGE_STATUSES:
        raise ValueError(f"Unknown stage status '{status}'")
    refs = dict(references or {})
    for key, value in refs.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Stage references must be non-empty text")
    return StageRecord(
        record_id=record_id, stage=stage, status=status, references=refs,
        notes=str(notes or "")[:2000],
        provenance=Provenance(
            source_type="ai-generated", creator_id="pipeline-3d",
            human_verified=False,
            notes="pipeline contract only; no geometry generated"))


def new_feasibility(object_id: str, printable: bool,
                    concerns: list[str] | None = None) -> Feasibility3D:
    cleaned = [str(item).strip()[:200] for item in (concerns or [])
               if str(item).strip()][:20]
    return Feasibility3D(
        object_id=object_id, printable=bool(printable),
        concerns=cleaned, suggested_method="local-template",
        provenance=Provenance(
            source_type="ai-generated", creator_id="pipeline-3d",
            human_verified=False,
            notes="feasibility advice only; never a production release"))


def new_generation_request(request_id: str, object_id: str,
                           method: str,
                           parameters: dict | None = None) -> Generation3DRequest:
    lowered = str(method or "").strip().lower()
    if lowered in PHYSICAL_METHODS:
        raise ValueError(
            f"Method '{method}' implies cloud/printer/hardware; refusing")
    if lowered not in VALID_METHODS:
        raise ValueError(
            f"Unknown generation method '{method}'; "
            "only local-template exists (interface only)")
    params = dict(parameters or {})
    for banned in ("gcode", "printer", "port", "device", "execute",
                   "auto_print", "cloud_key"):
        if banned in params:
            raise ValueError(
                f"Parameter '{banned}' implies physical execution; refusing")
    return Generation3DRequest(
        request_id=request_id, object_id=object_id, method=lowered,
        parameters=params,
        provenance=Provenance(
            source_type="ai-generated", creator_id="pipeline-3d",
            human_verified=False,
            notes="generation interface only; no geometry produced, "
                  "no hardware touched"))
