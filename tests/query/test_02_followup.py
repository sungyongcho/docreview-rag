"""Follow-up routing uses the same Unicode issuer spans as scope matching."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.review.schemas import RetrieveRequest
from app.ingestion.sources.models import CorpusIdentity, Manifest
from app.query.conversation import ConversationRouter
from app.query.intent import ConversationTurn
from app.query.resolution import ScopeResolver
from app.retrieval.search.profiles import ServerBM25
from tests.ingestion.support import filing_document


@pytest.mark.parametrize(
    ("previous", "expected"),
    [
        ("ＮＶＤＡ revenue 2023", "revenue — AMD 2024?"),
        ("삼성전자 매출 2023", "매출 — AMD 2024?"),
    ],
)
def test_issuer_and_year_pivot_preserves_only_the_previous_topic(tmp_path, previous, expected):
    """Remove the actual prior alias bytes while retaining its financial topic."""
    Manifest(
        corpus=CorpusIdentity(corpus_id="followup", name="Follow-up fixtures"),
        documents=(
            filing_document(),
            filing_document(issuer="AMD", filing_id="0000002488-24-000005"),
            filing_document(registry="dart", aliases=("삼성전자",)),
        ),
    ).write(tmp_path / "manifest.json")

    def no_database():
        """Reject database access during deterministic routing."""
        raise AssertionError("A known follow-up only needs the manifest")

    engines = SimpleNamespace(resolve_engine=AsyncMock(side_effect=AssertionError("provider")))
    router = ConversationRouter(
        scope=ScopeResolver(
            corpus_root=tmp_path,
            session_factory=no_database,
            bm25=ServerBM25(),
            developer=False,
            secret_values=(),
        ),
        engines=engines,
        classifier_enabled=True,
    )
    decision, path = asyncio.run(
        router.decide_path(
            RetrieveRequest(
                query="AMD 2024?",
                conversation_history=(ConversationTurn(role="user", text=previous),),
            )
        )
    )

    assert decision.intent == "document_review"
    assert decision.matched_rule == "filing_followup"
    assert path["retrieval_query"] == expected
    engines.resolve_engine.assert_not_awaited()
