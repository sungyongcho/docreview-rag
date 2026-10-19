"""Signed candidate snapshot and evidence-selection tests."""

from app.api.review.evidence import (
    CandidateSnapshotCodec,
    EvidenceSelection,
    EvidenceSnapshotError,
    select_evidence,
)
from app.api.review.profiles import ResolvedRetrievalProfile
from app.retrieval.types import ChunkHit, RetrievalFilters


def hit(chunk_id: int, body: str = "evidence", header: str = "ACME FY2024 · Item 7") -> ChunkHit:
    """Build one source-bound snapshot candidate."""
    return ChunkHit(
        chunk_id=chunk_id,
        doc_id="ACME-FY2024",
        item="7",
        kind="text",
        citation=header,
        start_char=chunk_id * 10,
        end_char=chunk_id * 10 + len(body),
        source_sha256=f"{chunk_id:064x}",
        body=body,
        context_header=header,
        index_text=f"{header}\n\n{body}",
        score=1.0 / chunk_id,
    )


def profile() -> ResolvedRetrievalProfile:
    """Return the default exact snapshot retrieval plan."""
    return ResolvedRetrievalProfile(
        preset="balanced",
        strategy="hybrid",
        k=2,
        candidate_k=20,
        rrf_k=60,
        lexical_ranker="ts_rank_cd",
        bm25_k1=1.2,
        bm25_b=0.75,
        bm25_idf="lucene",
        route_by_language=True,
        reranker=None,
    )


def test_signed_snapshot_pins_excludes_and_preserves_ranked_fill() -> None:
    """Select pinned evidence first and fill from the signed original order."""
    codec = CandidateSnapshotCodec(b"s" * 32, clock=lambda: 100.0)
    candidates = (hit(1), hit(2), hit(3))
    token, snapshot = codec.issue(
        query="query",
        profile=profile(),
        filters=RetrievalFilters(),
        candidates=candidates,
        routing_queries={"ko": "매출 증가"},
    )
    verified = codec.verify(
        token,
        query="query",
        profile=profile(),
        filters=RetrievalFilters(),
    )
    selected = select_evidence(
        verified,
        EvidenceSelection(
            candidate_token=token,
            pinned_chunk_ids=(3,),
            excluded_chunk_ids=(1,),
        ),
        candidates,
        k=2,
        max_context_chars=10_000,
    )

    assert snapshot == verified
    assert verified.routing_queries == {"ko": "매출 증가"}
    assert verified.candidates[2].score == candidates[2].score
    assert tuple(item.chunk_id for item in selected) == (3, 2)


def test_snapshot_rejects_tampering_and_outside_ids() -> None:
    """Fail before review when token or selected membership is untrusted."""
    codec = CandidateSnapshotCodec(b"s" * 32, clock=lambda: 100.0)
    candidates = (hit(1),)
    token, snapshot = codec.issue(
        query="query",
        profile=profile(),
        filters=RetrievalFilters(),
        candidates=candidates,
        routing_queries={},
    )

    try:
        codec.verify(
            token + "x",
            query="query",
            profile=profile(),
            filters=RetrievalFilters(),
        )
    except EvidenceSnapshotError as error:
        assert error.code == "candidate_snapshot_invalid"
    else:
        raise AssertionError("tampered snapshot was accepted")

    try:
        select_evidence(
            snapshot,
            EvidenceSelection(candidate_token=token, pinned_chunk_ids=(2,)),
            candidates,
            k=2,
            max_context_chars=10_000,
        )
    except EvidenceSnapshotError as error:
        assert error.code == "invalid_evidence_selection"
    else:
        raise AssertionError("outside evidence id was accepted")


def test_pins_with_one_body_are_duplicates_only_in_the_same_context() -> None:
    """Accept one table body pinned for two companies; reject the same chunk text twice."""
    codec = CandidateSnapshotCodec(b"s" * 32, clock=lambda: 100.0)
    body = "| Total | 100 |"
    candidates = (
        hit(1, body, "AMD FY2024 · Item 8"),
        hit(2, body, "NVDA FY2024 · Item 8"),
        hit(3, body, "AMD FY2024 · Item 8"),
    )
    token, snapshot = codec.issue(
        query="query",
        profile=profile(),
        filters=RetrievalFilters(),
        candidates=candidates,
        routing_queries={},
    )

    def pin(*chunk_ids: int) -> tuple[ChunkHit, ...]:
        """Select the given pins from the signed snapshot."""
        selection = EvidenceSelection(candidate_token=token, pinned_chunk_ids=chunk_ids)
        return select_evidence(snapshot, selection, candidates, k=2, max_context_chars=10_000)

    assert tuple(item.chunk_id for item in pin(1, 2)) == (1, 2)
    try:
        pin(1, 3)
    except EvidenceSnapshotError as error:
        assert error.code == "duplicate_pinned_evidence"
    else:
        raise AssertionError("the same source text in the same context was pinned twice")
