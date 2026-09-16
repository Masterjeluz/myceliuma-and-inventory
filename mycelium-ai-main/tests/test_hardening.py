"""FASE 9/10 tests (BIG #16): provenance defaults + save invariants.

Machine-created records never default to human_verified;
function-level saves enforce stage/evidence/revision rules
so future callers cannot bypass route checks.
"""

import pytest

from coordinator.app.inventory_read import Provenance


def test_machine_defaults_not_verified():
    from coordinator.app import cad, drones, familiars
    from coordinator.app import fabrication, robots, skills
    assert robots.new_robot(
        "R", capabilities=["robot.status"]).provenance.human_verified is False
    assert drones.new_drone(
        "D", capabilities=["drone.observe"]).provenance.human_verified is False
    assert familiars.new_familiar(
        "F", "digital").provenance.human_verified is False
    document = cad.new_document("Doc")
    assert document.provenance.human_verified is False
    assert fabrication.new_spool(
        "PLA", 100).provenance.human_verified is False
    assert skills.new_skill(
        "Soldering").provenance.human_verified is False
    # Explicit human provenance still accepted.
    human = Provenance(source_type="user-created",
                       creator_id="jelles", human_verified=True,
                       verified_by="jelles")
    assert robots.new_robot("R2", provenance=human
                            ).provenance.human_verified is True


def test_save_skill_rejects_unevidenced_stages(tmp_path,
                                               monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "h.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "h-chat.db"))
    from coordinator.app.skills import (
        Skill, SkillRefusedError, generate_skill_id, now,
        save_skill)
    from coordinator.app.inventory_read import Provenance as Prov
    base = dict(skill_id=generate_skill_id(), name="X",
                category="", description="", prerequisites=[],
                related_skills=[], proficiency="unknown",
                evidence=[], source="",
                provenance=Prov(source_type="user-created",
                                creator_id="t",
                                human_verified=False),
                project_refs=[], created_at=now(),
                updated_at=now())
    with pytest.raises(SkillRefusedError):
        save_skill(Skill(**{**base, "stage": "applied"}))
    with pytest.raises(SkillRefusedError):
        save_skill(Skill(**{**base, "stage": "mastered"}))
    # Evidenced but unverified top stage still refuses.
    from coordinator.app.skills import SkillEvidence
    evidenced = Skill(**{
        **base, "stage": "demonstrated",
        "evidence": [SkillEvidence(kind="project", ref="p1"),
                     SkillEvidence(kind="print", ref="p2")]})
    with pytest.raises(SkillRefusedError):
        save_skill(evidenced)
    verified = evidenced.model_copy(update={
        "provenance": Prov(
            source_type="user-created", creator_id="t",
            human_verified=True, verified_by="t")})
    save_skill(verified)  # passes


def test_save_memory_revision_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "h2.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "h2-chat.db"))
    from coordinator.app.memory import (
        MemoryRefusedError, get_memory, new_memory, save_memory)
    entry = new_memory("fact", "Revision guard",
                       truth="user_fact",
                       provenance=Provenance(
                           source_type="user-created",
                           creator_id="t", human_verified=True,
                           verified_by="t"))
    save_memory(entry)
    stored = get_memory(entry.memory_id)
    moved = stored.model_copy(update={
        "revision": stored.revision + 1,
        "content": "moved on"})
    save_memory(moved)
    with pytest.raises(MemoryRefusedError):
        save_memory(moved, expected_revision=1)
    save_memory(moved, expected_revision=2)


def test_payload_unified_bans(tmp_path, monkeypatch):
    from coordinator.app.diststate import (
        DistStateRefusedError, new_envelope)
    from coordinator.app.events import (
        EventRefusedError, new_event)
    from coordinator.app.payloads import (
        BANNED_PAYLOAD_KEYS, check_payload)
    assert {"sql", "query", "command", "shell", "exec",
            "url", "callback"} <= set(BANNED_PAYLOAD_KEYS)
    # Top-level bans on both paths.
    for banned in ("command", "shell", "sql", "query", "url",
                   "approved", "execute_now", "COMMAND"):
        with pytest.raises(DistStateRefusedError):
            new_envelope("node-a", "obj_1", "object",
                         "entity.observed",
                         payload={banned: "x"})
        with pytest.raises(EventRefusedError):
            new_event("task.queued", "summary",
                      payload={banned: "x"})
    # Nested bans refuse too.
    with pytest.raises(DistStateRefusedError):
        new_envelope("node-a", "obj_1", "object",
                     "entity.observed",
                     payload={"outer": {"exec": "rm"}})
    with pytest.raises(EventRefusedError):
        new_event("task.queued", "summary",
                  payload={"items": [{"sql": "select"}]})
    # Depth cap refuses hostile nesting.
    deep = {}
    cursor = deep
    for _ in range(10):
        cursor["next"] = {}
        cursor = cursor["next"]
    with pytest.raises(DistStateRefusedError):
        new_envelope("node-a", "obj_1", "object",
                     "entity.observed", payload=deep)
    # Oversized values and key counts refuse.
    with pytest.raises(EventRefusedError):
        new_event("task.queued", "summary",
                  payload={"note": "x" * 501})
    with pytest.raises(DistStateRefusedError):
        new_envelope("node-a", "obj_1", "object",
                     "entity.observed",
                     payload={f"key{i}": i for i in range(31)})
    # Legit nested metadata still passes.
    kept = check_payload({"a": {"b": ["x", 1, None]}},
                         max_keys=20, max_value_chars=500,
                         error=EventRefusedError)
    assert kept == {"a": {"b": ["x", 1, None]}}


def test_max_memories_enforced(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "h4.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "h4-chat.db"))
    from coordinator.app import memory as memory_mod
    from coordinator.app.memory import (
        MemoryRefusedError, new_memory, save_memory)
    monkeypatch.setattr(memory_mod, "MAX_MEMORIES", 2)
    for index in range(2):
        save_memory(new_memory(
            "fact", f"fact {index}", truth="observed"))
    with pytest.raises(MemoryRefusedError):
        save_memory(new_memory("fact", "one too many",
                               truth="observed"))


def test_save_link_stale_write_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "h3.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "h3-chat.db"))
    from coordinator.app.twin import (
        TwinRefusedError, new_link, observe_link, save_link)
    link = new_link("printer", "hw_1", "represents")
    save_link(link)
    observed = observe_link(link.link_id)
    assert observed is not None
    with pytest.raises(TwinRefusedError):
        save_link(link,
                  expected_updated_at=link.updated_at)
    save_link(observed,
              expected_updated_at=observed.updated_at)
