# M8.2 튜토리얼 2 — 실패를 소유하기 전에 측정한다

이 모듈 끝에는 수정이 기다리고 있고, 지금 그것을 집어 드는 것이 실수다. **이전 표가 없는 개선은 일화이고, 숫자가 없는 다국어 주장은 소문이다.** 이 문서는 자기 출처를 M3 하니스로 실어 나르는 실험군과, 아직 아무것도 바뀌지 않은 시점에 돌릴 수 있을 만큼 싼 진단 두 개를 만든다. 진단은 "이 시스템이 한국어를 인식하기는 하는가"에 답한다.

**선행 조건:** M8.1 완료, `uv run pytest tests/crosslingual/test_01_bilingual.py -q` 통과.

### 무엇을 정의하고, 무엇을 구현하고, 무엇을 들여다볼 것인가

| 영역 | 학습 행동 | 가져갈 것 |
|---|---|---|
| `CrosslingualArm` | 실험군과 그 config를 **구현한다** | config 딕셔너리가 모든 회귀 숫자를 짊어진다 |
| `twin_query_alignment` | 코퍼스 없는 진단을 **구현한다** | 0에 가까움은 주장이고, 정확한 0은 거짓말이다 |
| `lexical_candidate_coverage` | 붕괴 계수기를 **구현한다** | 비율은 측정되지 결코 가정되지 않는다 |
| 렌더 헬퍼 | 조인을 **작성한다** | 언어는 두 번째 실행이지 새 차원이 아니다 |

### 1. 실험군은 자기가 무엇인지 말해야 한다

M3 하니스는 정규 config 딕셔너리로 실행을 비교한다. `latest_comparable_baseline`이 직렬화된 config로 대조하므로 config가 같은 두 실행은 같은 것을 잰 측정으로 취급된다. 이것은 선물이자 함정이다. `query.language`를 빠뜨리면 한국어 실행이 조용히 영어 기준선을 물려받고, `embedding.model`을 빠뜨리면 다국어 실험군이 토큰 해시 실험군과 비교된다. **config 계약이 이 모듈의 모든 회귀 숫자의 무게를 온전히 짊어진다.**

#### `app/evals/crosslingual.py` 생성 — 실험군

**학습 행동 — 실험군을 구현한다:** 검증을 먼저 쓰고, 규칙마다 그것이 어떤 숫자를 지키는지 말한다.

<!-- src: app/evals/crosslingual.py::CrosslingualArm -->
```python
@dataclass(frozen=True, slots=True)
class CrosslingualArm:
    """One measured cross-lingual retrieval arm and its canonical provenance."""

    embedding_provider: ProviderChoice
    embedding_model: str
    strategy: RetrievalStrategy
    language: QueryLanguage
    handling: QueryHandling = "direct"
    lexical_ranker: LexicalRanker | None = None
    translator_model: str | None = None
    dimensions: int = 384
    target_text_chars: int = CROSSLINGUAL_TARGET_TEXT_CHARS
    k: int = 5
    candidate_k: int = 20
    rrf_k: int = DEFAULT_RRF_K

    def __post_init__(self) -> None:
        """Reject arm shapes whose measured numbers could not be attributed."""
        if self.embedding_provider not in PROVIDER_CHOICES:
            raise ValueError(f"unsupported embedding provider: {self.embedding_provider}")
        if not self.embedding_model.strip():
            raise ValueError("embedding_model must be nonblank")
        if self.strategy not in STRATEGY_ORDER:
            raise ValueError(f"unsupported retrieval strategy: {self.strategy}")
        if self.language not in LANGUAGE_ORDER:
            raise ValueError(f"unsupported query language: {self.language}")
        if self.handling not in HANDLING_ORDER:
            raise ValueError(f"unsupported query handling: {self.handling}")
        if self.strategy == "vector":
            if self.lexical_ranker is not None:
                raise ValueError("vector retrieval must not name a lexical ranker")
        elif self.lexical_ranker not in RANKER_SLUG:
            raise ValueError(f"{self.strategy} retrieval requires an explicit lexical ranker")
        # Routing decides whether to ask the lexical component at all, so it only
        # means something where both components run. A "routed" vector arm would be
        # the direct vector arm under a label claiming a route it never took.
        if self.handling != "direct" and self.strategy != "hybrid":
            raise ValueError(f"{self.handling} handling requires the hybrid strategy")
        if (self.handling == "translated") != (self.translator_model is not None):
            raise ValueError("a translator model is required exactly for translated handling")
        if self.dimensions <= 0 or self.target_text_chars <= 0:
            raise ValueError("dimensions and target_text_chars must be positive")
        if self.k <= 0 or self.candidate_k < self.k or self.rrf_k <= 0:
            raise ValueError("k, candidate_k, and rrf_k are inconsistent")
        if ARM_NAME.fullmatch(self.name) is None:
            raise ValueError("arm name must be lowercase kebab-case")

    @property
    def name(self) -> str:
        """Return the kebab arm name, which must survive being used as a filename."""
        parts = ["xling", self.embedding_provider, self.strategy]
        if self.lexical_ranker is not None:
            parts.append(RANKER_SLUG[self.lexical_ranker])
        if self.handling != "direct":
            parts.append(self.handling)
        parts.append(self.language)
        return "-".join(parts)

    @property
    def sort_key(self) -> tuple[int, int, int, str]:
        """Order arms by retrieval path, then handling, then language."""
        return (
            STRATEGY_ORDER[self.strategy],
            HANDLING_ORDER[self.handling],
            LANGUAGE_ORDER[self.language],
            self.name,
        )

    def paired_with(self, language: QueryLanguage) -> CrosslingualArm:
        """Return the same arm measured in the other query language."""
        return CrosslingualArm(**{**asdict(self), "language": language})

    def to_config(self) -> dict[str, Any]:
        """Return the canonical config dict consumed by artifacts and baselines.

        ``embedding.model`` and ``query.language`` carry the whole weight of every
        regression number in this module: ``latest_comparable_baseline`` matches on
        the serialized config, so an arm that omitted either would be compared
        against a run in a different vector space or a different language and the
        comparison would look valid.

        ``retrieval.reranker`` is recorded as null rather than left out. The M2.6
        cross-encoder is an English-trained model, so it stays off in every arm here;
        writing that down makes a future run that switches it on visibly incomparable
        instead of quietly contaminating the Korean slice.
        """
        translator = (
            None
            if self.translator_model is None
            else {"provider": "openai", "model": self.translator_model}
        )
        return {
            "name": self.name,
            "chunking": {
                "strategy": "structure-aware",
                "target_text_chars": self.target_text_chars,
                "golden_identity": "source-sha256-and-half-open-span",
            },
            "retrieval": {
                "strategy": self.strategy,
                "lexical_ranker": self.lexical_ranker,
                "reranker": None,
                "k": self.k,
                "candidate_k": self.candidate_k,
                "rrf_k": self.rrf_k,
            },
            "embedding": {
                "provider": self.embedding_provider,
                "model": self.embedding_model,
                "dimensions": self.dimensions,
            },
            "query": {
                "language": self.language,
                "handling": self.handling,
                "translator": translator,
            },
            "measurement": {
                "environment": "isolated-temporary-postgresql",
                "paid_api_calls": self.embedding_provider == "openai"
                or self.handling == "translated",
                "populated_corpus_embeddings_modified": False,
            },
        }
```

**코드에서 꼭 볼 것**

- `__post_init__`의 모든 거부는 타입이 아니라 귀속을 지킨다. `routed` 벡터 실험군은 탄 적 없는 경로를 주장하는 이름표를 붙인 direct 벡터 실험군이다 — 값은 진짜이고 이름이 거짓말이다.
- `retrieval.reranker`는 생략하지 않고 `null`로 적는다. **기록된 null은 영어로 학습된 cross-encoder를 켠 나중 실행을 눈에 띄게 비교 불가능하게 만들지만, 키를 빼 버리면 그 실행이 같은 기준선으로 슬쩍 합쳐진다.**
- 이름은 config가 기록하는 것과 같은 필드로 만들어지므로, 산출물 파일 이름과 그 config가 무엇이 돌았는지를 두고 어긋날 수 없다.
- `paired_with`는 동등성 단계가 다른 언어를 얻는 방법이다. 필드 하나가 바뀌고 `__post_init__`이 형태 전체를 다시 검증한다.

실험군은 `evaluate_retriever`에 곧장 들어가며 `run_ablation`을 거치지 않는다. `ExperimentConfig`에는 질의 언어나 처리 모드를 기록할 자리가 없고, 그 config 동일성 검사가 형태를 강요하기 때문이다. 나머지는 전부 — 채점, 출처, 지연, 산출물 스키마 — 손대지 않은 M3 하니스다.

### 2. 가장 싼 정직한 진단

코퍼스가 존재하기 전에 이미 답할 수 있는 질문이 하나 있다. 이 임베딩 공간은 한국어 질문을 영어 쌍둥이 근처 어디쯤에 놓는가? 짝 28개, `embed_documents` 호출 두 번, 데이터베이스 없음이다.

#### `app/evals/crosslingual.py` 확장 — 쌍둥이 정렬

**학습 행동 — 코퍼스 없는 진단을 구현한다:** 돌리기 전에 결정론적 공급자의 숫자를 예측하고, *정확히* 0이라는 예측이 맞았는지 확인한다.

<!-- src: app/evals/crosslingual.py::twin_query_alignment -->
```python
async def twin_query_alignment(
    provider: EmbeddingProvider,
    suite: BilingualSuite,
    *,
    provider_name: str = "unknown",
) -> TwinAlignment:
    """Measure how near each Korean query sits to its English twin, before any corpus.

    This is the cheapest honest answer to "does this embedding space recognize both
    languages at all": no database, no chunks, no retrieval. A token-hashing provider
    shares almost no tokens across the pair and lands near zero — near, not at, since
    384 hashed dimensions collide. A multilingual model places the twins close, and
    that difference is visible before a single arm is indexed.
    """
    pairs = suite.pairs()
    if not pairs:
        raise ValueError("twin alignment requires at least one pair")
    en_vectors = await provider.embed_documents([english.question for english, _ in pairs])
    ko_vectors = await provider.embed_documents([korean.question for _, korean in pairs])
    measured = tuple(
        TwinCosine(case_id=english.id, cosine=_cosine(en_vector, ko_vector))
        for (english, _), en_vector, ko_vector in zip(pairs, en_vectors, ko_vectors, strict=True)
    )
    cosines = [item.cosine for item in measured]
    return TwinAlignment(
        provider=provider_name,
        pair_count=len(measured),
        mean_cosine=sum(cosines) / len(cosines),
        min_cosine=min(cosines),
        max_cosine=max(cosines),
        pairs=measured,
    )
```

**코드에서 꼭 볼 것**

- 결정론적 공급자는 토큰을 384개 버킷으로 해싱하고 한글 어절도 토큰으로 유지하므로, 한국어 벡터는 비어 있지 않고 무관한 토큰이 공유 차원으로 충돌해 들어온다. **정직한 단언은 작은 상한이지 결코 `== 0.0`이 아니다** — 정확한 0 테스트는 첫 충돌에서 실패하고 아무것도 가르쳐 주지 않는다.
- `min_cosine`과 `max_cosine`을 평균과 나란히 보고한다. 짝 28개의 평균은 무너진 짝 하나를 가리기 때문이다.
- 짝별 코사인을 보관하므로 나쁜 쌍둥이를 진단 재실행이 아니라 사례 ID로 찾을 수 있다.

### 3. 붕괴를 세되, 가정하지 않는다

#### `app/evals/crosslingual.py` 확장 — lexical 커버리지

**학습 행동 — 붕괴 계수기를 구현한다:** 한국어에서 기대하는 비율을 적어 둔 뒤 docstring을 읽고 수정한다.

<!-- src: app/evals/crosslingual.py::lexical_candidate_coverage -->
```python
async def lexical_candidate_coverage(
    retriever: Retriever,
    cases: Sequence[GoldenCase],
    *,
    language: QueryLanguage,
    candidate_k: int = 20,
) -> LexicalCoverage:
    """Count how many questions the lexical arm answers with nothing at all.

    The retriever is injected rather than built from a session here, so the
    diagnostic is exercised offline against a scripted lexical arm and used in the
    measured run against ``make_retriever(session, strategy="lexical", ...)``.

    The rate is measured, not assumed. Korean questions about this corpus still carry
    Latin tokens — tickers, ``7nm``, ``G4ad`` — and the English tsquery can match
    those, so the collapse is partial in a way only the number shows.
    """
    if not cases:
        raise ValueError("lexical coverage requires at least one case")
    if candidate_k <= 0:
        raise ValueError("candidate_k must be positive")
    empty: list[str] = []
    total = 0
    for case in sorted(cases, key=lambda item: item.id):
        hits = await retriever(case.question, candidate_k)
        total += len(hits)
        if not hits:
            empty.append(case.id)
    return LexicalCoverage(
        language=language,
        case_count=len(cases),
        zero_candidate_cases=len(empty),
        zero_candidate_rate=len(empty) / len(cases),
        mean_candidate_count=total / len(cases),
        zero_candidate_case_ids=tuple(empty),
    )
```

**코드에서 꼭 볼 것**

- 매개변수는 세션이 아니라 `Retriever`다. 그래서 이 진단은 스크립트된 실험군을 상대로 오프라인에서 시험할 수 있고, 측정 실행은 `make_retriever(session, strategy="lexical", ...)`을 넘긴다 — M3가 이미 정의한 바로 그 콜러블 계약이다.
- **한국어 비율은 이야기가 원하는 100%가 아니라 코퍼스가 만들어 내는 숫자다.** 반도체 공시에 관한 한국어 질문은 티커와 공정 노드를 라틴 문자로 싣고 있고, 영어 인덱스는 그 렉심들을 기꺼이 매칭한다.
- `zero_candidate_case_ids`를 반환하므로 4장의 실패 분석이 실제로 붕괴한 사례에서 출발할 수 있다.

### 4. 언어는 두 번째 실행이지 새 차원이 아니다

#### `app/evals/crosslingual.py` 확장 — 조인

**학습 행동 — 조인을 작성한다:** 편집하지 *않아도* 됐던 모듈이 무엇인지 짚는다.

<!-- src: app/evals/crosslingual.py::category_breakdown,arm_comparison_markdown,language_category_markdown -->
```python
def category_breakdown(evaluation: RetrievalEvaluation) -> tuple[GroupScore, ...]:
    """Slice one evaluation by golden category through the unmodified breakdown."""
    cases = [case.golden for case in evaluation.cases]
    scores = [case.score for case in evaluation.cases if case.score is not None]
    return breakdown_by_category(cases, scores)


def arm_comparison_markdown(runs: Sequence[LanguageRun]) -> str:
    """Render one row per measured arm in deterministic arm order."""
    if not runs:
        raise ValueError("comparison requires at least one run")
    lines = [
        "| Arm | Strategy | Handling | Language | Cases | Recall@k | Hit rate@k | MRR | P95 ms |",
        "|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for run in sorted(runs, key=lambda item: item.arm.sort_key):
        score = run.evaluation.score
        lines.append(
            f"| {run.arm.name} | {run.arm.strategy} | {run.arm.handling} | "
            f"{run.arm.language} | {score.case_count} | {score.recall_at_k:.6f} | "
            f"{score.hit_rate_at_k:.6f} | {score.mrr:.6f} | "
            f"{run.evaluation.latency.p95_ms:.3f} |"
        )
    return "\n".join(lines)


def language_category_markdown(runs: Sequence[LanguageRun]) -> str:
    """Join the per-category slices of every run into one language-aware table.

    Language is not a breakdown dimension inside ``breakdown.py``; each language is a
    separate run of the unmodified harness, and the two are joined here at render
    time. That keeps ``GroupScore`` and the loader's span-identity rule untouched, and
    it is the same move M9.5 made when it sliced decomposition by category.
    """
    if not runs:
        raise ValueError("category table requires at least one run")
    lines = [
        "| Arm | Language | Category | Cases | Recall@k | Hit rate@k | MRR |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for run in sorted(runs, key=lambda item: item.arm.sort_key):
        for group in run.categories:
            lines.append(
                f"| {run.arm.name} | {run.arm.language} | {group.group} | "
                f"{group.case_count} | {group.recall_at_k:.6f} | "
                f"{group.hit_rate_at_k:.6f} | {group.mrr:.6f} |"
            )
    return "\n".join(lines)
```

**코드에서 꼭 볼 것**

- `breakdown_by_category`를 수정 없이 호출한다. **`GroupScore` 안에 언어 차원을 더했다면 이 모듈보다 먼저 존재한 채점기를 편집한다는 뜻이었다 — 조인은 틀려도 싼 렌더링 시점에 속한다.**
- 행은 `sort_key` 순서로 나오므로 같은 행렬을 두 번 돌리면 바이트 단위로 비교 가능한 표가 나온다.
- 비교 표는 모든 지표 옆에 사례 수를 찍는다. 언어당 채점된 양성이 24개면 뒤집힌 사례 하나가 약 0.042인데, `n`을 볼 수 없는 독자는 그것을 볼 수 없다.

의존성 하나가 이 파일 밖에 산다. `crosslingual.py`는 모듈 최상위에서 `MULTILINGUAL_SBERT_MODEL`을 임포트하고 `tests/crosslingual/test_02_crosslingual.py`도 같다 — 이 상수가 생기기 전에는 M8.2 명령이 실패하는 단언이 아니라 수집 단계의 `ImportError`로 죽는다. 무엇이든 돌리기 전에 `app/retrieval/sbert.py`에 이 한 줄을 더한다.

<!-- src: app/retrieval/sbert.py::MULTILINGUAL_SBERT_MODEL -->
```python
MULTILINGUAL_SBERT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
```

### 5. 측정 실행

측정은 테스트가 아니라 언제나 커맨드라인 실행이다.

```bash
docker compose up -d db
uv run python -m app.evals.crosslingual --provider sbert-multi --languages en ko --strategies lexical vector hybrid
```

`--provider sbert-multi`는 새 공급자 리터럴이 아니다. 기존 `sbert` 공급자를 네이티브 384차원인 `paraphrase-multilingual-MiniLM-L12-v2`로 향하게 한 것이라, 이 실험군은 `embed_dim`도 `Vector(384)` 컬럼도 마이그레이션도 건드리지 않고 벡터 공간만 바꾼다. 돌아온 결과를 [검증](../05-verify.md)에 기록한 뒤 계속한다 — 그 표가 다음 두 장이 비교 대상으로 삼는 "이전"이다.

### 집중 테스트와 그것이 지키는 계약

```bash
uv run pytest tests/crosslingual/test_02_crosslingual.py -q
```

기대 결과: 데이터베이스도 네트워크도 없이 `23 passed`.

| 테스트가 깨뜨리는 것 | 지키는 계약 |
|---|---|
| 언어나 모델을 빠뜨린 config를 가진 실험군 | 기준선은 언어별·벡터 공간별로 갈린다 |
| 하이브리드가 아닌 전략 위의 `routed` 실험군 | 실험군 이름은 탄 적 없는 경로를 주장할 수 없다 |
| 교차 언어 코사인을 정확한 0으로 단언 | 주장은 준직교이며 해시 충돌은 실재한다 |
| 하드코딩된 한국어 후보 0건 비율 | 붕괴는 가정이 아니라 측정이다 |
| `breakdown.py` 안에서 만든 카테고리 표 | M3 브레이크다운은 수정되지 않은 채 남는다 |

### 이제 설명할 수 있어야 하는 것

답은 위의 **굵은 핵심 문장**에 있다.

- **config 딕셔너리는 왜 `embedding.model`과 `query.language`를 명시적으로 싣는가?**
  - **답:** `latest_comparable_baseline`이 직렬화된 config로 대조하므로, 빠진 필드는 한국어 실행을 영어 기준선과, 또는 다국어 실험군을 토큰 해시 실험군과 조용히 비교하게 만든다.
- **결정론적 쌍둥이 코사인에 왜 0이 아니라 0에 가까움을 단언하는가?**
  - **답:** 384개 해시 버킷은 충돌하므로 무관한 토큰이 차원을 공유한다. 구조적 주장은 "이 공간은 두 언어를 관계 짓지 않는다"이고, 작은 상한이 그 주장의 정직한 테스트다.
- **lexical 후보 0건 비율을 왜 100%로 단언하지 않고 측정하는가?**
  - **답:** 한국어 질문은 영어 인덱스가 매칭하는 라틴 티커와 공정 노드를 싣고 있으므로 붕괴가 부분적이고, 얼마나 부분적인지는 숫자만 말해 준다.

---

[← 이전: 이중 언어 골든 스위트](01-bilingual-golden.md) · [모듈 개요](../03-build.md) · [다음: 라우팅과 번역 →](03-routing-and-translation.md)
