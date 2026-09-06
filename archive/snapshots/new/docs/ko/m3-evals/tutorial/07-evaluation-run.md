# M3.4 튜토리얼 7 — 평가를 실행하고 예산을 잰다

튜토리얼 5는 실험군을, 튜토리얼 6은 실행 하나가 남길 레코드를 정의했다. 두 문서 모두 하지 않은 일이 실행이다. 아직 질의 한 번 검색되지 않았고, 시계도 한 번 읽히지 않았다. 이 문서의 함수 여섯 개가 그 간극을 메운다 — 검색을 실행하고, 걸린 시간을 재고, 결과를 저장한다.

이 계층이 막아야 하는 실패는 조용한 오귀속이다. 평가기가 조금이라도 잘못 배선되면 — 실제로 돌리지 않은 설정 아래 결과가 저장되거나, 쓰지 않은 랭커의 이름이 실험군에 붙으면 — 겉보기에 멀쩡한 아티팩트가 나온다. 모든 필드가 채워져 있고, 모든 숫자가 그럴듯하고, 어디에도 오류가 없다. 몇 주 뒤 그 아티팩트가 청킹이나 랭커 결정을 엉뚱한 방향으로 이끌어도, 파일 안의 무엇도 바꿔치기를 드러내지 못한다.

그래서 이 문서의 불변조건은 이것이다. **실행 하나의 아티팩트에는 자신의 집계값을 다시 유도하는 데 필요한 모든 것이 들어 있어야 하고, 그 집계값은 정확히 하나의 설정에 귀속되어야 한다.** 아래 함수들은 전부 이 아티팩트를 채우거나 이 귀속을 지키는 일을 한다.

**선행 조건:** 튜토리얼 6에서 `retrieval_eval.py`의 레코드 계층을 작성한 상태여야 한다. 테스트는 튜토리얼 8에서 함께 돈다.

### 예산도 측정 대상이다

품질 지표만 측정하면 시스템의 절반만 보는 것이다. 성능 관문 두 개를 함께 둔다.

- 실험군 하나를 **인덱싱**하는 데 300초
- 순차 검색 질의 **200회**를 90초

**이 관문이 있어야 재현율이 0.03 오르는 대신 인덱싱이 세 배 느려지는 교환을 결과에서 확인할 수 있다.** 품질 지표만 보고 조정하면 어느 시점부터 실사용이 불가능한 지연 시간을 갖게 된다.

이 임계값은 가정이 아니다. 이 모듈 뒤에 커밋된 실행이 두 관문을 실제로 측정했다. 저자의 기기에서 500자 실험군 인덱싱(문서 20건, 청크 12,984개)은 허용된 300초 중 38.5초를 썼고, 1200자 실험군(청크 9,172개)은 33.9초를 썼으며, 1200자 코퍼스에 대한 순차 hybrid 질의 200회는 허용된 90초 중 29.79초가 걸렸다 — 질의당 평균 148.9ms, p95 213.6ms, 최악 283.4ms. 근거는 직접 읽을 수 있다.

```bash
python3 -c "import json; d = json.load(open('data/eval_runs/20260824T203336Z-budgets.json')); print(json.dumps({'indexing': d['indexing'], 'query_budget': d['query_budget']}, indent=2))"
```

이 파일의 내력을 적어 둔다. 이것은 튜토리얼 8에서 조립하는 CLI가 쓴 파일이다. 실행이 끝나면 `_run_cli`가 인덱싱 측정 두 건과 질의 예산 측정 한 건을, 같은 실행이 남긴 실험군별 아티팩트 열 개 옆에 `{timestamp}-budgets.json` 하나로 직렬화한다. `data/eval_runs`에 커밋된 사본은 2026-08-24의 기본 deterministic 명령 실행에서 나왔고, `measurement_provenance` 블록에 어떤 임베딩 공급자가 돌았는지, 예산 질의를 어떤 lexical 랭커가 처리했는지, 코퍼스가 격리된 임시 테이블이었는지, 유료 API 호출이 없었는지가 기록되어 있다. 이 파일은 이후 아무도 갱신하지 않는다 — 다음 실행은 옆에 새 타임스탬프 파일을 쓰고, 이전 파일은 역사로 남는다.

예산 JSON에는 **실제 관측값**만 기록한다. 테스트가 이 값을 임의로 채우지 않는다. 측정값이 실제와 다르면 그 값을 근거로 한 모든 판단이 무효가 된다.

한계도 정직하게 적는다. `passed`는 기기 하나, 공급자 하나, 격리된 코퍼스 하나에 대한 벽시계 사실이다. 알고리즘 비용이 로컬에서 예산 안에 든다는 것을 증명할 뿐, 호스팅된 배포의 지연 시간을 보장하지 않는다. deterministic 공급자를 실제 임베딩 API로 바꾸면 vector와 hybrid 질의마다 네트워크 왕복이 더해진다.

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `evaluate_retriever` | 실행 루프를 **직접 구현** | 28개를 돌리고 24개를 채점하는 지점 |
| `write_evaluation_artifact` | **구조 작성 후 직렬화 검토** | 아티팩트가 안정적이어야 하는 이유 |
| 예산 측정 두 함수 | 측정 규칙을 **직접 구현** | 시계를 어디서 읽는가 |
| `make_retriever` | 전략 바인딩을 **직접 구현** | 세 전략이 한 인터페이스를 갖는 방법 |
| `persist_evaluation` | **호출 순서 검토** | 기준선을 저장 전에 읽어야 하는 이유 |

### 1. 28개를 돌리고 24개를 채점한다

#### `app/evals/retrieval_eval.py` 확장 — 평가 실행

**학습 행동 — 실행 루프 구현:** 루프를 직접 작성하고, `case.answers`가 비어 있을 때 어떤 경로를 지나는지 추적한다.

코드에 들어가기 전에 한 줄로 되짚는다. `retriever` 인자는 (질문, k) → 히트 형태의 비동기 호출 가능 객체일 뿐이며, 4절의 `make_retriever`가 M2 검색 함수들을 감싸 만들어 주는 클로저가 바로 그것이다. `evaluate_retriever`는 의도적으로 그 이상을 알지 못한다.

<!-- src: app/evals/retrieval_eval.py::evaluate_retriever -->
```python
async def evaluate_retriever(
    cases: Sequence[GoldenCase],
    retriever: Retriever,
    *,
    suite: str,
    config: Mapping[str, Any],
    k: int = 5,
    clock: Clock = time.perf_counter_ns,
    recorded_at: datetime | None = None,
) -> RetrievalEvaluation:
    """Evaluate every case once while scoring only source-bearing positives."""
    if not isinstance(suite, str) or not suite.strip():
        raise ValueError("suite must be nonblank")
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")
    ordered = tuple(sorted(cases, key=lambda case: case.id))
    if not ordered:
        raise ValueError("golden cases must not be empty")
    if len({case.id for case in ordered}) != len(ordered):
        raise ValueError("golden case ids must be unique")
    provenance = _golden_provenance(ordered)

    results: list[CaseEvaluation] = []
    scores: list[CaseScore] = []
    latencies: list[float] = []
    for case in ordered:
        started = clock()
        hits = tuple(await retriever(case.question, k))
        elapsed_ms = (clock() - started) / 1_000_000
        if elapsed_ms < 0:
            raise ValueError("clock must be monotonic")
        latencies.append(elapsed_ms)
        case_score = score_case(case.id, case.answers, hits, k) if case.answers else None
        if case_score is not None:
            scores.append(case_score)
        results.append(
            CaseEvaluation(
                golden=case,
                latency_ms=elapsed_ms,
                hits=hits,
                score=case_score,
            )
        )

    return RetrievalEvaluation(
        suite=suite,
        recorded_at=recorded_at or datetime.now(UTC),
        config=_canonical_config(config),
        provenance=provenance,
        score=score_suite(scores),
        latency=_latency_summary(latencies),
        cases=tuple(results),
    )
```

**코드에서 꼭 볼 것**

- **28개를 실행하고 24개를 채점하는 구분은 `score_case(...) if case.answers else None` 한 줄이 결정한다.** absent 사례도 검색은 실행되고 hit도 기록되지만, `scores` 목록에는 들어가지 않는다.
- `clock`을 주입할 수 있고 기본값은 `time.perf_counter_ns`다. **벽시계가 아니라 단조 카운터를 쓰므로 NTP 보정으로 시각이 뒤로 이동해도 측정된 지연 시간이 음수가 되지 않는다.**
- 그럼에도 `elapsed_ms < 0`을 검사한다. 주입된 시계는 단조가 아닐 수 있고, 음수 지연이 섞이면 `_latency_summary`가 오류 없이 잘못된 백분위를 반환한다.
- `sorted(cases, key=...)`로 사례 순서를 고정한다. 지연 시간 목록의 순서가 실행마다 달라지면 같은 조건에서도 p95 값이 달라진다.
- `recorded_at or datetime.now(UTC)`로 기록 시각을 주입할 수 있다. 테스트가 시각을 고정한 상태로 결과를 검증할 수 있다.

> **개념 — absent 사례를 실행하되 채점하지 않는 이유**
>
> 골든 28개 중 4개는 absent 사례다. 코퍼스에 답이 없는 것이 정답이므로, 히트와 비교할 정답 구간 자체가 없다. 이런 사례의 재현율은 정의되지 않는다 — 0으로 치면 올바르게 동작한 검색기가 벌점을 받고, 1로 치면 근거 없이 평균이 부풀어 오른다. 점수에서 제외하는 것이 유일하게 정직한 산술이다.
>
> 뻔한 단순화는 아예 건너뛰는 것인데, 그러면 증거 두 종류가 조용히 사라진다. absent 질문도 실제 작업량의 일부이므로 그 지연 시간은 예산 그림에 속한다. 그리고 기록된 히트는 M4의 부재 판정 계층이 필요로 하는 바로 그 증거다. "문서에 없다"를 어떻게 말할지 정하려면, 정답이 없을 때 검색이 무엇을 돌려주는지부터 봐야 한다.
>
> 그래서 루프는 28개를 전부 돌리고, 28개 전부의 히트와 지연 시간을 기록하되, 정답 구간이 있는 24개만 점수 목록에 넣는다. 아티팩트는 이 구분을 provenance로 남긴다. 전체 28, 채점 24, 미채점 4.

### 2. 아티팩트는 안정적이어야 한다

#### `app/evals/retrieval_eval.py` 확장 — 아티팩트 기록

**학습 행동 — 구조 작성 후 직렬화 검토:** `json.dumps`에 넘기는 인자 네 개가 각각 무엇을 보장하는지 확인한다.

<!-- src: app/evals/retrieval_eval.py::write_evaluation_artifact -->
```python
def write_evaluation_artifact(path: str | Path, evaluation: RetrievalEvaluation) -> Path:
    """Write one stable UTF-8 raw artifact and return its path."""
    artifact_path = Path(path)
    if artifact_path.suffix != ".json":
        raise ValueError("evaluation artifact path must end in .json")
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        evaluation.artifact_payload(),
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    artifact_path.write_text(payload + "\n", encoding="utf-8")
    return artifact_path
```

**코드에서 꼭 볼 것**

- **`sort_keys=True`와 `indent=2`가 같은 내용을 같은 바이트로 만들므로, 두 실행의 아티팩트를 `diff`로 직접 비교할 수 있다.** 두 옵션이 없으면 딕셔너리 순서만 달라져도 파일 전체가 바뀐 것으로 보인다.
- `allow_nan=False`는 `NaN` 지연 시간이 파일에 들어가는 것을 막는다. JSON 표준에 없는 값이라 다른 도구가 이 파일을 읽지 못한다.
- `.json` 확장자를 요구한다. 디렉터리나 확장자 없는 경로를 넘겨도 파일이 만들어지면, 이후 아티팩트를 수집하는 코드가 그 파일을 찾지 못한다.
- `mkdir(parents=True, exist_ok=True)`로 아티팩트 디렉터리를 만든다. 측정을 모두 마친 뒤 저장 단계에서 디렉터리가 없어 실패하면 그 실행의 결과가 남지 않는다.

5절에서 데이터베이스에도 저장하는데 왜 파일을 따로 남기는가. 두 기록이 답하는 질문이 다르기 때문이다. 데이터베이스 행에는 집계 지표 일곱 개와 `raw_artifact_path` 포인터만 들어간다 — 실행끼리 비교하기에는 충분하지만, 어느 사례가 실패했고 대신 무엇이 검색됐는지는 답하지 못한다. 원시 아티팩트는 사례마다 히트와 구간을 전부 담고 있어 집계값을 언제든 다시 유도할 수 있다. 행으로는 아티팩트를 복원할 수 없지만 아티팩트로는 행을 복원할 수 있다. 파일을 잃으면 증거를 잃는 것이고, 그래서 영속화를 고려하기도 전에 파일부터 쓴다.

### 3. 시계를 어디서 읽는가

#### `app/evals/retrieval_eval.py` 확장 — 예산 측정

**학습 행동 — 측정 규칙 구현:** `previous`가 어떻게 갱신되는지 따라가며 구현한다. `measure_query_budget`의 루프가 그 지점이다.

<!-- src: app/evals/retrieval_eval.py::measure_query_budget,assess_indexing_budget -->
```python
async def measure_query_budget(
    queries: Sequence[str],
    retriever: Retriever,
    *,
    k: int = 5,
    query_count: int = QUERY_BUDGET_COUNT,
    budget_seconds: float = QUERY_BUDGET_SECONDS,
    clock: Clock = time.perf_counter_ns,
) -> QueryBudgetMeasurement:
    """Repeat nonempty queries sequentially and assess the wall-clock budget."""
    if not queries or any(not isinstance(query, str) or not query.strip() for query in queries):
        raise ValueError("queries must contain nonblank strings")
    if isinstance(query_count, bool) or not isinstance(query_count, int) or query_count <= 0:
        raise ValueError("query_count must be a positive integer")
    if k <= 0:
        raise ValueError("k must be positive")
    if not math.isfinite(budget_seconds) or budget_seconds <= 0:
        raise ValueError("budget_seconds must be finite and positive")

    previous = clock()
    latencies: list[float] = []
    for index in range(query_count):
        await retriever(queries[index % len(queries)], k)
        current = clock()
        elapsed_ms = (current - previous) / 1_000_000
        if elapsed_ms < 0:
            raise ValueError("clock must be monotonic")
        latencies.append(elapsed_ms)
        previous = current

    summary = _latency_summary(latencies)
    total_seconds = summary.total_ms / 1_000
    return QueryBudgetMeasurement(
        query_count=query_count,
        total_seconds=total_seconds,
        budget_seconds=budget_seconds,
        passed=total_seconds <= budget_seconds,
        mean_ms=summary.mean_ms,
        p50_ms=summary.p50_ms,
        p95_ms=summary.p95_ms,
        max_ms=summary.max_ms,
    )


def assess_indexing_budget(
    *,
    target_text_chars: int,
    document_count: int,
    chunk_count: int,
    embedding_provider: str,
    total_seconds: float,
    budget_seconds: float = INDEXING_BUDGET_SECONDS,
) -> IndexingBudgetMeasurement:
    """Validate and assess one measured indexing duration."""
    if target_text_chars <= 0 or document_count <= 0 or chunk_count <= 0:
        raise ValueError("indexing counts and target_text_chars must be positive")
    if not embedding_provider.strip():
        raise ValueError("embedding_provider must be nonblank")
    if not math.isfinite(total_seconds) or total_seconds < 0:
        raise ValueError("total_seconds must be finite and nonnegative")
    if not math.isfinite(budget_seconds) or budget_seconds <= 0:
        raise ValueError("budget_seconds must be finite and positive")
    return IndexingBudgetMeasurement(
        target_text_chars=target_text_chars,
        document_count=document_count,
        chunk_count=chunk_count,
        embedding_provider=embedding_provider,
        total_seconds=total_seconds,
        budget_seconds=budget_seconds,
        passed=total_seconds <= budget_seconds,
    )
```

**코드에서 꼭 볼 것**

- `previous = clock()`은 루프 **밖**에서 한 번 실행되고, 루프 안에서는 `previous = current`로 이어진다. 질의 사이의 간격이 아니라 연속된 구간을 측정하므로 개별 측정값의 합이 실제 경과 시간과 같다.
- `queries[index % len(queries)]`로 질의를 순환한다. **200회를 채우려고 같은 질의만 반복하면 데이터베이스와 공급자의 캐시가 두 번째 호출부터 응답을 앞당겨 측정값이 실제보다 짧아진다.**
- `assess_indexing_budget`은 시계를 읽지 않고 이미 측정된 초를 받아 판정만 한다. 측정과 판정을 분리했으므로 테스트가 고정된 값으로 판정 로직만 검증할 수 있다.
- 두 함수 모두 `passed`를 계산해 레코드에 저장한다. 나중에 임계값을 바꿔도 그 실행의 판정 결과가 파일에 남는다.

> **개념 — 스위트가 28개인데 왜 200회를 재는가**
>
> 지연 시간 관문은 분포에 대한 주장이고, 분포에서 가장 늦게 안정되는 곳이 꼬리다. 표본이 28개뿐이면 이 파일의 백분위 규칙에서 p95는 그저 두 번째로 느린 측정값이다 — 가비지 컬렉션 한 번이나 콜드 캐시 한 번이 숫자를 결정한다. 표본이 200개면 p95는 열한 번째로 느린 값이 되고, 그 위에 더 느린 측정값 열 개가 놓이므로 사고 하나가 숫자를 소유하지 못한다.
>
> 그래서 예산 측정은 새 질문을 지어내는 대신 골든 질문 28개를 대략 일곱 바퀴 돈다. 목표는 더 넓은 커버리지가 아니라 현실적인 질의 구성에 대한 안정적인 추정이다. 질의를 일부러 순차로 실행하는 것도 같은 이유다 — 관문이 순차 벽시계로 정의되어 있어야 두 실행이 비교 가능하고, 동시 실행은 검색 경로만큼이나 커넥션 풀을 재게 된다.

### 4. 세 전략이 한 인터페이스를 갖는다

#### `app/evals/retrieval_eval.py` 확장 — 검색기 바인딩

**학습 행동 — 전략 바인딩 구현:** 클로저가 무엇을 포획하는지, 이 함수가 값이 아니라 함수를 반환하는 이유가 무엇인지 확인한다.

<!-- src: app/evals/retrieval_eval.py::make_retriever -->
```python
def make_retriever(
    session: AsyncSession,
    *,
    strategy: RetrievalStrategy,
    provider: EmbeddingProvider | None,
    lexical_ranker: LexicalRanker | None = None,
    candidate_k: int = 20,
    rrf_k: int = DEFAULT_RRF_K,
    filters: RetrievalFilters | None = None,
) -> Retriever:
    """Bind one explicit retrieval strategy and lexical ranker to a session.

    The ranker is required exactly when the strategy runs a lexical query, so an
    arm can never be measured under a ranker it did not use, and a vector arm can
    never be labelled with one it never touched.
    """
    if strategy not in {"lexical", "vector", "hybrid"}:
        raise ValueError(f"unsupported retrieval strategy: {strategy}")
    if strategy == "vector":
        if lexical_ranker is not None:
            raise ValueError("vector retrieval must not name a lexical ranker")
    elif lexical_ranker not in {"ts_rank_cd", "bm25"}:
        raise ValueError(f"{strategy} retrieval requires an explicit lexical ranker")
    if candidate_k <= 0:
        raise ValueError("candidate_k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    if strategy in {"vector", "hybrid"} and provider is None:
        raise ValueError(f"{strategy} retrieval requires an embedding provider")

    async def run(query: str, k: int) -> Sequence[ChunkHit]:
        if candidate_k < k:
            raise ValueError("candidate_k must be at least k")
        if strategy == "lexical":
            if lexical_ranker == "bm25":
                return await bm25_search(session, query, k, filters)
            return await lexical_search(session, query, k, filters)
        assert provider is not None
        if strategy == "vector":
            query_vector = await provider.embed_query(query)
            return await vector_search(session, query_vector, k=k, filters=filters)
        result = await retrieve(
            session,
            query,
            provider=provider,
            k=k,
            candidate_k=candidate_k,
            filters=filters,
            rrf_k=rrf_k,
            lexical_ranker=lexical_ranker,
        )
        return result.hits

    return run
```

**코드에서 꼭 볼 것**

- 반환값은 `Retriever`이고, 그 인터페이스는 `(query, k) -> hits` 하나뿐이다. `evaluate_retriever`는 어떤 전략이 실행되는지 알지 못한다.
- 전략 검사와 공급자 검사는 **클로저를 만들기 전에** 실행된다. 질의를 200회 실행하는 도중 100번째에 공급자가 없어 실패하면, 그때까지의 측정값이 모두 무의미해진다.
- `strategy in {"vector", "hybrid"} and provider is None`을 먼저 거부한다. lexical 전략은 임베딩 공급자가 필요 없으므로 이 조건에서 제외한다.
- `candidate_k < k` 검사는 클로저 **안**에 있다. `k`가 호출 시점에 결정되기 때문이다.

뻔한 대안은 클로저를 아예 두지 않는 것이다. `evaluate_retriever`에 전략 문자열을 넘겨 루프 안에서 분기하면 된다. 그러면 측정 루프가 모든 검색 경로에 용접된다 — 새 실험군이 생길 때마다 측정되는 코드 자체를 고치게 되고, 루프는 대부분의 경우 무시할 공급자·랭커 인자를 떠안는다. 더 나쁜 것은 귀속이 흐려진다는 점이다. 쓰지 않은 랭커 아래에서 실험군이 측정될 수 없다는 docstring의 약속은, 바인딩과 검증이 측정 시작 전에 여기서 한 번만 일어나기 때문에 강제할 수 있다. 클로저 방식에서는 모든 실험군이 바이트 단위로 같은 루프를 지나므로, 두 실험군의 지연 시간 차이는 검색 경로에서만 나올 수 있다.

### 5. 기준선은 저장 전에 읽는다

#### `app/evals/retrieval_eval.py` 확장 — 영속화와 비교

**학습 행동 — 호출 순서 검토:** 세 호출의 순서를 바꿨을 때 어떤 결과가 나오는지 확인한다.

<!-- src: app/evals/retrieval_eval.py::persist_evaluation -->
```python
async def persist_evaluation(
    session: AsyncSession,
    evaluation: RetrievalEvaluation,
    *,
    raw_artifact_path: str | Path,
    tolerances: RegressionTolerances | Mapping[str, float] | None = None,
) -> PersistedEvaluation:
    """Persist one run and compare it with the latest suite/config baseline."""
    baseline = await latest_comparable_baseline(
        session,
        suite=evaluation.suite,
        config=evaluation.config,
    )
    comparison = (
        compare_against_baseline(
            baseline.metrics,
            evaluation.metric_values(),
            tolerances=tolerances,
        )
        if baseline is not None
        else None
    )
    result = await persist_eval_result(
        session,
        suite=evaluation.suite,
        config=evaluation.config,
        metrics=evaluation.metric_values(),
        raw_artifact_path=raw_artifact_path,
        created_at=evaluation.recorded_at,
    )
    if result.id is None:
        raise RuntimeError("persisted evaluation did not receive an id")
    return PersistedEvaluation(
        result_id=result.id,
        baseline_id=baseline.id if baseline is not None else None,
        comparison=comparison,
    )
```

**코드에서 꼭 볼 것**

- `latest_comparable_baseline`을 `persist_eval_result`보다 **먼저** 호출한다. **순서를 바꾸면 방금 저장한 이번 실행이 기준선으로 조회되어 자기 자신과 비교하게 되고, 회귀 판정은 항상 통과로 나온다.**
- `baseline is None`이면 `comparison`도 `None`으로 둔다. 비교할 기준선이 없는 첫 실행이 회귀 없음으로 통과한 실행처럼 보이지 않는다.
- `created_at=evaluation.recorded_at`을 넘긴다. 저장 시각이 아니라 측정 시각을 기록하므로 기준선 정렬이 실제 실험 순서를 따른다.
- `result.id is None`을 확인한다. `persist_eval_result`가 flush하므로 ID가 있어야 하며, 없으면 그대로 진행하지 않고 실패시킨다.

> **개념 — 결과 저장이 opt-in인 이유**
>
> 튜토리얼 8의 CLI는 원시 아티팩트는 항상 쓰지만, 데이터베이스 행은 플래그가 요구할 때만 쓴다. 이 비대칭은 의도된 것이다. 튜토리얼 4의 비교 규칙은 suite가 같고 설정이 바이트 단위로 같은 가장 최신의 저장된 행을 기준선으로 고른다. 즉 저장된 행 하나하나가 같은 설정의 다음 저장 실행을 재는 잣대가 된다.
>
> 탐색 삼아 돌린 실행까지 전부 저장된다면, 반쯤 망가진 코퍼스로 디버깅하던 실행이 다음 진지한 실행을 판정하는 기준선으로 슬그머니 올라서고, "회귀 없음"은 "내 망가진 실험보다 나쁘지 않음"이라는 뜻이 된다. 영속화를 opt-in으로 두면 기준선 테이블은 실행된 모든 것의 로그가 아니라 의도적으로 지명된 기준선의 집합으로 유지된다. 측정은 공짜지만, 잣대가 되는 데는 명시적 결정이 필요하다.

튜토리얼 8의 CLI에서 그 결정이 `--persist-results` 플래그이고, 기본값은 꺼짐이다.

### 튜토리얼 5에서 미룬 집중 테스트

이제 `RetrievalEvaluation`, `evaluate_retriever`, `write_evaluation_artifact`가 모두 있으므로 튜토리얼 5의 어블레이션 집중 테스트를 실행한다.

왜 지금까지 미뤄야 했는지도 적어 둔다. 이 테스트 파일은 skip 장치가 보호하지 못하는 자리다. import 블록이 `evaluate_retriever`를 `retrieval_eval.py`에서 `need()` 가드 없이 직접 꺼내 오고, `ablation.py` 자신도 최상단에서 `RetrievalEvaluation`과 `write_evaluation_artifact`를 import한다. 튜토리얼 6과 이 문서 이전에는 그 이름들이 존재하지 않았으므로, 파일은 skip이 아니라 수집 단계의 ImportError로 실패했다 — "잘못 작성했다"가 아니라 "아직 작성하지 않았다"는 빨간불이다.

```bash
uv run pytest tests/evals/test_04_ablation.py -q
```

`retrieval_eval.py` 전체 실행기와 예산 테스트는 튜토리얼 8에서 함께 실행한다.

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 함수와 연결해 설명해 본다.

- **28개를 돌리고 24개만 채점하는 코드가 어느 한 줄인가?**
  - **답:** `case_score = score_case(...) if case.answers else None`이 모든 검색을 기록하되 골든 구간이 있는 사례에만 점수를 만든다.
- **벽시계 대신 단조 카운터를 쓰는 이유는 무엇인가?**
  - **답:** 단조 카운터는 NTP나 시스템 시계 보정으로 역행하지 않으므로 경과 지연 시간이 음수가 되지 않는다.
- **`sort_keys=True`가 아티팩트에서 무엇을 가능하게 하는가?**
  - **답:** 직렬화 결과를 바이트 단위로 안정시켜 두 실행의 산출물을 직접 diff하고 비교할 수 있게 한다.
- **200회 질의에서 같은 질의만 반복하면 무엇이 왜곡되는가?**
  - **답:** 캐시 효과 때문에 질의 예산의 지연 시간 측정이 실제 다양한 작업량을 대표하지 못하고, 보통 검색이 더 빠른 것처럼 보인다.
- **기준선 조회를 저장보다 뒤로 옮기면 회귀 판정이 어떻게 되는가?**
  - **답:** 방금 저장한 실행이 자기 자신의 최신 기준선이 되어 모든 차이가 0으로 나오고 실제 회귀가 사라진다.
- **채점하지도 않을 absent 사례 4개를 왜 실행하는가?**
  - **답:** 그 지연 시간은 예산이 기술하는 작업량의 일부이고, 기록된 히트는 M4의 부재 판정이 딛고 설 증거다. 점수만 그 사례들을 제외한다.
- **모든 실행이 기본으로 자신을 영속화하면 무엇이 잘못되는가?**
  - **답:** 최신 비교 규칙 아래에서 저장된 행은 전부 다음 실행의 기준선이 되므로, 버리는 실험이 잣대가 된다. `--persist-results`가 그것을 의도적 결정으로 남긴다.

---

[← 이전: 평가 레코드](06-evaluation-records.md) · [모듈 개요](../03-build.md) · [다음: 격리 실행과 CLI →](08-evaluation-cli.md)
