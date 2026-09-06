# M9.5 튜토리얼 5 — 개선은 측정된 델타다

멀티홉 질문 — "X가 2022년과 2023년 사이 어떻게 변했나" — 는 단일 임베딩 질의에서 recall을 잃고, 골든셋은 M3부터 이 순간을 기다리며 `multi_hop` 카테고리를 실어 왔다. 이 문서는 질문을 쪼개고, 부분별로 검색하고, 랭킹을 융합한다 — 그리고 그 아이디어 전체를 무수정 M3 하니스에 제출한다. **아티팩트의 카테고리별 델타가 아닌 검색 개선은 일화이기 때문이다.**

**선행 조건:** M9.4 완료, `uv run pytest tests/agent/test_05_builtin_tools.py -q` 통과.

### 무엇을 정의하고, 무엇을 구현하고, 무엇을 들여다볼 것인가

| 영역 | 학습 행동 | 가져갈 것 |
|---|---|---|
| `QueryDecomposition` + `decompose_query` | fail-closed 분해를 **구현한다** | 폴백은 원래 질문이지 절대 에러가 아니다 |
| `merge_ranked_lists` | n-리스트 RRF를 **구현한다** | 순위만 쓰는 융합, 결정론적 동점 처리 — M2 규칙의 일반화 |
| 리트리버 + 비교 | **구현하고, 측정을 돌린다** | M3 하니스가 새 리트리버를 무수정으로 받는다 |

### 1. 분해는 fail-closed다

#### `app/agent/decompose.py` 생성 — 분해

**학습 행동 — fail-closed 분해를 구현한다:** 실패 모드를 열거하고 전부가 같은 폴백에 도착하는지 확인한다.

<!-- src: app/agent/decompose.py::QueryDecomposition,decompose_query -->
```python
class QueryDecomposition(StrictAgentModel):
    """The structured decomposition contract returned by the LLM."""

    sub_questions: tuple[Annotated[StrictStr, Field(min_length=1)], ...]

    @model_validator(mode="after")
    def validate_sub_questions(self) -> Self:
        """Reject empty, oversized, blank, or duplicated decompositions."""
        if not 1 <= len(self.sub_questions) <= MAX_SUB_QUESTIONS:
            raise ValueError(f"decomposition requires 1 to {MAX_SUB_QUESTIONS} sub-questions")
        normalized = [" ".join(question.split()).casefold() for question in self.sub_questions]
        if any(not question for question in normalized):
            raise ValueError("sub-questions must not be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("sub-questions must be unique")
        return self


async def decompose_query(
    question: str,
    *,
    llm_provider: LLMProvider,
    provider_budget: ProviderBudget,
) -> tuple[str, ...]:
    """Return validated sub-questions, falling back to the original on failure.

    The fallback is deliberate: decomposition is an optimization, and an
    unavailable or refusing provider must degrade to the measured single-query
    baseline instead of failing the retrieval request outright.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must not be blank")
    prompt = Prompt(system=DECOMPOSE_SYSTEM_PROMPT, user=question)
    result = await llm_provider.complete(prompt, QueryDecomposition, provider_budget)
    if result.status != "ok" or result.parsed is None:
        return (question,)
    return result.parsed.sub_questions
```

**코드에서 꼭 볼 것**

- `QueryDecomposition`은 정규화되고 유일한 하위 질문 1~4개를 허용한다. 중복이나 장문 에세이로 "분해"하는 모델은 검증에 실패하고, 검증 실패도 폴백으로 가는 또 하나의 길일 뿐이다.
- **모든 실패 — provider 예외, 깨진 JSON, 빈 리스트 — 는 원래 질문으로 폴백하므로, 분해는 recall 경로를 더할 수만 있지 baseline을 깎을 수는 없다.** LLM이 딸꾹질할 때 검색을 더 나쁘게 만들 수 있는 기능은 개선이 아니라 부채다.

### 2. 융합은 이번에도 순위만 쓴다

#### `app/agent/decompose.py` 확장 — n-리스트 reciprocal-rank fusion

**학습 행동 — n-리스트 RRF를 구현한다:** M2의 2-리스트 융합과 비교해 무엇이 일반화됐고 무엇이 아닌지 짚는다.

<!-- src: app/agent/decompose.py::merge_ranked_lists -->
```python
def merge_ranked_lists(
    ranked_lists: tuple[tuple[ChunkHit, ...], ...],
    k: int,
    *,
    rrf_k: int = DEFAULT_RRF_K,
) -> tuple[ChunkHit, ...]:
    """Fuse per-sub-question rankings with reciprocal-rank scores over n lists.

    This is the M2.5 fusion rule generalized from two fixed components to one
    list per sub-question: only ranks contribute, so sub-questions with
    incomparable native scores still merge deterministically.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    scores: dict[int, float] = {}
    first_seen: dict[int, ChunkHit] = {}
    for hits in ranked_lists:
        for rank, hit in enumerate(hits, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (rrf_k + rank)
            first_seen.setdefault(hit.chunk_id, hit)
    fused = sorted(
        first_seen.values(),
        key=lambda hit: (
            -scores[hit.chunk_id],
            hit.doc_id,
            hit.source_sha256,
            hit.start_char,
            hit.end_char,
            hit.chunk_id,
        ),
    )
    return tuple(hit.model_copy(update={"score": scores[hit.chunk_id]}) for hit in fused[:k])
```

**코드에서 꼭 볼 것**

- 서로 다른 하위 질문의 점수는 비교 불가능하다 — M2의 dense 대 lexical 융합과 같은 교훈이므로, 병합은 같은 `rrf_k` 감쇠로 순위만 쓴다.
- 동점 처리는 dict 순서가 아니라 완전한 결정론적 키다. 같은 리스트로 두 번 돌리면 같은 융합 랭킹이 나와야 하고, 아니라면 다음 절의 평가는 노이즈를 측정한다.
- 융합된 히트는 RRF 점수를 실은 `model_copy` 갱신이다 — 원본 히트는 M1의 값 객체 규칙대로 동결된 채 남는다.

### 3. 주장은 하니스를 통과한다

#### `app/agent/decompose.py` 확장 — 그대로 꽂히는 리트리버

**학습 행동 — 리트리버를 구현한다:** 본문을 쓰기 전에 시그니처를 M3의 `Retriever` 타입과 대조한다.

<!-- src: app/agent/decompose.py::make_decomposed_retriever -->
```python
def make_decomposed_retriever(
    session: AsyncSession,
    *,
    llm_provider: LLMProvider,
    provider_budget: ProviderBudget,
    embedding_provider: EmbeddingProvider | None = None,
    candidate_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
    filters: RetrievalFilters | None = None,
):
    """Return an M3-compatible ``Retriever`` that decomposes before retrieving.

    The callable signature matches ``evaluate_retriever``'s ``Retriever``
    contract exactly, so the decomposed strategy plugs into the existing
    evaluation harness without modifying any M3 file.
    """

    async def retrieve_decomposed(question: str, k: int) -> tuple[ChunkHit, ...]:
        sub_questions = await decompose_query(
            question,
            llm_provider=llm_provider,
            provider_budget=provider_budget,
        )
        ranked_lists = []
        for sub_question in sub_questions:
            result = await retrieve(
                session,
                sub_question,
                provider=embedding_provider,
                k=k,
                candidate_k=candidate_k,
                filters=filters,
                rrf_k=rrf_k,
            )
            ranked_lists.append(result.hits)
        return merge_ranked_lists(tuple(ranked_lists), k, rrf_k=rrf_k)

    return retrieve_decomposed
```

#### `app/agent/eval.py` 생성 — 카테고리별 측정

**학습 행동 — 측정을 돌린다:** 배포물은 개선됐다는 문장이 아니라 아티팩트 두 개와 델타 표다.

<!-- src: app/agent/eval.py::category_metrics,run_decomposition_comparison -->
```python
def category_metrics(evaluation: RetrievalEvaluation) -> dict[str, dict[str, float]]:
    """Return macro retrieval metrics per golden category, scored cases only.

    The suite-level score hides exactly the split this module exists to show:
    a decomposition change should move ``multi_hop`` without touching
    ``simple_lookup``. Absent cases stay excluded, mirroring M3's scoring rule.
    """
    grouped: dict[str, list[Any]] = {}
    for case in evaluation.cases:
        if case.score is None:
            continue
        grouped.setdefault(case.golden.category, []).append(case.score)
    metrics: dict[str, dict[str, float]] = {}
    for category in sorted(grouped):
        scores = grouped[category]
        count = len(scores)
        metrics[category] = {
            "scored_case_count": float(count),
            "recall_at_k": sum(score.recall_at_k for score in scores) / count,
            "hit_rate_at_k": sum(score.hit_at_k for score in scores) / count,
            "mrr": sum(score.reciprocal_rank for score in scores) / count,
        }
    return metrics


def _arm_payload(evaluation: RetrievalEvaluation) -> dict[str, Any]:
    return {
        "metrics": evaluation.metric_values(),
        "categories": category_metrics(evaluation),
    }


def _artifact_name(recorded_at: datetime, label: str) -> str:
    timestamp = recorded_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{label}.json"


async def run_decomposition_comparison(
    cases: Sequence[GoldenCase],
    *,
    baseline_retriever: Retriever,
    decomposed_retriever: Retriever,
    baseline_config: Mapping[str, Any],
    decomposed_config: Mapping[str, Any],
    suite: str,
    artifact_dir: str | Path,
    k: int = 5,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate both retrievers on one golden suite and write paired artifacts.

    Both arms run through the unmodified M3 harness, so their artifacts have
    the same schema as every other evaluation and remain comparable with the
    stored baselines. The returned payload adds the per-category split and the
    metric deltas the ablation narrative needs.
    """
    moment = recorded_at or datetime.now(UTC)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    baseline = await evaluate_retriever(
        cases,
        baseline_retriever,
        suite=suite,
        config=baseline_config,
        k=k,
        recorded_at=moment,
    )
    decomposed = await evaluate_retriever(
        cases,
        decomposed_retriever,
        suite=suite,
        config=decomposed_config,
        k=k,
        recorded_at=moment,
    )
    directory = Path(artifact_dir)
    baseline_path = write_evaluation_artifact(
        directory / _artifact_name(moment, "decomposition-baseline"),
        baseline,
    )
    decomposed_path = write_evaluation_artifact(
        directory / _artifact_name(moment, "decomposition-decomposed"),
        decomposed,
    )
    baseline_categories = category_metrics(baseline)
    decomposed_categories = category_metrics(decomposed)
    deltas = {
        category: {
            "recall_at_k": decomposed_categories[category]["recall_at_k"]
            - baseline_categories[category]["recall_at_k"],
            "mrr": decomposed_categories[category]["mrr"] - baseline_categories[category]["mrr"],
        }
        for category in sorted(set(baseline_categories) & set(decomposed_categories))
    }
    return {
        "suite": suite,
        "k": k,
        "baseline": _arm_payload(baseline),
        "decomposed": _arm_payload(decomposed),
        "category_deltas": deltas,
        "artifacts": {
            "baseline": str(baseline_path),
            "decomposed": str(decomposed_path),
        },
    }
```

**코드에서 꼭 볼 것**

- `make_decomposed_retriever`는 M3의 `Retriever` 계약에 맞는 평범한 콜러블을 반환한다. **`app/evals`는 한 줄도 바뀌지 않는다: 하니스는 어떤 리트리버든 심판하도록 지어졌고, 이것이 그 보상이다.**
- `category_metrics`는 골든 카테고리별로 자르고 채점되지 않은 absent 케이스를 제외한다. M3 집계와 정확히 같은 방식이다 — 채점 안 된 행을 슬쩍 포함한 카테고리 평균은 같은 이름을 쓴 다른 지표다.
- `run_decomposition_comparison`은 같은 골든셋 위에서 baseline과 분해 리트리버를 돌리고 두 아티팩트와 카테고리별 델타를 쓴다. **흥미로운 숫자는 평평한 전체 델타에 맞세운 `multi_hop` 델타다 — 개선 주장은 그 슬라이스에 살거나 아무 데도 살지 않는다.**

### 집중 테스트와 그것이 지키는 계약

```bash
uv run pytest tests/agent/test_06_decompose.py -q
```

| 테스트가 깨뜨리는 것 | 지키는 계약 |
|---|---|
| 분해 도중 예외를 던지는 provider | 폴백은 원래 질문을 반환한다 |
| 중복되거나 빈 하위 질문 | 분해 계약은 팽팽하게 유지된다 |
| 동순위를 가진 재정렬 입력 리스트 | 융합은 결정론적이고 순위만 쓴다 |
| 채점되지 않은 케이스를 포함한 카테고리 슬라이스 | 슬라이스 지표도 M3 채점 규칙을 지킨다 |

### 이제 설명할 수 있어야 하는 것

답은 위의 **굵은 핵심 문장**에 있다.

- **분해 실패는 왜 원래 질문을 반환해야 하는가?**
  - **답:** 여기서 fail-closed는 baseline이 바닥이라는 뜻이다 — 기능은 recall 경로를 더할 수 있을 뿐, 존재하지 않는 것보다 나빠질 수는 없다.
- **왜 점수가 아니라 순위로 융합하는가?**
  - **답:** 서로 다르게 임베딩된 하위 질문들의 점수는 비교 불가능하다. M2가 dense와 lexical 점수를 섞기를 거부한 것과 같은 이유다.
- **"M3 하니스가 무수정으로 돈다"가 왜 이 체크포인트의 헤드라인인가?**
  - **답:** 심판이 도전자보다 먼저 존재했기에 주장이 신뢰를 얻는다. 기능에 맞춰 조정된 평가는 아무것도 증명하지 못한다.

---

[← 이전: 내장 도구](04-builtin-tools.md) · [모듈 개요](../03-build.md) · [다음: MCP와 CLI →](06-mcp-cli.md)
