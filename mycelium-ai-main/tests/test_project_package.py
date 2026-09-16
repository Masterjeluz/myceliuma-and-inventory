"""Project-aware context package tests (BIG #5).

Bounded, read-only projection: no file contents, no secrets, no
absolute sensitive paths, provenance preserved, lexical fallback
when semantic retrieval is unavailable.
"""

import asyncio

import pytest

from coordinator.app.inventory_read import Provenance, SearchResult
from coordinator.app.project_context import ProjectContext
from coordinator.app.project_package import (
    assemble_project_package,
    build_project_package,
    redact_path,
    summarize_for_chat,
)


def run(coro):
    return asyncio.run(coro)


def make_project(tmp_path):
    return ProjectContext(
        project_id="prj-test", name="Testproject",
        repository=str(tmp_path), working_directory=str(tmp_path),
        provenance=Provenance(source_type="user-created",
                              creator_id="human",
                              human_verified=True))


def make_record(entity_id="obj_abc", title="Bout"):
    return {"entity_type": "object", "entity_id": entity_id,
            "title": title, "snippet": "M3 bout in lade",
            "match_type": "lexical",
            "provenance": {"source_type": "user-created",
                           "human_verified": True}}


class FakeReader:
    def __init__(self, results=None):
        self._results = results or []

    async def search(self, q, type=None):
        from coordinator.app.inventory_read import SearchResponse
        return SearchResponse(
            query=q,
            results=[SearchResult(
                entity_type="object", entity_id="obj_abc",
                title="Bout", snippet="M3",
                provenance=Provenance(
                    source_type="user-created",
                    creator_id="human", human_verified=True),
                details={})],
            total=1)

    async def browse(self, type=None):
        from coordinator.app.inventory_read import SearchResponse
        return SearchResponse(query="", results=[], total=0)

    async def graph(self, entity_id, depth=1):
        from coordinator.app.inventory_read import GraphResponse
        return GraphResponse(entity_id=entity_id, depth=depth,
                             nodes=[], edges=[])


def test_package_is_bounded(tmp_path):
    project = make_project(tmp_path)
    package = build_project_package(
        project,
        entities=[make_record(f"obj_{index:03d}") for index in range(50)],
        missions=[{"mission_id": f"mission_{index}",
                   "goal": f"doel {index}", "status": "running",
                   "steps": []} for index in range(20)],
        events=[{"event_type": "note", "message": f"m{index}"}
                for index in range(40)],
        git={"branch": "main", "lines": [f"M f{i}" for i in range(5)]},
        files=[{"name": f"bestand{index}.txt",
                "contents": "GEHEIM"}
               for index in range(30)])
    assert len(package["entities"]) == 10
    assert len(package["missions"]) == 5
    assert len(package["events"]) == 10
    assert len(package["files"]) == 10
    # Files are listed by name only — never contents.
    assert all(set(item) == {"name"} for item in package["files"])


def test_no_secrets_and_no_absolute_paths(tmp_path):
    project = make_project(tmp_path)
    home = str(tmp_path)
    package = build_project_package(
        project,
        entities=[{**make_record(),
                   "snippet": f"ligt in {home}/geheim",
                   "api_key": "SUPERGEHEIM"}],
        git={"branch": "main", "lines": [f"M {home}/x.txt"]})
    text = str(package)
    assert "SUPERGEHEIM" not in text
    assert home not in text
    assert "$PROJECT" in text or "$HOME" in text


def test_redact_path():
    import os
    assert redact_path("/home/jelles/x", "/home/jelles") == "$PROJECT/x"
    home = os.path.expanduser("~")
    assert "$HOME" in redact_path(home + "/x")


def test_provenance_flows_through(tmp_path):
    project = make_project(tmp_path)
    package = build_project_package(
        project, entities=[make_record()])
    provenance = package["entities"][0]["provenance"]
    assert provenance["source_type"] == "user-created"
    assert provenance["human_verified"] is True
    assert package["provenance"]["human_verified"] is False


def test_summary_answers_what_are_we_building(tmp_path):
    project = make_project(tmp_path)
    package = build_project_package(
        project, entities=[make_record()],
        missions=[{"mission_id": "mission_1",
                   "goal": "Werkbank opruimen",
                   "status": "running", "steps": []}],
        git={"branch": "main", "lines": []})
    summary = summarize_for_chat(package)
    assert "Testproject" in summary
    assert "Bout" in summary
    assert "Werkbank opruimen" in summary
    assert "geen toestemming" in summary


def test_assemble_uses_lexical_fallback(tmp_path):
    project = make_project(tmp_path)
    package = run(assemble_project_package(
        project, FakeReader(), query="bout", mode="hybrid"))
    assert package["retrieval_mode"] == "lexical"
    assert len(package["entities"]) == 1
    assert package["entities"][0]["entity_id"] == "obj_abc"


def test_assemble_empty_query_never_fails(tmp_path):
    project = make_project(tmp_path)
    package = run(assemble_project_package(
        project, FakeReader(), query=""))
    assert package["entities"] == []
    assert package["name"] == "Testproject"


class BrokenEmbedder:
    model = "broken"

    async def embed(self, texts):
        from coordinator.app.embeddings import EmbeddingUnavailable
        raise EmbeddingUnavailable("no model; pull one first")


def test_assemble_semantic_outage_falls_back(tmp_path):
    project = make_project(tmp_path)
    package = run(assemble_project_package(
        project, FakeReader(), query="bout", mode="hybrid",
        embedder=BrokenEmbedder()))
    assert package["retrieval_mode"] == "lexical"
    assert len(package["entities"]) == 1
