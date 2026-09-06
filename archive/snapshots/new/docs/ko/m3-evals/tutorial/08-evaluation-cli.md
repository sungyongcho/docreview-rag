# M3.4 튜토리얼 8 — 격리된 코퍼스에서 실행하기

마지막 단계에서는 실험이 **실제 코퍼스를 변경하지 않고** 실행되도록 만든다.

**선행 조건:** 튜토리얼 7까지 `retrieval_eval.py`의 실행 경로를 작성한 상태여야 한다.

### 실험이 실제 코퍼스를 건드리면 안 된다

튜토리얼 7은 측정 도구를 완성했다. `evaluate_retriever`가 준비된 코퍼스를 돌며 실행 하나를 아티팩트 하나로 만든다. 열려 있는 질문은 그 코퍼스가 어디서 오느냐다. 실험 행렬의 절반은 청크 크기를 바꾸는 실험이라 코퍼스 전체를 다시 청킹하고 다시 인덱싱해야 하는데, 이 프로젝트의 PostgreSQL은 운영 테이블이 들어 있는 그 하나뿐이다.

이 재인덱싱을 운영 테이블에서 실행하면 **측정에 쓰던 벡터가 파괴된다.** 시딩이 1,200자 청크를 한 실험의 500자 버전으로 교체하고, 임베딩 백필이 M2에서 만든 벡터를 덮어쓰고, BM25 통계는 다음 실험군에서 사라질 코퍼스 기준으로 다시 세워진다. 어느 단계도 오류를 내지 않는다. 하나하나가 운영 코퍼스를 정상적으로 관리하는 바로 그 코드이기 때문이다. 그래서 이후 근거로 사용할 데이터가 소리 없이 실험 중간 상태로 남고, 어느 실험군이 그렇게 만들었는지는 어떤 아티팩트에도 남지 않는다.

그러므로 이 문서의 불변조건은 절대적이다. **실험은 완주하든 어느 단계에서 죽든, 영구 테이블을 한 바이트도 바꾸지 않아야 한다.** 그래서 `temporary_corpus_session()`이 **전용 연결에 임시 테이블**을 만든다. 파싱, 청킹, 인덱싱, 평가가 모두 그 안에서 실행되고 연결이 닫히면 함께 사라진다. 별도의 스크래치 데이터베이스로도 격리는 되지만, 자체 URL과 자체 pgvector 설치가 필요하고 그 스키마가 운영이 실제로 돌리는 스키마와 일치한다는 보장을 아무것도 해 주지 않는다. 임시 테이블은 운영 데이터베이스의 환경을 그대로 재사용한다. M1.4와 M2.8에서 사용한 것과 같은 방식이다.

```
ordered experiment configs → isolated corpus per arm → parsing/chunking/indexing measurement
    → 28 retrieval records → metrics over 24 positives → timestamped artifacts → budget table
```

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `build_chunking_batch` | **구조 작성** | 청크 크기만 바꿔 코퍼스를 다시 만드는 법 |
| 임시 테이블 DDL | **설계 결정 확인** | 왜 ORM이 아니라 손으로 쓴 DDL인가 |
| `temporary_corpus_session` | 수명 관리를 **직접 구현** | 연결 하나에 묶인 격리 |
| CLI 인자 | **구조 작성** | 실험 축이 명령줄로 열리는 지점 |
| `_run_cli` | **호출 순서 검토** | 실험군마다 코퍼스를 새로 만드는 흐름 |

### 1. 청크 크기만 바꿔 코퍼스를 다시 만든다

#### `app/evals/retrieval_eval.py` 확장 — 청킹 배치 생성

**학습 행동 — 구조 작성:** `chunker=` 인자가 M1.4의 어느 확장 지점을 사용하는지 확인한다.

<!-- src: app/evals/retrieval_eval.py::build_chunking_batch -->
```python
def build_chunking_batch(
    target_text_chars: int,
    *,
    settings: Settings | None = None,
) -> SeedBatch:
    """Build one source-stable corpus arm without changing the canonical golden spans."""
    configured = settings or get_settings()
    entries = load_manifest(configured.corpus_dir / "manifest.json")
    chunk_config = ChunkConfig(target_text_chars=target_text_chars)
    return build_seed_batch(
        entries,
        expected_documents=20,
        chunker=lambda filing: chunk_filing(filing, chunk_config),
    )
```

**코드에서 꼭 볼 것**

- `chunker=`를 `build_seed_batch`에 넘긴다. M1.4가 이 확장 지점을 열어 두었기 때문에 청크 크기만 바꿔 코퍼스 전체를 다시 만들 수 있다. 매니페스트 로딩, 무결성 검사, 문서 구성은 중복 없이 그대로 재사용한다.
- 매니페스트와 원문 파일은 바뀌지 않는다. **바뀌는 것은 청킹 결과뿐이므로 정답 좌표가 그대로 유효하다.** 정답 span은 청크가 아니라 불변인 원문에 대한 오프셋 쌍이라서, 어떤 재청킹도 그 좌표를 움직이지 못한다.
- `expected_documents=20`을 여기서도 강제한다. 문서 하나를 조용히 잃은 실험군은 더 작은 코퍼스로 채점되는데, 비교 표는 그 숫자를 여전히 비교 가능한 것처럼 보여 준다.

### 2. 왜 ORM이 아니라 손으로 쓴 DDL인가

#### `app/evals/retrieval_eval.py` 확장 — 임시 테이블 생성

**학습 행동 — 설계 결정 확인:** `CREATE TEMP TABLE`을 `Base.metadata.create_all`로 대체할 수 없는 이유를 확인한다.

<!-- src: app/evals/retrieval_eval.py::_create_temporary_corpus_tables -->
```python
async def _create_temporary_corpus_tables(connection: AsyncConnection, dimensions: int) -> None:
    extension = await connection.scalar(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    )
    if extension is None:
        raise RuntimeError("the configured PostgreSQL database does not have pgvector")
    await connection.execute(
        text(
            """
            CREATE TEMP TABLE documents (
                doc_id varchar(32) PRIMARY KEY,
                ticker varchar(16) NOT NULL,
                cik bigint NOT NULL,
                fiscal_year integer NOT NULL,
                form varchar(16) NOT NULL,
                filing_date varchar(10) NOT NULL,
                report_period varchar(10) NOT NULL,
                accession varchar(32) NOT NULL,
                url text NOT NULL,
                parse_status varchar(32) NOT NULL,
                item_index jsonb NOT NULL,
                source_length bigint NOT NULL,
                source_sha256 varchar(64) NOT NULL
            ) ON COMMIT PRESERVE ROWS
            """
        )
    )
    await connection.execute(
        text(
            f"""
            CREATE TEMP TABLE chunks (
                id bigserial PRIMARY KEY,
                doc_id varchar(32) NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
                item varchar(8),
                kind varchar(16) NOT NULL,
                ordinal integer NOT NULL,
                body text NOT NULL,
                context_header text NOT NULL,
                index_text text NOT NULL,
                start_char bigint NOT NULL,
                end_char bigint NOT NULL,
                source_sha256 varchar(64) NOT NULL,
                citation text NOT NULL,
                embedding vector({dimensions}),
                content_tsv tsvector GENERATED ALWAYS AS (
                    to_tsvector('english', index_text)
                ) STORED,
                created_at timestamptz NOT NULL DEFAULT now(),
                UNIQUE (doc_id, ordinal)
            ) ON COMMIT PRESERVE ROWS
            """
        )
    )
    await connection.execute(text("CREATE INDEX ON chunks USING gin (content_tsv)"))
    for statement in (
        """
        CREATE TEMP TABLE chunk_terms (
            chunk_id bigint NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
            lexeme text NOT NULL,
            tf integer NOT NULL,
            PRIMARY KEY (chunk_id, lexeme)
        ) ON COMMIT PRESERVE ROWS
        """,
        """
        CREATE TEMP TABLE chunk_lengths (
            chunk_id bigint PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
            dl integer NOT NULL
        ) ON COMMIT PRESERVE ROWS
        """,
        """
        CREATE TEMP TABLE lexeme_stats (
            lexeme text PRIMARY KEY,
            df integer NOT NULL
        ) ON COMMIT PRESERVE ROWS
        """,
        "CREATE INDEX ON chunk_terms (lexeme)",
    ):
        await connection.execute(text(statement))
    await connection.commit()
```

**코드에서 꼭 볼 것**

- `CREATE TEMP TABLE`을 직접 작성한다. SQLAlchemy의 `create_all`은 영구 테이블만 만들고 — 임시 테이블은 ORM 메타데이터로 표현되지 않는다 — 이미 존재하는 테이블은 건너뛴다. 이 데이터베이스에 대고 실행하면 운영의 `documents`와 `chunks`가 이미 있으니 아무것도 만들지 않고, 실험이 라이브 코퍼스에서 돌게 된다. 이 모듈이 막으려고 존재하는 바로 그 사고다.
- 테이블 이름을 `documents`, `chunks`로 운영과 동일하게 둔다. **PostgreSQL은 임시 스키마를 검색 경로 앞에 두므로, `persist_seed_batch`와 검색 코드가 코드 수정 없이 임시 테이블을 사용한다.** 격리가 성립하는 지점이 여기다.
- pgvector 확장을 먼저 확인하고 없으면 거부한다. `pg_extension`을 먼저 조회하면, `vector({dimensions})` 열을 만들다 중간에 터지는 알기 어려운 실패가 이름 붙은 선행 조건 검사로 바뀐다.
- `ON COMMIT PRESERVE ROWS`는 PostgreSQL 임시 테이블의 기본값과 같지만 일부러 명시한다. **이 절의 다른 두 값 `ON COMMIT DELETE ROWS`와 `ON COMMIT DROP`은 커밋 시점에 행이나 테이블을 지우므로, 커밋 뒤에도 코퍼스가 남는다는 전제를 DDL에 그대로 남긴다.** 시딩과 첫 검색 사이에 세션은 여러 번 커밋하는데, 이 DDL을 감사하는 독자가 코퍼스가 그 커밋들을 넘겨 살아남는다는 사실을 알기 위해 PostgreSQL 기본값 표를 외우고 있어야 해서는 안 된다.
- `content_tsv` 생성 열과 GIN 인덱스는 운영 스키마를 그대로 반영하며, 둘을 빠뜨렸을 때의 실패 양상은 전혀 다르다. 열을 빼면 평가가 시작되기도 전에 요란하게 죽는다. `backfill_term_stats`가 `chunks`에서 이 열을 읽는데, 가려진 이름은 운영 테이블로 대체되지 않기 때문이다. 인덱스만 빼면 아무것도 실패하지 않는다. M2.4의 어휘 질의는 순차 스캔으로 동일한 행을 반환하고, 지연 시간 예산은 운영에 없는 인덱스 형태를 조용히 측정하게 된다.

> **개념 — 임시 테이블 섀도잉**
>
> PostgreSQL은 스키마를 붙이지 않은 테이블 이름을 검색 경로(search_path)로 해석하는데, 연결의 임시 스키마는 그 경로의 어떤 항목보다 먼저 검색된다. 이 연결이 chunks라는 임시 테이블을 만든 순간부터, 같은 연결에서 실행되는 모든 이후 문장에서 — ORM insert든, 날 SQL 문자열이든, BM25 재빌드 안의 LOCK TABLE이든 — 그 이름은 임시 테이블을 가리킨다. 다른 연결에서는 여전히 운영 테이블로 해석된다.
>
> 시딩·검색 코드를 한 줄도 바꾸지 않고 격리가 성립하는 이유가 이것이다. 그 모듈들은 테이블 이름에 스키마를 붙이지 않으므로, 격리 코퍼스로의 우회는 코드 경로가 아니라 이름 해석의 귀결이다. 대가는 규율이다. 임시 테이블에 없는 열은 운영 테이블로 대체되는 것이 아니라 그냥 존재하지 않는 것이므로, DDL은 운영 스키마의 형태를 정확히 재현해야 한다.

### 3. 연결 하나에 묶인 격리

#### `app/evals/retrieval_eval.py` 확장 — 임시 코퍼스 세션

**학습 행동 — 수명 관리 구현:** `try/finally`가 무엇을 보장하는지, `yield`가 어느 위치에 있는지 확인한다.

<!-- src: app/evals/retrieval_eval.py::temporary_corpus_session -->
```python
@asynccontextmanager
async def temporary_corpus_session(
    engine: AsyncEngine,
    batch: SeedBatch,
    provider: EmbeddingProvider,
    *,
    target_text_chars: int,
    embedding_provider: str,
    clock: Clock = time.perf_counter_ns,
    started_at_ns: int | None = None,
) -> AsyncIterator[tuple[AsyncSession, IndexingBudgetMeasurement]]:
    """Index one isolated corpus arm and discard it when its connection closes."""
    started = clock() if started_at_ns is None else started_at_ns
    connection = await engine.connect()
    session: AsyncSession | None = None
    try:
        await _create_temporary_corpus_tables(connection, provider.dimensions)
        session = AsyncSession(bind=connection, expire_on_commit=False)
        await persist_seed_batch(session, batch)
        # One rebuild per corpus arm. Every BM25 experiment on this chunking shares
        # it, and the next chunk target gets its own corpus and its own statistics,
        # because df, avgdl, and dl are all properties of a particular chunking.
        await backfill_term_stats(session)
        backfill = await embed_missing_chunks(session, provider)
        if backfill.embedded != len(batch.chunks) or backfill.skipped_stale:
            raise RuntimeError("temporary corpus embedding backfill was incomplete")
        elapsed_seconds = (clock() - started) / 1_000_000_000
        measurement = assess_indexing_budget(
            target_text_chars=target_text_chars,
            document_count=len(batch.documents),
            chunk_count=len(batch.chunks),
            embedding_provider=embedding_provider,
            total_seconds=elapsed_seconds,
        )
        yield session, measurement
    finally:
        if session is not None:
            await session.close()
        await connection.close()
```

**코드에서 꼭 볼 것**

- `engine.connect()`로 **연결 하나**를 확보하고 세션을 그 연결에 바인딩한다. 임시 테이블은 연결에 속하므로, 세션이 풀에서 다른 연결을 사용하면 테이블을 찾지 못한다.
- 인덱싱 시간 측정 구간이 `_create_temporary_corpus_tables`부터 백필 완료까지다. 테이블 생성, 시드, BM25 통계 재빌드, 임베딩 백필이 모두 인덱싱 시간에 포함된다. 이 예산이 묻는 것은 이 청킹의 새 코퍼스가 질의 가능해지기까지 얼마나 걸리는가이므로, 시계 밖에 남겨 둔 준비 단계는 아무리 느려져도 예산을 실패시키지 못한다.
- `backfill.embedded != len(batch.chunks)`를 확인한다. 일부만 임베딩된 코퍼스로 평가를 실행하면 재현율이 낮게 나오는데, 그 원인이 검색 품질이 아니라 준비 실패라는 사실이 결과에 드러나지 않는다.
- `finally`에서 세션과 연결을 순서대로 닫는다. 연결이 닫히면 임시 테이블도 함께 사라지므로 별도의 정리 코드가 필요 없다.

> **개념 — 연결 수명에 묶인 격리**
>
> PostgreSQL 임시 테이블은 세션 하나에 속하고, 이 드라이버에서 세션은 데이터베이스 연결 하나다. 임시 테이블은 다른 어떤 연결에서도 보이지 않고, 자기 연결이 닫히는 순간 자동으로 삭제된다. 이보다 짧은 수명은 쓸 수 없고 — 트랜잭션은 실험이 끝나기 한참 전에 끝난다 — 이보다 긴 수명은 존재하지 않아서 새어 나갈 곳도 없다.
>
> 이 수명 규칙이 함수의 형태를 결정한다. 연결을 정확히 하나 확보하고 세션을 거기에 바인딩하는 이유는, 엔진에 바인딩된 보통의 세션은 트랜잭션마다 풀에서 다른 연결을 빌릴 수 있어서 테이블을 만든 연결과 찾는 연결이 달라질 수 있기 때문이다. 같은 수명 규칙 덕에 정리는 공짜이고 크래시에도 안전하다. finally 블록에 명시적 DROP이 없는 것은 연결을 닫는 것 자체가 삭제이기 때문이며, 프로세스가 실험군 중간에 죽어도 마찬가지다.

커밋된 예산 아티팩트가 이 측정의 실제 비용을 기록하고 있다. 500자 실험군은 문서 20건을 청크 12,984개로 인덱싱하는 데 약 38.5초, 1,200자 실험군은 청크 9,172개를 만드는 데 약 33.9초가 걸렸고, 둘 다 300초 인덱싱 예산을 여유 있게 통과한다(CLI는 이 시계를 `build_chunking_batch` 이전에 시작하므로, 커밋된 초에는 파싱과 청킹도 포함된다). 저장소에서 그대로 재현할 수 있다.

```bash
python3 -c "import json; d = json.load(open('data/eval_runs/20260824T203336Z-budgets.json')); [print(i['target_text_chars'], i['chunk_count'], round(i['total_seconds'], 1), i['passed']) for i in d['indexing']]"
```

### 4. 실험 축을 명령줄로 연다

#### `app/evals/retrieval_eval.py` 확장 — CLI 인자

**학습 행동 — 구조 작성:** 인자 기본값이 M3의 전체 행렬 — 2×3 기본 행렬에 어휘 랭커 축을 교차한 것 — 을 재현하는지 확인한다.

<!-- src: app/evals/retrieval_eval.py::_positive_int,arguments -->
```python
def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the isolated M3 ablation command."""
    parser = argparse.ArgumentParser(
        description="Run isolated source-span retrieval ablations and latency budgets."
    )
    parser.add_argument("--suite", default="m3-retrieval-v1")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_PATH)
    parser.add_argument("--artifact-dir", type=Path, default=Path("data/eval_runs"))
    parser.add_argument("--provider", choices=("deterministic", "openai"), default="deterministic")
    parser.add_argument("--target-text-chars", type=_positive_int, nargs="+", default=[500, 1200])
    parser.add_argument(
        "--strategies",
        choices=("lexical", "vector", "hybrid"),
        nargs="+",
        default=["lexical", "vector", "hybrid"],
    )
    parser.add_argument(
        "--lexical-rankers",
        choices=("ts_rank_cd", "bm25"),
        nargs="+",
        default=["ts_rank_cd", "bm25"],
        help="Lexical rankers to cross with every lexical and hybrid arm.",
    )
    parser.add_argument("-k", type=_positive_int, default=5)
    parser.add_argument("--candidate-k", type=_positive_int, default=20)
    parser.add_argument("--rrf-k", type=_positive_int, default=DEFAULT_RRF_K)
    parser.add_argument("--budget-queries", type=_positive_int, default=QUERY_BUDGET_COUNT)
    parser.add_argument("--persist-results", action="store_true")
    return parser.parse_args(argv)
```

**코드에서 꼭 볼 것**

- `--target-text-chars`와 `--strategies`에 `nargs="+"`를 지정한다. 실험 축을 명령줄에서 늘리거나 줄일 수 있고, `--suite`나 `--artifact-dir`로 일회성 실행을 커밋된 증거와 다른 곳으로 돌릴 수 있다.
- 기본값은 `[500, 1200]`, 세 전략, 그리고 두 어휘 랭커다. 인자 없이 실행하면 실험군 열 개가 실행된다. 청크 크기마다 랭커 축이 lexical과 hybrid 행을 두 개씩으로 가르고, vector 실험군은 랭커를 받지 않는다.
- `--provider`는 `deterministic`과 `openai`만 제공한다. 설정 계층에는 `sbert` 공급자 이름도 있지만, 핀 고정된 현재 코드에서는 이 명령줄로 선택할 수 없다. 실험 설계의 성질이 아니라 현재 플래그의 한계다.
- `_positive_int`를 `argparse` 타입으로 사용한다. 잘못된 값이 몇 분짜리 코퍼스 빌드가 시작된 뒤가 아니라 인자 파싱 단계에서 거부된다.
- `--persist-results`의 기본값은 꺼짐이다. 데이터베이스 쓰기는 명시적으로 요청해야 한다. 스스로를 기본으로 저장하는 측정 실행은 다음 실행의 최신 비교 기준선이 되어 버리기 때문이고, 이것이 튜토리얼 7에서 세운 옵트인 규칙이다.

### 5. 실험군마다 코퍼스를 새로 만든다

#### `app/evals/retrieval_eval.py` 완성 — CLI 실행

**학습 행동 — 호출 순서 검토:** 청크 크기마다 코퍼스가 몇 번 만들어지는지 세어 본다.

<!-- src: app/evals/retrieval_eval.py::_run_cli,main -->
```python
async def _run_cli(args: argparse.Namespace) -> dict[str, Any]:
    from app.db.bootstrap import bootstrap_schema
    from app.evals.ablation import ExperimentConfig, experiment_matrix, run_ablation

    if args.candidate_k < args.k:
        raise ValueError("candidate_k must be at least k")
    settings = get_settings().model_copy(update={"embedding_provider": args.provider})
    provider = get_embedding_provider(settings)
    cases = load_golden_cases(args.golden)
    recorded_at = datetime.now(UTC)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    all_outcomes = []
    indexing_measurements: list[IndexingBudgetMeasurement] = []
    query_budget: QueryBudgetMeasurement | None = None
    budget_ranker: LexicalRanker | None = None
    try:
        for target_text_chars in sorted(set(args.target_text_chars)):
            indexing_started_at_ns = time.perf_counter_ns()
            batch = build_chunking_batch(target_text_chars, settings=settings)
            configs = experiment_matrix(
                target_text_chars=(target_text_chars,),
                strategies=tuple(args.strategies),
                lexical_rankers=tuple(dict.fromkeys(args.lexical_rankers)),
                embedding_provider=args.provider,
                dimensions=provider.dimensions,
                k=args.k,
                candidate_k=args.candidate_k,
                rrf_k=args.rrf_k,
            )
            async with temporary_corpus_session(
                engine,
                batch,
                provider,
                target_text_chars=target_text_chars,
                embedding_provider=args.provider,
                started_at_ns=indexing_started_at_ns,
            ) as (session, indexing):
                indexing_measurements.append(indexing)

                async def evaluator(config: ExperimentConfig) -> RetrievalEvaluation:
                    retriever = make_retriever(
                        session,
                        strategy=config.strategy,
                        provider=provider,
                        lexical_ranker=config.lexical_ranker,
                        candidate_k=config.candidate_k,
                        rrf_k=config.rrf_k,
                    )
                    return await evaluate_retriever(
                        cases,
                        retriever,
                        suite=args.suite,
                        config=config.to_dict(),
                        k=config.k,
                        recorded_at=recorded_at,
                    )

                report = await run_ablation(
                    configs,
                    evaluator,
                    artifact_dir=args.artifact_dir,
                    recorded_at=recorded_at,
                )
                all_outcomes.extend(report.outcomes)

                if target_text_chars == max(args.target_text_chars):
                    budget_strategy = (
                        "hybrid" if "hybrid" in args.strategies else args.strategies[-1]
                    )
                    budget_ranker = None if budget_strategy == "vector" else args.lexical_rankers[0]
                    budget_retriever = make_retriever(
                        session,
                        strategy=budget_strategy,
                        provider=provider,
                        lexical_ranker=budget_ranker,
                        candidate_k=args.candidate_k,
                        rrf_k=args.rrf_k,
                    )
                    query_budget = await measure_query_budget(
                        [case.question for case in cases],
                        budget_retriever,
                        k=args.k,
                        query_count=args.budget_queries,
                    )

        if query_budget is None:
            raise RuntimeError("query budget was not measured")

        timestamp = recorded_at.strftime("%Y%m%dT%H%M%SZ")
        budget_path = args.artifact_dir / f"{timestamp}-budgets.json"
        budget_payload = {
            "schema_version": RAW_ARTIFACT_SCHEMA_VERSION,
            "recorded_at": _utc_text(recorded_at),
            "measurement_provenance": {
                "embedding_provider": args.provider,
                "budget_lexical_ranker": budget_ranker,
                "environment": "isolated-temporary-postgresql",
                "paid_api_calls": args.provider != "deterministic",
                "populated_corpus_embeddings_modified": False,
            },
            "indexing": [asdict(measurement) for measurement in indexing_measurements],
            "query_budget": asdict(query_budget),
        }
        budget_path.parent.mkdir(parents=True, exist_ok=True)
        budget_path.write_text(
            json.dumps(budget_payload, allow_nan=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        persisted = []
        if args.persist_results:
            await bootstrap_schema(engine)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                for outcome in all_outcomes:
                    persisted.append(
                        await persist_evaluation(
                            session,
                            outcome.evaluation,
                            raw_artifact_path=outcome.artifact_path,
                        )
                    )
                await session.commit()

        from app.evals.ablation import AblationReport

        combined = AblationReport(outcomes=tuple(all_outcomes))
        return {
            "comparison_table": combined.comparison_markdown(),
            "artifacts": [str(outcome.artifact_path) for outcome in all_outcomes],
            "budget_artifact": str(budget_path),
            "indexing": [asdict(measurement) for measurement in indexing_measurements],
            "query_budget": asdict(query_budget),
            "persisted": [asdict(result) for result in persisted],
        }
    finally:
        await engine.dispose()


def main() -> None:
    """Run the complete isolated M3 evaluation command."""
    result = asyncio.run(_run_cli(arguments()))
    print(result["comparison_table"])
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "comparison_table"}, indent=2
        )
    )
```

**코드에서 꼭 볼 것**

- 청크 크기마다 코퍼스를 **한 번** 만들고 그 안에서 전략·랭커 실험군 전부를 실행한다. **실험군마다 다시 인덱싱하면 같은 코퍼스를 다섯 번 다시 만들게 되고, 인덱싱 측정이 같은 준비 작업을 반복 계상하며, 실험군 사이의 차이를 단지 다른 시점에 만들어진 코퍼스 탓으로 돌릴 수 있게 된다.**
- 엔진을 `NullPool`로 만든다. 연결을 반환하면 풀로 돌아가는 대신 실제로 닫힌다. 이유는 3절의 수명 규칙이다. **풀에 남은 연결은 자기 임시 테이블을 그대로 들고 있으므로, 다음 실험군이 그 연결을 꺼내면 이전 실험군의 코퍼스를 물려받아 운영 테이블을 가리게 된다.**
- 질의 예산은 가장 큰 청크 크기에서 한 번만 측정한다. 기본값에서는 1,200자 코퍼스, 즉 운영이 서비스하는 것과 같은 청킹이다. 전략은 `hybrid`를 우선하고 랭커는 목록의 첫 항목인데, 기본값에서는 `ts_rank_cd`다. 실험군마다 측정하면 실행 비용만 배가 되고 예산이 주장하는 내용은 달라지지 않는다. 커밋된 예산 아티팩트가 정확히 그 실험군을 기록하고 있다. 순차 질의 200개가 90초 예산에 대해 약 29.8초 걸렸다.
- `bootstrap_schema`는 `--persist-results`를 지정한 경우에만 호출한다. 결과를 저장하지 않는 실행은 영구 스키마를 변경하지 않는다.
- `finally: await engine.dispose()`로 엔진을 정리한다. 실험이 중간에 실패해도 연결이 남지 않는다.

기본 실행이 남기는 결과물을 정확히 짚어 둘 가치가 있다. `data/eval_runs/`에 정확히 파일 열한 개가 남는다. 실험군별 아티팩트 열 개 — 랭커 축이 lexical과 hybrid 행을 두 배로 가르고 vector 아티팩트에는 랭커 접미사가 없어서 청크 크기당 다섯 개 — 에 실행 타임스탬프를 공유하는 예산 아티팩트 하나를 더한 것이다. 이 저장소에 커밋된 실행이 정확히 그 형태를 보여 준다.

```bash
ls data/eval_runs/ | grep -c 20260824T203336Z
```

이 명령은 `11`을 출력한다.

예산 아티팩트는 `_run_cli`의 끝, 모든 실험군이 끝난 뒤에 태어난다. 청크 크기마다 하나씩의 인덱싱 측정과 단 한 번의 질의 예산 측정을 담고, 어느 임베딩 공급자가 실행됐는지, 유료 API 호출이 있었는지, 운영 코퍼스를 변경하지 않았는지를 기록하는 출처 블록으로 감싼다. 이 파일은 이후 아무도 수정하지 않으며 — 다음 실행은 그 옆에 새 타임스탬프로 새 파일을 쓴다 — 커밋된 사본이 이 모듈의 결론이 인용하는 지연 시간 증거가 된다. 그 범위는 튜토리얼 7에서 세운 그대로다. 이 기계의 벽시계 증거이지, 호스팅 환경의 지연 시간 보장이 아니다.

파일 마지막에 모듈 실행 가드를 덧붙인다. 이 두 줄이 있어야 `python -m app.evals.retrieval_eval`이 직접 동작한다.

```python
if __name__ == "__main__":
    main()
```

#### `app/evals/__main__.py` 생성 — 모듈 실행 진입점

**학습 행동 — 구조 작성:** 네 줄짜리 파일이다. 이 파일이 있어야 `python -m app.evals`로 실행할 수 있다.

```python
"""Command-line entry point for the complete M3 evaluation matrix."""

from app.evals.retrieval_eval import main

if __name__ == "__main__":
    main()
```

### 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/evals/test_04_ablation.py tests/evals/test_05_runner.py -q
```

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 단조가 아닌 시계 | 음수 지연이 백분위를 오염시키지 않는다. |
| 일부만 임베딩된 임시 코퍼스 | 준비 실패가 검색 실패로 보고되지 않는다. |
| 저장 전에 잡힌 기준선 | 실행이 자기 자신과 비교되지 않는다. |
| absent 사례가 섞인 채점 | 부재 판정이 재현율에 들어가지 않는다. |
| 키 순서가 다른 아티팩트 | 두 실행의 아티팩트를 `diff`로 비교할 수 있다. |

통합 경로는 실제 PostgreSQL이 필요하다.

```bash
docker compose up -d db
uv run pytest tests/evals/test_06_postgres.py -q
```

**건너뛴 테스트는 통과가 아니라 환경 검증이 끝나지 않았다는 뜻이다.**

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 코드와 연결해 설명해 본다.

- **실험이 운영 테이블에서 돌면 정확히 무엇이 파괴되는가?**
  - **답:** 재청킹이 서비스용 코퍼스와 임베딩을 한 실험의 중간 청크 크기 버전으로 덮어쓴다. 운영에서 OpenAI 같은 유료 API 임베딩 공급자를 썼다면 비용을 들인 작업도 사라지지만, 기본 결정론적 공급자에는 API 비용이 없다.
- **임시 테이블 이름이 운영과 같아야 하는 이유는 무엇인가?**
  - **답:** PostgreSQL은 임시 스키마를 검색 경로 앞에 두므로, 같은 이름이 운영 테이블을 가리고 기존 시딩·검색 코드를 바꾸지 않은 채 격리 코퍼스에서 실행하게 한다.
- **`ON COMMIT PRESERVE ROWS`가 없으면 언제 코퍼스가 사라지는가?**
  - **답:** 이 절을 생략해도 PostgreSQL은 기본적으로 임시 테이블 행을 커밋 뒤에 보존하므로 사라지지 않는다. `ON COMMIT DELETE ROWS`는 커밋할 때 행을 비우고, `ON COMMIT DROP`은 테이블을 제거한다.
- **`NullPool`을 쓰지 않으면 어떤 증상이 나타나는가?**
  - **답:** 풀의 연결을 다음 실험군이 재사용하면 이전 실험군의 임시 테이블이나 행이 남아 이름 충돌이나 낡은 코퍼스 유출이 생길 수 있다. 세션은 이미 확보한 연결 하나에 바인딩되므로 두 번째 연결로 바뀌는 문제는 아니다.
- **청크 크기당 코퍼스를 한 번만 만드는 이유는 무엇인가?**
  - **답:** 벡터·어휘·하이브리드 전략이 같은 준비 코퍼스를 사용해야 한다. 전략마다 다시 만들면 같은 일을 세 번 하고 인덱싱 측정값의 의미도 깨진다.

---

[← 이전: 평가 실행](07-evaluation-run.md) · [모듈 개요](../03-build.md) · [다음: 골든 큐레이션 →](09-golden-curation.md)
