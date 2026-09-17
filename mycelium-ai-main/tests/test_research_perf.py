"""BIG #29 performance/bound tests: budgets hold under
adversarial volumes. No network; stub providers everywhere."""

import pytest

from coordinator.app.research_engine import (
    collect_sources,
    execute_run,
    extract_run_claims,
    generate_queries,
    new_run,
    save_run,
)
from coordinator.app.research_extract import MAX_CLAIMS_PER_SOURCE
from coordinator.app.research_transport import (
    FetchedPage,
    TestResearchTransport,
)

BIG_PAGES = {
    f"page-{index}": (
        f"Titel {index}",
        f"De distributieriem nummer {index} is belangrijk voor "
        f"de motor van variant {index}. "
        "De camper heeft vier wielen voor lange reizen. " * 20)
    for index in range(20)
}


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "perf.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "perf-chat.db"))


def test_max_sources_respected(isolated_db):
    run = new_run("Onderzoek de camper distributieriem motor")
    save_run(run)
    run = run.model_copy(update={
        "queries": generate_queries(run.question, [])})
    run, result = collect_sources(
        run, run.queries,
        search_provider=TestResearchTransport(BIG_PAGES),
        max_sources=2)
    assert result.stored == 2
    assert len(run.source_ids) == 2


def test_max_queries_bounded():
    queries = generate_queries("Onderzoek de camper", [
        "a", "b", "c", "d", "e", "f"])
    from coordinator.app.research_engine import MAX_QUERIES
    assert len(queries) <= MAX_QUERIES


def test_max_bytes_breaks_collection(isolated_db):
    run = new_run("Onderzoek de camper distributieriem")
    save_run(run)
    run = run.model_copy(update={
        "queries": generate_queries(run.question, [])})
    run, result = collect_sources(
        run, run.queries,
        search_provider=TestResearchTransport(BIG_PAGES),
        max_sources=6, max_bytes=10_000)
    assert len(run.source_ids) <= 6
    assert result.errors, "byte budget must be reported"


def test_claims_capped_per_source(isolated_db):
    run = new_run("Onderzoek de camper distributieriem motor")
    save_run(run)
    run = run.model_copy(update={
        "queries": generate_queries(run.question, [])})
    run, _ = collect_sources(
        run, run.queries,
        search_provider=TestResearchTransport(BIG_PAGES),
        max_sources=1)
    run = extract_run_claims(run, max_claims=5)
    assert len(run.claims) <= 5


def test_duplicate_seed_urls_counted(isolated_db):
    run = new_run("Onderzoek de camper distributieriem")
    save_run(run)

    def stub_fetch(url):
        return FetchedPage(
            canonical_url=url, final_url=url, status_code=200,
            content_type="text/plain", title="T",
            text="De distributieriem is belangrijk voor de motor. "
                 "De camper heeft vier wielen voor lange reizen.",
            content_hash="dup", retrieved_at="now",
            execution_state="REAL", provider="direct", hops=0)

    run, result = collect_sources(
        run, [],
        search_provider=TestResearchTransport({}),
        fetch_fn=stub_fetch,
        seed_urls=["https://example.com/a",
                   "https://example.com/a"])
    assert result.stored == 1
    assert result.duplicates == 1


def test_repeated_research_dedups_memory(isolated_db):
    import asyncio

    async def go():
        run = new_run("Onderzoek de camper distributieriem")
        save_run(run)
        return await execute_run(
            run.run_id,
            search_provider=TestResearchTransport({
                "a": ["T", "De distributieriem is belangrijk "
                      "voor de motor. De camper heeft vier "
                      "wielen voor lange reizen."]}),
            advise_fn=None)

    first = asyncio.run(go())
    second = asyncio.run(go())
    assert first.status == "completed"
    # Same content fingerprint: second run reuses the memory.
    assert second.memory_id == first.memory_id
