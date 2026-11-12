"""A snapshot freezes current evidence only, and keeps serving it after a later change."""

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.amendments.review import ItemEffect, clear_review, record_review
from app.db.models import EvalResult, SnapshotChunk, SnapshotDocument
from app.evals.results.identity import (
    EVALUATED_GOLDEN_KEY,
    evaluated_golden_sha256,
    index_fingerprint,
)
from app.evals.snapshots.service import SnapshotService
from app.ingestion.persistence import persist_seed_batch
from app.retrieval.embedding.provider import EmbeddingIdentity
from app.retrieval.search.plan import SearchPlan
from app.retrieval.search.service import retrieve
from app.retrieval.types import RetrievalFilters
from tests.amendments.support import (
    amendment_document,
    batch,
    dart_document,
    eligible,
    hold,
    parsed,
    sec_document,
)
from tests.live_postgres import isolated_session_factory

REPORT = sec_document(18)
AMENDMENT = amendment_document(21)
ORIGINAL = dart_document("20210322000782")
CORRECTION = dart_document("20210330000776")
IDENTITY = EmbeddingIdentity("test", "frozen-evidence", 384, "cl100k_base")
CASES = [{"id": "case-1", "question": "What changed?"}]


async def evaluated(
    factory: async_sessionmaker[AsyncSession], directory: Path, name: str, fingerprint: str
) -> int:
    """Store one evaluation result that claims the given corpus fingerprint."""
    config = {
        "strategy": "lexical",
        EVALUATED_GOLDEN_KEY: evaluated_golden_sha256(CASES),
        "embedding": {
            "provider": IDENTITY.provider,
            "model": IDENTITY.model,
            "dimensions": IDENTITY.dimensions,
            "tokenizer": IDENTITY.tokenizer,
        },
        "admin_identity": {"corpus_fingerprint": fingerprint, "golden_sha256": "a" * 64},
    }
    path = directory / f"{name}.json"
    case = {"golden": CASES[0], "score": {"first_relevant_rank": 1}, "hits": []}
    path.write_text(json.dumps({"cases": [case], "suite": "frozen-evidence", "config": config}))
    result = EvalResult(
        suite="frozen-evidence", config=config, metrics={"mrr": 1.0}, raw_artifact_path=str(path)
    )
    async with factory() as session, session.begin():
        session.add(result)
    return result.id


@pytest.mark.live_postgres
def test_a_snapshot_holds_only_current_evidence_and_outlives_a_later_hold(tmp_path) -> None:
    """Replaced text is not frozen; what was frozen stays searchable when live is held."""

    async def scenario() -> None:
        async with isolated_session_factory() as factory:
            async with factory() as session:
                await persist_seed_batch(
                    session,
                    batch(
                        parsed(REPORT, ("1", "7")),
                        parsed(AMENDMENT, ("7",)),
                        parsed(ORIGINAL, ("I",)),
                        parsed(CORRECTION, ("I",)),
                    ),
                )
                await record_review(
                    session,
                    AMENDMENT.document_id,
                    reviewer="operator",
                    rationale="Item 7 restated in full.",
                    effects=[ItemEffect("7", "replace")],
                )
                await session.commit()
                current = await eligible(session)
                fingerprint = await index_fingerprint(session, IDENTITY)
            assert current == {
                (REPORT.document_id, "1"),
                (AMENDMENT.document_id, "7"),
                (CORRECTION.document_id, "I"),
            }
            service = SnapshotService(session_factory=factory, artifact_dir=tmp_path)
            first = await evaluated(factory, tmp_path, "first", fingerprint)
            later = await evaluated(factory, tmp_path, "later", fingerprint)

            snapshot = await service.create(label="Reviewed", eval_result_id=first, public=False)

            async with factory() as session:
                frozen = await session.execute(
                    select(SnapshotChunk.doc_id, SnapshotChunk.item).where(
                        SnapshotChunk.snapshot_id == snapshot.snapshot_id
                    )
                )
                assert {(doc_id, item) for doc_id, item in frozen} == current
                documents = await session.scalars(
                    select(SnapshotDocument.doc_id).where(
                        SnapshotDocument.snapshot_id == snapshot.snapshot_id
                    )
                )
                # The replaced DART original contributes nothing, so it is not a member.
                assert set(documents) == {doc_id for doc_id, _ in current}

                await clear_review(session, AMENDMENT.document_id)
                await session.commit()
                assert await index_fingerprint(session, IDENTITY) != fingerprint
                plan = SearchPlan(strategy="lexical")
                live = await retrieve(
                    session, "text of Item", plan=plan, filters=RetrievalFilters(issuers=("AMD",))
                )
                kept = await retrieve(
                    session,
                    "text of Item",
                    plan=plan,
                    k=10,
                    filters=RetrievalFilters(issuers=("AMD",), snapshot_id=snapshot.snapshot_id),
                )
            assert (live.hits, live.holds) == ((), (hold("sec", "AMD", 2025, "amendment_pending"),))
            assert {(hit.doc_id, hit.item) for hit in kept.hits} == {
                (REPORT.document_id, "1"),
                (AMENDMENT.document_id, "7"),
            }
            assert kept.holds == ()
            # An evaluation run before the hold no longer describes the live index.
            with pytest.raises(ValueError, match="no longer matches"):
                await service.create(label="Outdated", eval_result_id=later, public=False)

    asyncio.run(scenario())
