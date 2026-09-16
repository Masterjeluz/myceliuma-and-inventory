"""Skills domain (BIG #11-15, Phase 3).

A skill is evidence-based: DISCOVERED → INTERESTED →
LEARNING → PRACTICING → APPLIED → DEMONSTRATED → MASTERED.
Stages advance on evidence, never on AI claims; the top two
stages need human confirmation.

Research/project context may only produce SkillCandidates
(candidate ≠ owned skill). A candidate becomes a skill
through explicit user acceptance.
"""

import secrets
import time

from pydantic import BaseModel, Field

from .inventory_read import Provenance

SKILL_STAGES = (
    "discovered",
    "interested",
    "learning",
    "practicing",
    "applied",
    "demonstrated",
    "mastered",
)

PROFICIENCIES = (
    "unknown",
    "novice",
    "competent",
    "proficient",
    "expert",
)

# Deterministic discovery map: keyword → skill suggestion.
# A suggestion is a candidate with evidence, never a skill.
DISCOVERY_KEYWORDS = {
    "3d print": "3D printing",
    "robotic arm": "robotics",
    "robot": "robotics",
    "cad": "CAD",
    "mesh": "mesh repair",
    "slic": "slicer configuration",
    "electronic": "electronics",
    "motor": "motors",
    "control": "control systems",
    "python": "Python",
    "fabricat": "fabrication",
    "vegan": "vegan nutrition",
    "recipe": "recipe development",
    "danc": "dancing",
    "skate": "skating",
    "freerun": "freerunning",
    "solar": "sustainable design",
    "camera": "photography",
    "garmin": "endurance training",
    "drone": "drone operation",
}


class SkillRefusedError(ValueError):
    """Fail-closed skill validation."""


def now() -> str:
    import datetime
    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


def generate_skill_id() -> str:
    return f"skl_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def generate_candidate_id() -> str:
    return f"skc_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


class SkillEvidence(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    ref: str = Field(min_length=1, max_length=200)
    observed_at: str = Field(default="", max_length=80)
    note: str = Field(default="", max_length=300)


class Skill(BaseModel):
    skill_id: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=1000)
    prerequisites: list[str] = Field(default_factory=list,
                                     max_length=20)
    related_skills: list[str] = Field(default_factory=list,
                                      max_length=20)
    stage: str = Field(default="discovered", max_length=20)
    proficiency: str = Field(default="unknown", max_length=20)
    evidence: list[SkillEvidence] = Field(default_factory=list,
                                          max_length=50)
    source: str = Field(default="", max_length=200)
    provenance: Provenance
    project_refs: list[str] = Field(default_factory=list,
                                    max_length=20)
    created_at: str = Field(default="", max_length=80)
    updated_at: str = Field(default="", max_length=80)


class SkillCandidate(BaseModel):
    candidate_id: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    evidence: list[str] = Field(default_factory=list,
                                max_length=10)
    project_ref: str = Field(default="", max_length=100)
    status: str = Field(default="proposed", max_length=20)
    created_at: str = Field(default="", max_length=80)


def new_skill(name: str, *, category: str = "",
              description: str = "",
              prerequisites: list | None = None,
              related_skills: list | None = None,
              stage: str = "discovered",
              proficiency: str = "unknown",
              project_refs: list | None = None,
              source: str = "",
              provenance: Provenance | None = None
              ) -> Skill:
    if not isinstance(name, str) or not name.strip():
        raise SkillRefusedError("skill needs a name")
    if stage not in SKILL_STAGES:
        raise SkillRefusedError(f"Unknown stage '{stage}'")
    if proficiency not in PROFICIENCIES:
        raise SkillRefusedError(
            f"Unknown proficiency '{proficiency}'")
    if stage in ("demonstrated", "mastered"):
        raise SkillRefusedError(
            "top stages need evidence + human confirmation; "
            "use advance_skill()")
    stamp = now()
    return Skill(
        skill_id=generate_skill_id(), name=name.strip()[:200],
        category=str(category or "")[:80],
        description=str(description or "")[:1000],
        prerequisites=[str(item)[:80]
                       for item in (prerequisites or [])][:20],
        related_skills=[str(item)[:80]
                        for item in (related_skills or [])][:20],
        stage=stage, proficiency=proficiency, evidence=[],
        source=str(source or "")[:200],
        provenance=provenance or Provenance(
            source_type="user-created", creator_id="skills",
            human_verified=False),
        project_refs=[str(item)[:100]
                      for item in (project_refs or [])][:20],
        created_at=stamp, updated_at=stamp)


def _row_to_skill(row) -> Skill:
    from .database import load
    return Skill(
        skill_id=row["skill_id"], name=row["name"],
        category=row["category"],
        description=row["description"],
        prerequisites=load(row["prerequisites"]),
        related_skills=load(row["related_skills"]),
        stage=row["stage"], proficiency=row["proficiency"],
        evidence=[SkillEvidence(**item)
                  for item in load(row["evidence"])],
        source=row["source"],
        provenance=Provenance(**load(row["provenance"])),
        project_refs=load(row["project_refs"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"])


def save_skill(skill: Skill) -> None:
    """Persist a skill. Stage/evidence invariants hold here,
    not only in the routes: applied needs evidence,
    demonstrated/mastered need ≥2 evidence plus verified
    provenance. A future caller cannot bypass the gates by
    writing directly."""
    if skill.stage not in SKILL_STAGES:
        raise SkillRefusedError(
            f"Unknown stage '{skill.stage}'")
    if skill.proficiency not in PROFICIENCIES:
        raise SkillRefusedError(
            f"Unknown proficiency '{skill.proficiency}'")
    if skill.stage == "applied" and len(skill.evidence) < 1:
        raise SkillRefusedError(
            "applied needs at least one evidence entry")
    if skill.stage in ("demonstrated", "mastered"):
        if len(skill.evidence) < 2:
            raise SkillRefusedError(
                f"{skill.stage} needs at least two evidence "
                "entries")
        if not skill.provenance.human_verified:
            raise SkillRefusedError(
                f"{skill.stage} needs verified provenance")
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO skills
        (skill_id, name, category, description,
         prerequisites, related_skills, stage, proficiency,
         evidence, source, provenance, project_refs,
         created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(skill_id) DO UPDATE SET
         stage=excluded.stage,
         proficiency=excluded.proficiency,
         evidence=excluded.evidence,
         project_refs=excluded.project_refs,
         updated_at=excluded.updated_at""",
                     (skill.skill_id, skill.name,
                      skill.category, skill.description,
                      dump(skill.prerequisites),
                      dump(skill.related_skills), skill.stage,
                      skill.proficiency,
                      dump([item.model_dump(mode="json")
                            for item in skill.evidence]),
                      skill.source,
                      dump(skill.provenance.model_dump(
                          mode="json")),
                      dump(skill.project_refs),
                      skill.created_at, skill.updated_at))


def get_skill(skill_id: str) -> Skill | None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM skills WHERE skill_id=?",
                         (skill_id,)).fetchone()
    return _row_to_skill(row) if row is not None else None


def list_skills(*, stage: str = "",
                limit: int = 100) -> list[Skill]:
    from .database import chat_connection, init_chat_database
    if stage and stage not in SKILL_STAGES:
        raise SkillRefusedError(f"Unknown stage '{stage}'")
    init_chat_database()
    with chat_connection() as db:
        if stage:
            rows = db.execute(
                "SELECT * FROM skills WHERE stage=? ORDER BY "
                "updated_at DESC LIMIT ?",
                (stage, max(1, min(int(limit or 100),
                                   200)))).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM skills ORDER BY updated_at DESC "
                "LIMIT ?", (max(1, min(int(limit or 100),
                                       200)),)).fetchall()
    return [_row_to_skill(row) for row in rows]


def add_evidence(skill_id: str, kind: str, ref: str, *,
                 note: str = "") -> Skill:
    """Attach one evidence entry. Evidence is data, never a
    stage jump by itself."""
    skill = get_skill(skill_id)
    if skill is None:
        raise SkillRefusedError("skill not found")
    if not isinstance(kind, str) or not kind.strip() or \
            len(kind) > 40:
        raise SkillRefusedError("evidence kind must be text")
    if not isinstance(ref, str) or not ref.strip() or \
            len(ref) > 200:
        raise SkillRefusedError("evidence ref must be text")
    entry = SkillEvidence(kind=kind.strip()[:40],
                          ref=ref.strip()[:200],
                          observed_at=now(),
                          note=str(note or "")[:300])
    updated = skill.model_copy(update={
        "evidence": [*skill.evidence, entry][:50],
        "updated_at": now()})
    save_skill(updated)
    return updated


def advance_skill(skill_id: str, to_stage: str, *,
                  confirmed_by: str = "") -> Skill:
    """One stage forward. 'applied' needs ≥1 evidence;
    'demonstrated'/'mastered' need ≥2 evidence plus a human
    confirmer. Never backwards, never skipping."""
    order = list(SKILL_STAGES)
    if to_stage not in order:
        raise SkillRefusedError(f"Unknown stage '{to_stage}'")
    skill = get_skill(skill_id)
    if skill is None:
        raise SkillRefusedError("skill not found")
    if order.index(to_stage) != order.index(skill.stage) + 1:
        raise SkillRefusedError(
            "stages advance one step at a time, never back")
    if to_stage == "applied" and len(skill.evidence) < 1:
        raise SkillRefusedError(
            "applied needs at least one evidence entry")
    if to_stage in ("demonstrated", "mastered"):
        if len(skill.evidence) < 2:
            raise SkillRefusedError(
                f"{to_stage} needs at least two evidence "
                "entries")
        if not str(confirmed_by or "").strip():
            raise SkillRefusedError(
                f"{to_stage} needs human confirmation")
    updated = skill.model_copy(update={
        "stage": to_stage, "updated_at": now(),
        "provenance": skill.provenance.model_copy(update={
            "human_verified": True,
            "verified_by": str(confirmed_by or
                               skill.provenance.verified_by or
                               "skills")[:80]})
        if to_stage in ("demonstrated", "mastered")
        else skill.provenance})
    save_skill(updated)
    return updated


def discover_candidates(project_text: str, *,
                        project_ref: str = "") -> list[SkillCandidate]:
    """Deterministic keyword discovery over project text.
    Returns candidates with evidence snippets — never skills."""
    if not isinstance(project_text, str) or not project_text.strip():
        raise SkillRefusedError("discovery needs project text")
    lowered = project_text.lower()
    owned = {skill.name.strip().lower()
             for skill in list_skills(limit=200)}
    candidates = []
    for keyword, name in DISCOVERY_KEYWORDS.items():
        if keyword not in lowered or name.lower() in owned:
            continue
        position = lowered.find(keyword)
        snippet = project_text[max(0, position - 40):
                               position + 80].strip()
        candidates.append(SkillCandidate(
            candidate_id=generate_candidate_id(), name=name,
            evidence=[f"keyword '{keyword}' in project "
                      f"context: …{snippet}…"],
            project_ref=str(project_ref or "")[:100],
            status="proposed", created_at=now()))
        if len(candidates) >= 10:
            break
    return candidates


def save_candidate(candidate: SkillCandidate) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO skill_candidates
        (candidate_id, name, evidence, project_ref, status,
         created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(candidate_id) DO NOTHING""",
                     (candidate.candidate_id, candidate.name,
                      dump(candidate.evidence),
                      candidate.project_ref, candidate.status,
                      candidate.created_at))


def list_candidates(*, status: str = "proposed"
                    ) -> list[SkillCandidate]:
    from .database import chat_connection, init_chat_database, load
    if status not in ("proposed", "accepted", "rejected"):
        raise SkillRefusedError(
            f"Unknown candidate status '{status}'")
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute("SELECT * FROM skill_candidates WHERE "
                          "status=? ORDER BY created_at DESC "
                          "LIMIT 100", (status,)).fetchall()
    return [SkillCandidate(
        candidate_id=row["candidate_id"], name=row["name"],
        evidence=load(row["evidence"]),
        project_ref=row["project_ref"], status=row["status"],
        created_at=row["created_at"]) for row in rows]


def accept_candidate(candidate_id: str, *,
                     accepted_by: str) -> Skill:
    """User acceptance turns a candidate into an owned skill
    at 'interested'. The candidate row closes as accepted."""
    if not str(accepted_by or "").strip():
        raise SkillRefusedError(
            "accepting a candidate needs a human")
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM skill_candidates WHERE "
                         "candidate_id=?",
                         (candidate_id,)).fetchone()
        if row is None:
            raise SkillRefusedError("candidate not found")
        if row["status"] != "proposed":
            raise SkillRefusedError(
                "candidate already decided")
        db.execute("UPDATE skill_candidates SET status="
                   "'accepted' WHERE candidate_id=?",
                   (candidate_id,))
    skill = new_skill(
        row["name"], stage="interested",
        project_refs=[row["project_ref"]]
        if row["project_ref"] else [],
        source=f"candidate:{candidate_id}",
        provenance=Provenance(
            source_type="user-created",
            creator_id=accepted_by.strip()[:80],
            human_verified=True,
            verified_by=accepted_by.strip()[:80],
            notes="accepted skill candidate"))
    save_skill(skill)
    return skill
