from abc import ABC, abstractmethod
import hashlib
import re

from app.config import Settings


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class Embedder(ABC):
    dim: int

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class FakeEmbedder(Embedder):  # scratch의 해시 fake. 결정적·무과금 (테스트용)
    dim: int = 256

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for word in _tokenize(text):
                bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim
                vec[bucket] += 1
            vectors.append(vec)
        return vectors


class SentenceTransformerEmbedder(Embedder):  # scratch Step 3의 진짜 임베딩
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        if (dimension := self.model.get_embedding_dimension()) is None:
            raise ValueError(
                f"Embedding model {model_name!r} did not report a dimension"
            )
        self.dim = dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()


def get_embedder(settings: Settings) -> Embedder:  # EMBEDDING_PROVIDER=fake|st 로 분기
    if settings.embedding_provider == "fake":
        return FakeEmbedder()
    return SentenceTransformerEmbedder(settings.embedding_model)
