import math
from collections import Counter
from enum import Enum
from functools import lru_cache
from typing import Optional

from krag_compat.tokenizers import KiwiTokenizer


class AveragingMethod(Enum):
    MICRO = "micro"
    MACRO = "macro"
    BOTH = "both"


class MatchingCriteria(Enum):
    ALL = "all"
    PARTIAL = "partial"


class OfflineRetrievalEvaluators:
    def __init__(
        self,
        actual_docs,
        predicted_docs,
        match_method: str = "text",
        averaging_method: AveragingMethod = AveragingMethod.BOTH,
        matching_criteria: MatchingCriteria = MatchingCriteria.ALL,
    ) -> None:
        self.actual_docs = actual_docs
        self.predicted_docs = predicted_docs
        self.match_method = match_method
        self.averaging_method = averaging_method
        self.matching_criteria = matching_criteria

    def text_match(self, actual_text: str, predicted_text: str | list[str]) -> bool:
        if isinstance(predicted_text, list):
            return any(self.text_match(actual_text, text) for text in predicted_text)

        if self.match_method != "text":
            raise ValueError(f"Unsupported match_method: {self.match_method}")

        return actual_text == predicted_text

    def _relevant(self, actual_docs, predicted_doc) -> bool:
        return any(
            self.text_match(actual_doc.page_content, predicted_doc.page_content)
            for actual_doc in actual_docs
        )

    def calculate_hit_rate(self, k: Optional[int] = None) -> dict[str, float]:
        hit_count = 0
        for actual_docs, predicted_docs in zip(self.actual_docs, self.predicted_docs):
            predicted_texts = [doc.page_content for doc in predicted_docs[:k]]
            if self.matching_criteria == MatchingCriteria.ALL:
                hit = all(
                    any(self.text_match(actual_doc.page_content, pred_text) for pred_text in predicted_texts)
                    for actual_doc in actual_docs
                )
            else:
                hit = any(
                    any(self.text_match(actual_doc.page_content, pred_text) for pred_text in predicted_texts)
                    for actual_doc in actual_docs
                )
            hit_count += int(hit)

        return {"hit_rate": hit_count / len(self.actual_docs) if self.actual_docs else 0.0}

    def calculate_precision(self, k: Optional[int] = None) -> dict[str, float]:
        result = {}
        micro_precision = 0
        macro_precisions = []

        for actual_docs, predicted_docs in zip(self.actual_docs, self.predicted_docs):
            k_effective = min(k or len(predicted_docs), len(predicted_docs))
            relevant_count = sum(
                1 for predicted_doc in predicted_docs[:k_effective]
                if self._relevant(actual_docs, predicted_doc)
            )
            micro_precision += relevant_count
            macro_precisions.append(relevant_count / k_effective if k_effective > 0 else 0.0)

        total_predicted = sum(min(k or len(docs), len(docs)) for docs in self.predicted_docs)
        if self.averaging_method in [AveragingMethod.MICRO, AveragingMethod.BOTH]:
            result["micro_precision"] = micro_precision / total_predicted if total_predicted > 0 else 0.0
        if self.averaging_method in [AveragingMethod.MACRO, AveragingMethod.BOTH]:
            result["macro_precision"] = sum(macro_precisions) / len(macro_precisions) if macro_precisions else 0.0

        return result

    def calculate_recall(self, k: Optional[int] = None) -> dict[str, float]:
        result = {}
        micro_recall = 0
        macro_recalls = []

        for actual_docs, predicted_docs in zip(self.actual_docs, self.predicted_docs):
            relevant_count = sum(
                1 for actual_doc in actual_docs
                if any(self.text_match(actual_doc.page_content, doc.page_content) for doc in predicted_docs[:k])
            )
            micro_recall += relevant_count
            macro_recalls.append(relevant_count / len(actual_docs) if actual_docs else 0.0)

        total_actual = sum(len(docs) for docs in self.actual_docs)
        if self.averaging_method in [AveragingMethod.MICRO, AveragingMethod.BOTH]:
            result["micro_recall"] = micro_recall / total_actual if total_actual > 0 else 0.0
        if self.averaging_method in [AveragingMethod.MACRO, AveragingMethod.BOTH]:
            result["macro_recall"] = sum(macro_recalls) / len(macro_recalls) if macro_recalls else 0.0

        return result

    def calculate_f1_score(self, k: Optional[int] = None) -> dict[str, float]:
        precision = self.calculate_precision(k)
        recall = self.calculate_recall(k)
        result = {}

        if self.averaging_method in [AveragingMethod.MICRO, AveragingMethod.BOTH]:
            micro_p = precision.get("micro_precision", 0.0)
            micro_r = recall.get("micro_recall", 0.0)
            if micro_p + micro_r > 0:
                result["micro_f1"] = 2 * (micro_p * micro_r) / (micro_p + micro_r)

        if self.averaging_method in [AveragingMethod.MACRO, AveragingMethod.BOTH]:
            macro_p = precision.get("macro_precision", 0.0)
            macro_r = recall.get("macro_recall", 0.0)
            if macro_p + macro_r > 0:
                result["macro_f1"] = 2 * (macro_p * macro_r) / (macro_p + macro_r)

        return result

    def calculate_mrr(self, k: Optional[int] = None) -> dict[str, float]:
        reciprocal_ranks = []
        for actual_docs, predicted_docs in zip(self.actual_docs, self.predicted_docs):
            for rank, pred_doc in enumerate(predicted_docs[:k], start=1):
                if self._relevant(actual_docs, pred_doc):
                    reciprocal_ranks.append(1 / rank)
                    break
            else:
                reciprocal_ranks.append(0.0)

        return {"mrr": sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0}

    def calculate_map(self, k: Optional[int] = None) -> dict[str, float]:
        average_precisions = []
        for actual_docs, predicted_docs in zip(self.actual_docs, self.predicted_docs):
            relevant_docs = 0
            precision_sum = 0.0
            for i, pred_doc in enumerate(predicted_docs[:k], start=1):
                if self._relevant(actual_docs, pred_doc):
                    relevant_docs += 1
                    precision_sum += relevant_docs / i
            average_precisions.append(precision_sum / len(actual_docs) if actual_docs else 0.0)

        return {"map": sum(average_precisions) / len(average_precisions) if average_precisions else 0.0}

    def calculate_ndcg(self, k: Optional[int] = None) -> dict[str, float]:
        def dcg(relevances):
            return sum((2**rel - 1) / math.log2(i + 2) for i, rel in enumerate(relevances[:k]))

        ndcg_scores = []
        for actual_docs, predicted_docs in zip(self.actual_docs, self.predicted_docs):
            relevances = [
                1 if self._relevant(actual_docs, pred_doc) else 0
                for pred_doc in predicted_docs[:k]
            ]
            ideal_relevances = ([1] * len(actual_docs) + [0] * len(predicted_docs))[:k]
            dcg_score = dcg(relevances)
            idcg_score = dcg(ideal_relevances)
            ndcg_scores.append(dcg_score / idcg_score if idcg_score > 0 else 0.0)

        return {"ndcg": sum(ndcg_scores) / len(ndcg_scores) if ndcg_scores else 0.0}


class RougeOfflineRetrievalEvaluators(OfflineRetrievalEvaluators):
    _shared_tokenizer: KiwiTokenizer | None = None

    def __init__(
        self,
        actual_docs,
        predicted_docs,
        match_method: str = "rouge1",
        averaging_method: AveragingMethod = AveragingMethod.BOTH,
        matching_criteria: MatchingCriteria = MatchingCriteria.ALL,
        threshold: float = 0.5,
    ) -> None:
        normalized_method = match_method.lower()
        if normalized_method not in {"rouge1", "rouge2", "rougel"}:
            raise ValueError("match_method must be rouge1, rouge2, or rougeL")

        super().__init__(
            actual_docs=actual_docs,
            predicted_docs=predicted_docs,
            match_method=normalized_method,
            averaging_method=averaging_method,
            matching_criteria=matching_criteria,
        )
        self.threshold = threshold
        if RougeOfflineRetrievalEvaluators._shared_tokenizer is None:
            RougeOfflineRetrievalEvaluators._shared_tokenizer = KiwiTokenizer()
        self._tokenizer = RougeOfflineRetrievalEvaluators._shared_tokenizer

    def _tokens(self, text: str) -> tuple[str, ...]:
        return tuple(
            token.form.lower()
            for token in self._tokenizer.tokenize(text)
            if token.form.strip()
        )

    @staticmethod
    def _f1(overlap: int, predicted_count: int, actual_count: int) -> float:
        if predicted_count == 0 or actual_count == 0:
            return 0.0

        precision = overlap / predicted_count
        recall = overlap / actual_count
        return 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    @staticmethod
    def _lcs_length(left: tuple[str, ...], right: tuple[str, ...]) -> int:
        previous = [0] * (len(right) + 1)
        for left_token in left:
            current = [0]
            for index, right_token in enumerate(right, start=1):
                if left_token == right_token:
                    current.append(previous[index - 1] + 1)
                else:
                    current.append(max(current[-1], previous[index]))
            previous = current
        return previous[-1]

    @lru_cache(maxsize=4096)
    def rouge_score(self, actual_text: str, predicted_text: str) -> float:
        actual_tokens = self._tokens(actual_text)
        predicted_tokens = self._tokens(predicted_text)

        if not actual_tokens and not predicted_tokens:
            return 1.0

        if self.match_method == "rougel":
            overlap = self._lcs_length(actual_tokens, predicted_tokens)
            return self._f1(overlap, len(predicted_tokens), len(actual_tokens))

        n = 1 if self.match_method == "rouge1" else 2
        actual_ngrams = Counter(zip(*(actual_tokens[offset:] for offset in range(n))))
        predicted_ngrams = Counter(zip(*(predicted_tokens[offset:] for offset in range(n))))
        if not actual_ngrams and not predicted_ngrams:
            return float(actual_tokens == predicted_tokens)
        overlap = sum((actual_ngrams & predicted_ngrams).values())
        return self._f1(overlap, sum(predicted_ngrams.values()), sum(actual_ngrams.values()))

    def text_match(self, actual_text: str, predicted_text: str | list[str]) -> bool:
        if isinstance(predicted_text, list):
            return any(self.text_match(actual_text, text) for text in predicted_text)
        return self.rouge_score(actual_text, predicted_text) >= self.threshold

    def calculate_ndcg(self, k: Optional[int] = None) -> dict[str, float]:
        def dcg(relevances):
            return sum((2**rel - 1) / math.log2(i + 2) for i, rel in enumerate(relevances[:k]))

        ndcg_scores = []
        for actual_docs, predicted_docs in zip(self.actual_docs, self.predicted_docs):
            relevances = [
                max(
                    (
                        self.rouge_score(actual_doc.page_content, predicted_doc.page_content)
                        for actual_doc in actual_docs
                    ),
                    default=0.0,
                )
                for predicted_doc in predicted_docs[:k]
            ]
            ideal_relevances = sorted(relevances, reverse=True)
            dcg_score = dcg(relevances)
            idcg_score = dcg(ideal_relevances)
            ndcg_scores.append(dcg_score / idcg_score if idcg_score > 0 else 0.0)

        return {"ndcg": sum(ndcg_scores) / len(ndcg_scores) if ndcg_scores else 0.0}
