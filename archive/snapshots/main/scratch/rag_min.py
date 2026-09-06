import hashlib
import math
from pathlib import Path

from markdown_parser import Section, parse_corpus
from sentence_transformers import SentenceTransformer

DIM = 256


def embed_fake(texts: list[str]) -> list[list[float]]:
    # Step 3 전까지는 deterministic fake (토큰 해시 기반 고정 벡터). API·모델 다운로드 없음.
    # (lab은 sentence-transformers를 썼지만 여기선 무과금·결정적 fake로 흐름만 확인)

    vectors: list[list[float]] = []
    for text in texts:
        vec = [0.0] * DIM
        for word in _tokenize(text):
            bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM
            vec[bucket] += 1
        vectors.append(vec)
    return vectors


MODEL = SentenceTransformer("all-MiniLM-L6-v2")


def embed(texts: list[str]) -> list[list[float]]:
    # 진짜 의미 벡터. normalize=True면 cosine이 내적과 같아져 계산도 안정적.
    return MODEL.encode(texts, normalize_embeddings=True).tolist()


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def retrieve(
    query: str, corpus: list[Section], doc_embs: list[list[float]], k: int = 5
) -> list[tuple[Section, float]]:
    # query 임베딩 vs 각 섹션 임베딩 코사인 top-k. 반환에 section.citation 포함.
    q_emb = embed([query])[0]
    scored = [(section, cosine(q_emb, emb)) for section, emb in zip(corpus, doc_embs)]

    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:k]


if __name__ == "__main__":
    import argparse
    import os

    p = argparse.ArgumentParser()
    p.add_argument("--query", required=True)
    p.add_argument("-k", type=int, default=5)
    a = p.parse_args()
    root = Path(
        os.getenv("DATASET_ROOT", "data/sample1/docreview-dataset/data/seed/synthetic")
    )
    corpus = parse_corpus(root)
    doc_embs = embed(
        [s.text if hasattr(s, "text") else f"{s.heading}\n{s.content}" for s in corpus]
    )
    hits = retrieve(a.query, corpus, doc_embs, k=a.k)
    print(f"query: {a.query!r}  (corpus={len(corpus)} sections)\n")
    for sec, score in hits:
        print(f"  {sec.citation:12} score={score:.3f} | {sec.heading[:50]}")
    assert hits, "검색 결과 0건 — 파서/임베딩 배선 확인"
