from app.retrieval.embeddings import FakeEmbedder
from app.retrieval.hybrid import rrf_fuse
from app.retrieval.rerank import Reranker
from app.retrieval.types import ChunkHit

# 임베더는 FakeEmbedder만 (결정적·무과금·모델 다운로드 없음)


def test_fake_embedder_deterministic_and_dim():
    e = FakeEmbedder()
    v1 = e.embed_query("home office")
    v2 = e.embed_query("home office")
    assert v1 == v2  # 같은 입력 → 같은 벡터 (hashlib라 실행마다 동일)
    assert len(v1) == e.dim == 256


def test_fake_embedder_batch_shape():
    e = FakeEmbedder()
    vecs = e.embed_documents(["alpha beta", "gamma"])
    assert len(vecs) == 2
    assert all(len(v) == e.dim for v in vecs)


# --- RRF 융합 ---


def _hit(citation: str) -> ChunkHit:
    return ChunkHit(doc_id="X-1", section="1", snippet="", score=0.0, citation=citation)


def test_rrf_rewards_cross_list_agreement():
    a, b, c = _hit("A §1"), _hit("B §1"), _hit("C §1")
    vec = [a, b, c]  # A 1위, B 2위, C 3위
    lex = [b, a]  # B 1위, A 2위 (C 없음)
    fused = rrf_fuse([vec, lex])
    keys = [h.citation for h in fused]
    assert keys[-1] == "C §1"  # C는 한 리스트에만 → 꼴찌
    assert set(keys[:2]) == {"A §1", "B §1"}  # 양쪽 상위인 A·B가 위


# --- 리랭커 (모델 없이 재정렬 로직만) ---


def test_reranker_reorders_and_truncates():
    hits = [
        ChunkHit("A", "1", "", 0.9, "A §1"),
        ChunkHit("B", "1", "", 0.8, "B §1"),
        ChunkHit("C", "1", "", 0.7, "C §1"),
    ]
    out = Reranker._rerank_by_scores(hits, [0.1, 0.2, 5.0], top_k=2)
    assert [h.citation for h in out] == ["C §1", "B §1"]
    assert out[0].score == 5.0
