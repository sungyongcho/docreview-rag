from typing import Any, Optional

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict
from rank_bm25 import BM25Okapi

from krag_compat.tokenizers import KiwiTokenizer


class KiWiBM25RetrieverWithScore(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    documents: list[Document]
    kiwi_tokenizer: Optional[KiwiTokenizer] = None
    k: int = 4
    threshold: float = 0.0
    vectorizer: Any = None

    def __init__(
        self,
        documents,
        kiwi_tokenizer: KiwiTokenizer | None = None,
        k: int | None = None,
        threshold: float = 0.0,
    ):
        docs = list(documents)
        super().__init__(
            documents=docs,
            kiwi_tokenizer=kiwi_tokenizer,
            k=k if k is not None else 4,
            threshold=threshold,
        )
        if docs:
            self.vectorizer = BM25Okapi([self._tokenize(doc.page_content) for doc in docs])

    def _tokenize(self, text: str) -> list[str]:
        if self.kiwi_tokenizer is None:
            return text.split()
        return [token.form for token in self.kiwi_tokenizer.tokenize(text)]

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        if not self.documents or self.vectorizer is None:
            return []

        tokenized_query = self._tokenize(query)
        scores = self.vectorizer.get_scores(tokenized_query)
        top_indices = sorted(range(len(scores)), key=lambda idx: scores[idx], reverse=True)[: self.k]

        docs = []
        for idx in top_indices:
            score = float(scores[idx])
            if score <= self.threshold:
                continue

            doc = self.documents[idx]
            metadata = dict(doc.metadata)
            metadata["bm25_score"] = score
            docs.append(Document(page_content=doc.page_content, metadata=metadata, id=doc.id))

        return docs

