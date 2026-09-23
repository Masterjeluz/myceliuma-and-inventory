"""Screen observations: what the desktop agent sees (Fase H).

An observation is metadata about one screenshot, never the pixels
themselves: an ID, a timestamp, screen dimensions, an optional local
file reference, and optional active-window metadata. Screenshots stay
on the local machine (temporary directory, bounded retention) and are
never uploaded: there is no cloud field, no external-AI flag, and no
function here sends anything anywhere.

Rules (tested):

- dimensions must be positive integers within sane bounds.
- image_ref, when present, must be a plain local filename (no
  directories, no URLs, no schemes); the runtime resolves it inside
  its own observation directory.
- active window titles are capped text; nothing secret is expected
  and nothing is parsed out of them.
- observations are ephemeral: helpers expose retention bounds, the
  runtime prunes beyond OBSERVATION_RETENTION.
"""

from pydantic import BaseModel, ConfigDict, Field

from .inventory_read import Provenance

MAX_DIMENSION = 16384
MAX_TITLE_CHARS = 200
MAX_REF_CHARS = 200
OBSERVATION_RETENTION = 5


class ScreenObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str = Field(min_length=3, max_length=80)
    created_at: str = ""
    width: int = Field(ge=1, le=MAX_DIMENSION)
    height: int = Field(ge=1, le=MAX_DIMENSION)
    image_ref: str = Field(default="", max_length=MAX_REF_CHARS)
    active_window: str = Field(default="", max_length=MAX_TITLE_CHARS)
    provenance: Provenance = Field(default_factory=Provenance)


def check_image_ref(value: str) -> str:
    """Local filename only: no paths, URLs or schemes. Fail-closed."""
    if not isinstance(value, str):
        raise ValueError("image_ref must be text")
    text = value.strip()
    if not text:
        return ""
    if len(text) > MAX_REF_CHARS:
        raise ValueError("image_ref too long")
    lowered = text.lower()
    if ("://" in lowered or text.startswith("\\\\")
            or text.startswith("/") or ":" in text):
        raise ValueError("image_ref must be a plain local filename")
    if ".." in text or "/" in text or "\\" in text:
        raise ValueError("image_ref must not contain a path")
    if not text.lower().endswith((".bmp", ".png", ".jpg", ".jpeg")):
        raise ValueError("image_ref must be a .bmp, .png, .jpg or .jpeg file")
    return text


def new_observation(observation_id: str, width: int, height: int, *,
                    image_ref: str = "",
                    active_window: str = "") -> ScreenObservation:
    if not isinstance(width, int) or isinstance(width, bool):
        raise ValueError("width must be an integer")
    if not isinstance(height, int) or isinstance(height, bool):
        raise ValueError("height must be an integer")
    if not 1 <= width <= MAX_DIMENSION or not 1 <= height <= MAX_DIMENSION:
        raise ValueError("observation dimensions out of range")
    return ScreenObservation(
        observation_id=observation_id,
        width=width,
        height=height,
        image_ref=check_image_ref(image_ref),
        active_window=str(active_window or "")[:MAX_TITLE_CHARS],
        provenance=Provenance(
            source_type="sensor-observed",
            creator_id="desktop-agent",
            human_verified=False,
            notes="local screenshot metadata only; pixels never leave "
                  "the machine",
        ),
    )
