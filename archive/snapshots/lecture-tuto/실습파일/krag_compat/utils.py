import ast
import math
from typing import Any

import pandas as pd
from langchain_classic.retrievers import EnsembleRetriever
from tqdm.auto import tqdm

from krag_compat.document import KragDocument as Document
from krag_compat.evaluators import (
    AveragingMethod,
    MatchingCriteria,
    OfflineRetrievalEvaluators,
    RougeOfflineRetrievalEvaluators,
)


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, str):
        value = ast.literal_eval(value)
    if isinstance(value, (list, tuple)):
        return list(value)
    if value is None or pd.isna(value):
        return []
    return [value]


def context_to_document(df_test: pd.DataFrame, idx: int) -> list[Document]:
    row = df_test.iloc[idx]
    contexts = _as_list(row["context"])
    sources = _as_list(row["source"])
    doc_ids = _as_list(row["doc_id"])

    return [
        Document(page_content=str(context), metadata={"source": source, "doc_id": doc_id})
        for context, source, doc_id in zip(contexts, sources, doc_ids)
    ]


def setup_retriever(retriever: Any, k: int) -> Any:
    nested_retriever = getattr(retriever, "retriever", None)
    if nested_retriever is not None and hasattr(nested_retriever, "search_kwargs"):
        nested_retriever.search_kwargs["k"] = k
    elif hasattr(retriever, "search_kwargs"):
        retriever.search_kwargs["k"] = k
    elif hasattr(retriever, "k"):
        retriever.k = k
    elif "runnables" in type(retriever).__module__ and hasattr(retriever, "with_config"):
        return retriever.with_config({"configurable": {"search_kwargs": {"k": k}}})
    return retriever


def flatten_metrics(metrics: dict[str, Any], k: int) -> dict[str, float]:
    flattened = {}
    for key, value in metrics.items():
        if isinstance(value, dict):
            flattened.update({f"{sub_key}@{k}": sub_value for sub_key, sub_value in value.items()})
        else:
            flattened[f"{key}@{k}"] = value
    return flattened


def evaluate_retrieval_at_K(
    df_qa_test: pd.DataFrame,
    k: int,
    retrievers: dict[str, Any],
    ensemble: bool = False,
    rouge_method: str | None = None,
    threshold: float = 0.5,
    ensemble_weights: list[float] | None = None,
    averaging_method: AveragingMethod = AveragingMethod.BOTH,
    matching_criteria: MatchingCriteria = MatchingCriteria.PARTIAL,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    set_retrievers = {
        name: setup_retriever(retriever, k)
        for name, retriever in retrievers.items()
    }

    if ensemble:
        ensemble_retrievers = list(set_retrievers.values())
        if not ensemble_retrievers:
            raise ValueError("At least one retriever is required for an ensemble")
        weights = ensemble_weights or [1 / len(ensemble_retrievers)] * len(ensemble_retrievers)
        if len(weights) != len(ensemble_retrievers):
            raise ValueError("ensemble_weights must match the number of retrievers")
        set_retrievers["Ensemble"] = EnsembleRetriever(
            retrievers=ensemble_retrievers,
            weights=weights,
        )

    print("Evaluating retrieval performance...")
    print(
        f"ROUGE method: {rouge_method}, threshold: {threshold}, "
        f"averaging method: {averaging_method}, matching criteria: {matching_criteria}"
    )
    print(f"Ensemble: {ensemble}, Ensemble weights: {ensemble_weights}")
    print(f"Number of questions: {len(df_qa_test)}")

    outputs = []
    rows = tqdm(
        enumerate(df_qa_test.iterrows()),
        total=len(df_qa_test),
        desc="Processing questions",
    )
    for position, (_, row) in rows:
        question = row["question"]
        context_docs = context_to_document(df_qa_test, position)

        for retriever_name, retriever in set_retrievers.items():
            try:
                retrieved_docs = retriever.invoke(question)
                evaluator_kwargs = {
                    "actual_docs": [context_docs],
                    "predicted_docs": [retrieved_docs],
                    "averaging_method": averaging_method,
                    "matching_criteria": matching_criteria,
                }
                if rouge_method:
                    evaluator = RougeOfflineRetrievalEvaluators(
                        match_method=rouge_method,
                        threshold=threshold,
                        **evaluator_kwargs,
                    )
                else:
                    evaluator = OfflineRetrievalEvaluators(
                        match_method="text",
                        **evaluator_kwargs,
                    )

                metrics = {
                    "hit_rate": evaluator.calculate_hit_rate(k),
                    "mrr": evaluator.calculate_mrr(k),
                    "recall": evaluator.calculate_recall(k),
                    "precision": evaluator.calculate_precision(k),
                    "f1": evaluator.calculate_f1_score(k),
                    "map": evaluator.calculate_map(k),
                    "ndcg": evaluator.calculate_ndcg(k),
                }
                outputs.append(
                    {
                        "question": question,
                        "retriever": retriever_name,
                        **flatten_metrics(metrics, k),
                    }
                )
            except Exception as exc:
                print(f"Error evaluating retriever {retriever_name} for question '{question}': {exc}")

    df_output = pd.DataFrame(outputs)
    if df_output.empty:
        df_mean = pd.DataFrame()
    else:
        df_mean = df_output.groupby("retriever").mean(numeric_only=True)

    print("Evaluation complete.")
    return df_mean, df_output


def visualize_retrieval_at_K(df_mean: pd.DataFrame, k: int) -> None:
    import matplotlib.pyplot as plt

    metrics = [column for column in df_mean.columns if f"@{k}" in column]
    if not metrics:
        raise ValueError(f"No @{k} metrics found in df_mean")

    n_cols = 5
    n_rows = math.ceil(len(metrics) / n_cols)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5 * n_cols, 4 * n_rows), squeeze=False)
    fig.suptitle(f"Retrieval Performance Metrics @{k}", fontsize=16, y=1.02)

    flat_axes = list(axes.flat)
    for metric, ax in zip(metrics, flat_axes):
        values = df_mean[metric]
        bars = ax.bar(df_mean.index.astype(str), values)
        ax.set_title(metric.split("@")[0], pad=20)
        ax.set_xlabel("")
        ax.set_ylabel("Score")
        ax.tick_params(axis="x", rotation=45)
        ax.set_ylim(0, max(1.0, float(values.max()) * 1.1))
        ax.bar_label(bars, labels=[f"{value:.2f}" for value in values], padding=3)

    for ax in flat_axes[len(metrics):]:
        fig.delaxes(ax)

    plt.tight_layout()
    plt.show()
