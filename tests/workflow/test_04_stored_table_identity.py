"""The workflow figure check over stored tables, as the review runtime loads them."""

import asyncio
from functools import partial

import pytest
from sqlalchemy import select, update

from app.db.models import Chunk, ParsedTable
from app.ingestion.chunking import compose_index_text
from app.ingestion.persistence import persist_seed_batch
from app.llm.schemas import AnswerDecision, ChunkRelevance, RelevanceJudgment
from app.retrieval.tables import load_table_readings
from app.retrieval.types import ChunkHit
from app.workflow.nodes import check_node, grade_node, report_node, retrieve_node
from app.workflow.types import FiguresUnverified, WorkflowRequest, initial_state
from tests.ingestion.seed.support import sample_batch, table_batch
from tests.live_postgres import isolated_session
from tests.workflow.support import ok_result, provider_budget

PROSE = "Net revenue increased 14% compared with the prior year."


def _hit(chunk: Chunk) -> ChunkHit:
    """Retrieve one stored chunk as the workflow's retriever returns it, body as stored now."""
    return ChunkHit(
        chunk_id=chunk.id,
        doc_id=chunk.doc_id,
        item=chunk.item,
        kind=chunk.kind,
        citation=chunk.citation,
        start_char=chunk.start_char,
        end_char=chunk.end_char,
        source_sha256=chunk.source_sha256,
        body=chunk.body,
        context_header=chunk.context_header,
        index_text=compose_index_text(chunk.context_header, chunk.body),
        score=1.0,
    )


async def _label(session, hit: ChunkHit, answer: str, years: tuple[int, ...]):
    """Grade one hit relevant, load its readings as the runtime does, and report."""
    request = WorkflowRequest(
        run_id="run-stored", query="What was revenue?", provider_budget=provider_budget()
    )
    state = initial_state(request).model_copy(update={"requested_fiscal_years": years})
    state = retrieve_node(state, [hit])
    judgment = RelevanceJudgment(
        grades=(ChunkRelevance(chunk_id=hit.chunk_id, relevant=True, reason="Revenue."),)
    )
    state = grade_node(state, ok_result(judgment))
    loader = partial(load_table_readings, session, snapshot_id=None)
    readings = await loader(tuple(h.chunk_id for h in state.evidence if h.kind == "table"))
    decision = AnswerDecision(
        label="SUPPORTED", answer=answer, citation_chunk_ids=(hit.chunk_id,), reason="Stated."
    )
    report = report_node(check_node(state, ok_result(decision), readings)).report
    assert report is not None
    return report


@pytest.mark.live_postgres
@pytest.mark.parametrize("identity", ["resolver_identity", "builder_identity"])
def test_a_stale_table_leaves_a_supported_figure_unverified(identity):
    """Support a figure from a current table, refuse it from a stale one, keep prose."""

    async def exercise() -> None:
        """Store a table and a prose chunk, report, mark the table stale, report again."""
        async with isolated_session() as session:
            await persist_seed_batch(session, table_batch(doc_id="AMD-FY2024"))
            await persist_seed_batch(session, sample_batch())
            await session.execute(update(Chunk).where(Chunk.kind == "text").values(body=PROSE))
            table = (await session.scalars(select(Chunk).where(Chunk.doc_id == "AMD-FY2024"))).one()
            text = (await session.scalars(select(Chunk).where(Chunk.kind == "text"))).one()
            answer = "Net revenue was $25,785 million in fiscal 2024."

            report = await _label(session, _hit(table), answer, (2024,))
            assert report.label == "SUPPORTED"
            prose = await _label(session, _hit(text), "Revenue grew 14%.", ())
            assert prose.label == "SUPPORTED"

            await session.execute(update(ParsedTable).values({identity: "0" * 64}))
            refused = await _label(session, _hit(table), answer, (2024,))
            assert refused.label == "NOT_IN_DOCS"
            assert any(isinstance(reason, FiguresUnverified) for reason in refused.reasons)
            prose = await _label(session, _hit(text), "Revenue grew 14%.", ())
            assert prose.label == "SUPPORTED"

    asyncio.run(exercise())
