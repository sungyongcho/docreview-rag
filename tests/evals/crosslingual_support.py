"""Twin-question fixtures shared by the cross-lingual tests."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.evals.execution.models import EvaluationRetrieval
import app.evals.experiments.crosslingual as crosslingual_arms
from app.evals.experiments.crosslingual import CrosslingualArm, run_arm
from app.evals.golden.bilingual import BilingualSuite
from app.evals.golden.models import GoldenCase, GoldenCategory, GoldenSpan
from app.retrieval.types import ChunkHit
from tests.evals.support import EVALUATION_RECORDED_AT, SOURCE_SHA256

QUESTIONS = {
    "m3c-01": ("How did AMD's gross margin change?", "AMD의 매출총이익률은 어떻게 변화했습니까?"),
    "m3c-02": (
        "What did Intel disclose about capacity?",
        "인텔은 생산 능력에 대해 무엇을 공시했습니까?",
    ),
    "m3c-03": ("Which risk did the filing name?", "공시는 어떤 위험을 언급했습니까?"),
}


def golden(
    case_id: str, language: str, *, category: GoldenCategory = "simple_lookup"
) -> GoldenCase:
    """Build one twin case in the requested language."""
    question = QUESTIONS[case_id][0 if language == "en" else 1]
    return GoldenCase(
        id=case_id,
        question=question,
        category=category,
        facet="factual",
        tags=(),
        answers=(
            GoldenSpan(
                doc_id="AMD-FY2019",
                source_sha256=SOURCE_SHA256,
                start_char=100,
                end_char=200,
            ),
        ),
        expected_label="SUPPORTED",
        reference_answer="Supported evidence.",
        note="Cross-lingual fixture.",
        curation_status="agent-curated",
        approval_status="pending-author-approval",
        human_verified=False,
    )


def suite(
    categories: tuple[GoldenCategory, ...] = ("simple_lookup", "simple_lookup", "multi_hop"),
):
    """Build one synthetic twin suite over three shared answer spans."""
    ids = sorted(QUESTIONS)
    return BilingualSuite(
        en=tuple(
            golden(case_id, "en", category=category)
            for case_id, category in zip(ids, categories, strict=True)
        ),
        ko=tuple(
            golden(case_id, "ko", category=category)
            for case_id, category in zip(ids, categories, strict=True)
        ),
    )


def hit(chunk_id: int, *, start: int, score: float = 0.5) -> ChunkHit:
    """Build one candidate whose span may or may not overlap the golden one."""
    body = "Research and development expenses increased."
    context_header = "AMD FY2019 · Item 7"
    return ChunkHit(
        chunk_id=chunk_id,
        doc_id="AMD-FY2019",
        item="7",
        kind="text",
        citation=context_header,
        start_char=start,
        end_char=start + 100,
        source_sha256=SOURCE_SHA256,
        body=body,
        context_header=context_header,
        index_text=f"{context_header}\n\n{body}",
        score=score,
    )


BM25_FIELDS = {"bm25_k1": 1.2, "bm25_b": 0.75, "bm25_idf": "lucene"}


def arm(**changes):
    """Build one hybrid deterministic arm with optional field replacements."""
    values: dict[str, Any] = {
        "embedding_provider": "deterministic",
        "embedding_model": "token-hash-384",
        "strategy": "hybrid",
        "language": "en",
        "lexical_ranker": "ts_rank_cd",
    }
    values.update(changes)
    return CrosslingualArm(**values)


def evaluate_arm(module_arm, tmp_path=None):
    """Evaluate one arm against a scripted retriever, bypassing the database."""
    return asyncio.run(
        run_arm(
            cast(AsyncSession, SimpleNamespace()),
            module_arm,
            suite(),
            provider=None,
            artifact_dir=tmp_path,
            recorded_at=EVALUATION_RECORDED_AT,
        )
    )


def scripted(monkeypatch, per_language):
    """Replace ``make_retriever`` with a scripted, database-free retriever."""

    def factory(session, **kwargs):
        """Build one scripted retriever for the requested language."""

        async def retriever(query: str, k: int):
            """Return the scripted hits for the query language."""
            language = (
                "ko" if any(question == query for _, question in QUESTIONS.values()) else "en"
            )
            return EvaluationRetrieval(hits=tuple(per_language[language]))

        return retriever

    monkeypatch.setattr(crosslingual_arms, "make_retriever", factory)
