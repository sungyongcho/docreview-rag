"""Every path that serves evidence leaves out text a later filing replaced or holds."""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.stored_evidence import read_cited_evidence, read_selected_cells
from app.agent.tools.filings import build_default_registry
from app.agent.tools.registry import ToolError
from app.amendments.policy import EvidenceWithheldError
from app.amendments.registration import register_filings
from app.amendments.review import ItemEffect, record_review
from app.api.errors import ApiProblemError
from app.api.review.evidence import CandidateSnapshot, EvidenceSelection, SnapshotCandidate
from app.api.review.runtime import RuntimeApiServices
from app.db.models import Chunk
from app.ingestion.persistence import persist_seed_batch
from app.retrieval.embedding.provider import DeterministicEmbeddingProvider
from app.retrieval.indexing.embeddings import embed_missing_chunks
from app.retrieval.search.plan import SearchPlan
from app.retrieval.search.service import retrieve
from app.retrieval.tables import cell_ref
from app.retrieval.types import RetrievalFilters
from tests.amendments.support import amendment_document, batch, hold, parsed, sec_document
from tests.live_postgres import isolated_session_factory

REPORT = sec_document(18)
AMENDMENT = amendment_document(21)
PENDING = (hold("sec", "AMD", 2025, "amendment_pending"),)
LEXICAL = SearchPlan(strategy="lexical")

type Factory = async_sessionmaker[AsyncSession]


async def stored(factory: Factory) -> dict[tuple[str, str | None], int]:
    """Store the report, learn of its amendment, and return chunk ids by document and Item."""
    async with factory() as session:
        await persist_seed_batch(session, batch(parsed(REPORT, ("1", "7"))))
        await register_filings(session, [AMENDMENT])
        await session.commit()
        await persist_seed_batch(session, batch(parsed(AMENDMENT, ("7",))))
        await embed_missing_chunks(session, DeterministicEmbeddingProvider())
        await session.commit()
        rows = await session.execute(select(Chunk.doc_id, Chunk.item, Chunk.id))
        return {(doc_id, item): chunk_id for doc_id, item, chunk_id in rows}


async def reviewed(factory: Factory) -> None:
    """Record that the amendment's Item 7 replaces the report's."""
    async with factory() as session, session.begin():
        await record_review(
            session,
            AMENDMENT.document_id,
            reviewer="operator",
            rationale="Item 7 restated in full.",
            effects=[ItemEffect("7", "replace")],
        )


@pytest.mark.live_postgres
def test_search_ranks_only_current_evidence_and_names_what_is_held() -> None:
    """A held period returns nothing and says why; a review swaps the replaced Item."""

    async def scenario() -> None:
        async with isolated_session_factory() as factory:
            await stored(factory)
            async with factory() as session:
                held = await retrieve(session, "text of Item", plan=LEXICAL, k=10)
                other_year = await retrieve(
                    session,
                    "text of Item",
                    plan=LEXICAL,
                    filters=RetrievalFilters(fiscal_years=(2024,)),
                )
            assert (held.hits, held.holds) == ((), PENDING)
            assert other_year.holds == ()

            await reviewed(factory)
            async with factory() as session:
                current = await retrieve(session, "text of Item", plan=LEXICAL, k=10)
                # The replaced Item must not take the only rank from a current one.
                first = await retrieve(session, "text of Item 7", plan=LEXICAL, k=1)
            assert {(hit.doc_id, hit.item) for hit in current.hits} == {
                (REPORT.document_id, "1"),
                (AMENDMENT.document_id, "7"),
            }
            assert current.holds == ()
            assert [(hit.doc_id, hit.item) for hit in first.candidates if hit.item == "7"] == [
                (AMENDMENT.document_id, "7")
            ]

            # A search narrowed to the original form cannot reach the Item that replaced
            # the report's, and is told so instead of being left with less.
            async with factory() as session:
                narrowed = await retrieve(
                    session,
                    "text of Item",
                    plan=LEXICAL,
                    k=10,
                    filters=RetrievalFilters(forms=("10-K",)),
                )
            assert [(hit.doc_id, hit.item) for hit in narrowed.hits] == [(REPORT.document_id, "1")]
            assert narrowed.holds == (hold("sec", "AMD", 2025, "replaced", ("7",)),)

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_agent_tools_report_holds_and_refuse_a_replaced_chunk() -> None:
    """The search tools name a hold only when there is one; a replaced chunk is refused."""

    async def scenario() -> None:
        async with isolated_session_factory() as factory:
            ids = await stored(factory)
            registry = build_default_registry(
                factory, embedding_provider=DeterministicEmbeddingProvider()
            )
            search, fetch, compare = (
                registry.get(name) for name in ("search_filings", "fetch_chunk", "compare_years")
            )
            query = search.parameters.model_validate({"query": "text of Item"})
            years = compare.parameters.model_validate(
                {"query": "text of Item", "issuer": "AMD", "fiscal_years": [2024, 2025]}
            )

            held = await search.run(query)
            assert held == {"hits": [], "holds": [PENDING[0].model_dump(mode="json")]}
            by_year = (await compare.run(years))["years"]
            assert [("holds" in year, year["hits"]) for year in by_year] == [
                (False, []),
                (True, []),
            ]
            original = fetch.parameters.model_validate({"chunk_id": ids[(REPORT.document_id, "7")]})
            with pytest.raises(ToolError, match="no longer evidence"):
                await fetch.run(original)

            await reviewed(factory)
            assert "holds" not in await search.run(query)
            with pytest.raises(ToolError, match="no longer evidence"):
                await fetch.run(original)
            amended = await fetch.run(
                fetch.parameters.model_validate({"chunk_id": ids[(AMENDMENT.document_id, "7")]})
            )
            assert amended["doc_id"] == AMENDMENT.document_id

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_a_final_answer_is_not_reviewed_from_a_replaced_chunk() -> None:
    """Reading cited text or selected cells again refuses a chunk replaced meanwhile."""

    async def scenario() -> None:
        async with isolated_session_factory() as factory:
            ids = await stored(factory)
            await reviewed(factory)
            replaced = ids[(REPORT.document_id, "7")]
            kept = ids[(REPORT.document_id, "1")]

            assert set(await read_cited_evidence(factory, (kept,))) == {kept}
            for read in (
                read_cited_evidence(factory, (kept, replaced)),
                read_selected_cells(factory, (cell_ref(replaced, 0, 0),)),
            ):
                with pytest.raises(EvidenceWithheldError) as refused:
                    await read
                assert refused.value.chunk_ids == (replaced,)

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_a_pinned_selection_made_before_a_review_is_reported_stale() -> None:
    """Candidates retrieved while an Item was current are stale once it is replaced."""

    async def scenario() -> None:
        async with isolated_session_factory() as factory:
            ids = await stored(factory)
            await reviewed(factory)
            runtime = SimpleNamespace(
                _scope=SimpleNamespace(
                    manifest_index=lambda: SimpleNamespace(
                        documents={
                            document.document_id: document for document in (REPORT, AMENDMENT)
                        }
                    )
                )
            )

            async def answer_from(*chunk_ids: int, snapshot_id: int | None = None):
                """Reload the candidates a signed snapshot names, as a review would."""
                candidates = CandidateSnapshot(
                    issued_at=0,
                    expires_at=1,
                    query_sha256="0" * 64,
                    profile_sha256="0" * 64,
                    filters_sha256="0" * 64,
                    candidates=tuple(
                        SnapshotCandidate(chunk_id=chunk_id, source_sha256="a" * 64)
                        for chunk_id in chunk_ids
                    ),
                    routing_queries={},
                )
                async with factory() as session:
                    return await RuntimeApiServices._selected_evidence(
                        runtime,  # pyright: ignore[reportArgumentType]
                        session,
                        candidates,
                        EvidenceSelection(candidate_token="signed"),
                        RetrievalFilters(snapshot_id=snapshot_id),
                        k=5,
                        max_context_chars=12_000,
                    )

            kept, replaced = ids[(REPORT.document_id, "1")], ids[(REPORT.document_id, "7")]
            result, _candidates = await answer_from(kept, ids[(AMENDMENT.document_id, "7")])
            assert len(result.hits) == 2
            with pytest.raises(ApiProblemError) as stale:
                await answer_from(kept, replaced)
            assert (stale.value.status_code, stale.value.error.code) == (
                409,
                "candidate_snapshot_stale",
            )
            # A frozen snapshot keeps serving what it froze.
            frozen, _candidates = await answer_from(kept, replaced, snapshot_id=1)
            assert len(frozen.hits) == 2

    asyncio.run(scenario())
