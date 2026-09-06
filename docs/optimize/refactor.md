# 리팩터링 기록

모듈 경계를 넘는 리팩터링을 기록한다. 체크포인트 단위 최적화는 [instruction.md](instruction.md)의 `mX` 문서가 맡고, 이 문서는 여러 파일·모듈에 걸친 구조 변경만 담는다. 모든 항목은 동작 보존이 원칙이다: 테스트는 변경 전후 모두 초록이어야 하고, 성능은 중립 이상이어야 하며, 공개 계약(`__all__`, 에러 메시지, SQL 결과 집합)은 바꾸지 않는다.

## R1 — M1+M2 정리 (2026-08-25)

M2.11 완료 시점의 전체 코드(M1 ingestion + M2 retrieval)를 대상으로 한 동작 보존 패스. 커밋마다 `make lint`와 관련 테스트 스위트(`tests/ingestion`, `tests/chunk`, `tests/db`, `tests/retrieval`)가 초록을 유지했고, 종료 시점에 `make docs`까지 전부 초록이다.

### R1-1. 지연 로딩 Protocol 제거 → 클로저 어댑터

- [대상] `app/retrieval/sbert.py`, `app/retrieval/cross_encoder.py`
- [변경] `_SentenceEncoder`·`_EmbeddingMatrix`·`_CrossEncoderModel` Protocol과 `cast()` 쌍을 제거했다. `_load()`가 모델을 만든 뒤 `Callable[[list[str]], list[list[float]]]`(sbert) / `Callable[[list[tuple[str, str]]], list[float]]`(cross-encoder) 클로저를 만들어 `_encoder`에 캐시하고 반환한다.
- [이유] 이 저장소에는 정적 타입체커가 없어 `cast()`는 어떤 검사에도 기여하지 않았고, Protocol 3개는 ruff `ANN` 규칙에 넣을 이름을 만들기 위한 장치였다. 클로저는 같은 어노테이션 요구를 클래스 없이 충족하면서 lazy import 경계를 그대로 유지한다.
- [정합성] 테스트가 고정하는 계약을 전부 보존했다: `_encoder` 속성명, `_load()` 반환값과 캐시의 동일성, 차원 검사 실패 시 `_encoder` 미할당, RuntimeError/ValueError 메시지. `tests/retrieval/test_10_sbert.py`·`test_11_cross_encoder.py` 통과.

### R1-2. 유한 실수 검증 4중복 → `types.finite_float`

- [대상] `app/retrieval/types.py`(헬퍼 신설), `embeddings.py`, `vector.py`, `rerank.py`, `bm25.py`
- [변경] bool 거부 → `numbers.Real` → `math.isfinite` 루프 본문을 `finite_float(value, *, nonnumeric, nonfinite)` 하나로 옮기고 네 경계가 위임한다. `rerank._scores`는 `rerank_hits` 안의 중첩 함수에서 모듈 레벨로 꺼냈다(참조 구현과 같은 위치).
- [이유] 같은 수치 계약이 네 파일에 네 번 복사돼 있어 계약을 고치려면 네 곳을 맞춰야 했다.
- [정합성] 각 경계의 에러 메시지 문자열을 인자로 넘겨 그대로 보존했다. `validate_embeddings`는 메시지 f-string을 벡터 루프 바깥에서 만들어 컴포넌트 핫루프 비용을 중립으로 유지했다.

### R1-3. 필터·SQL 중복 통일 (소유자: `lexical.py`)

- [대상] `app/retrieval/lexical.py`, `vector.py`, `bm25.py`
- [변경] `_filter_predicates`를 공개 `filter_predicates`로 승격하고 `needs_document_join`, `hit_columns`, `hit_order_by`를 추가했다. `vector._filtered_statement`는 predicate 구성을 위임하고, bm25는 `Document` join을 다른 두 경로처럼 조건부로 바꿨다.
- [이유] 같은 필터 계약이 세 파일에 세 가지 구현으로 존재했고, join 전략과 item predicate 순서가 이미 서로 어긋나 있었다. `ChunkHit` 11컬럼 projection과 6키 동점 정렬도 세 곳에 그대로 복사돼 있었다.
- [정합성] 결과 집합은 동일하다: `Chunk.doc_id`가 NOT NULL FK라 무필터 bm25에서 inner join을 빼도 행이 달라지지 않는다. 컴파일된 SQL 텍스트는 두 곳에서 달라진다 — bm25 무필터 구문의 `JOIN documents` 제거, vector의 item predicate가 lexical 순서(`IN` 먼저, `IS NULL` 나중)로 변경. `tests/retrieval/test_04_lexical.py`가 lexical의 조건부 join을 고정하므로 통일 방향은 조건부 join이다. live PostgreSQL 테스트 포함 `tests/retrieval` `172`개 통과.

### R1-4. 크로스모듈 private import 정리

- [대상] `embeddings._texts` → `validate_texts`, `types._hit_order_key_for_score` → `hit_order_key_for_score`, `xref._in_tables` → `in_tables`
- [변경] 다른 모듈이 import하던 `_` 이름 세 개를 공개 이름으로 승격하고 NumPyDoc을 채웠다. `sort_hits`는 같은 6-tuple을 인라인하는 대신 `hit_order_key_for_score`를 재사용한다.
- [이유] private 심볼이 모듈 경계를 넘으면 이름이 약속하는 비공개 계약이 깨지고, 이름을 지키려고 만든 언더스코어가 오히려 결합을 숨긴다.
- [정합성] 동작 변화 없음. `tests/ingestion/test_06_xref.py`의 import 1건만 함께 갱신했다.

### R1-5. config 리터럴 단일화

- [대상] `app/config.py`, `app/retrieval/bm25.py`, `app/retrieval/__main__.py`
- [변경] `EmbeddingProviderName` Literal과 `DEFAULT_BM25_K1`/`DEFAULT_BM25_B`/`DEFAULT_BM25_IDF` 상수를 `config.py`로 모았다. bm25와 CLI가 이를 import하고, argparse choices는 `typing.get_args`로 유도한다. CLI 전용 `ProviderName` 별칭과 bm25의 중복 상수는 삭제했다.
- [이유] provider 세 문자열이 세 곳(설정 Literal, CLI Literal, argparse choices)에, BM25 기본값이 두 곳에 복사돼 있었다.
- [정합성] 기본값 수치는 동일하다. `--provider` help의 choices 순서만 설정 Literal 순서 `("openai", "deterministic", "sbert")`로 바뀌며 테스트가 고정하지 않는다.

### R1-6. ingestion 정리

- [대상] `app/ingestion/chunk.py`, `seed.py`, `edgar.py`
- [변경] `index_text = context_header + "\n\n" + body` 규칙을 공개 `chunk.compose_index_text`로 모으고 `Chunk.content` property와 seed의 행 검증이 위임한다. 공개 `section_units()`가 반환하던 private `_Unit`을 문서화된 `Unit`으로 공개했다. edgar의 `CORPUS`는 하드코딩 대신 `Settings.corpus_dir`를 읽는다.
- [이유] 조합 규칙이 세 곳(+ ORM `synonym`)에 복사돼 구분자 하나를 바꾸려면 패키지 세 개를 맞춰야 했고, 공개 함수가 private 타입을 반환하고 있었다.
- [정합성] `app/retrieval/types.py`의 `ChunkHit` 검증자는 의도적으로 독립 유지했다 — retrieval 계약이 ingestion 구현에 의존하지 않게 하는 패키지 디커플링이다. seed의 에러 메시지(`... has inconsistent index text`)는 불변이다.

### R1-7. 위생 — 게이트 복구, 모듈 docstring, façade 정돈

- [대상] `scripts/check_doc_parity.py`, `scripts/format_docs.py`, `docs/localization.toml`, 모듈 docstring 누락 7개, `app/retrieval/__init__.py`, ko 문서 4개
- [변경] D202 `18`건 자동수정, `shared_roots`에 `optimize` 추가로 문서 인벤토리 게이트 복구, [docstring.md](docstring.md) 기준 모듈 docstring 7개 추가(`service.py`는 참조 문구 복원), `__all__`을 참조 정렬판으로 통일하고 façade가 존재하는 이유(`RETRIEVAL_MODULE` 스왑과 `__all__`·동일성 assert)를 모듈 docstring에 명시, ko 문서 4개의 구조 패리티(누락 불릿 블록·섹션) 복원.
- [정합성] `make lint`·`make docs`·`make test` 전부 초록.

## R2 — Pylance basic 타입 정합성 (2026-08-25)

`.vscode/settings.json`의 Pylance `typeCheckingMode: "basic"`을 기준으로 `app/` 전체와 M1·M2 테스트 스위트의 타입 에러를 `0`으로 만들었다. 실행 동작 변경 없음, 전 스위트 초록.

### R2-1. SQLAlchemy 표현식 어노테이션 확장

- [대상] `app/retrieval/lexical.py`, `app/retrieval/bm25.py`
- [변경] `hit_columns`의 반환 타입과 `_idf_expression`의 SQL 파라미터를 `ColumnElement` 대신 SQLAlchemy가 어노테이션용으로 제공하는 공개 상위 타입 `SQLColumnExpression`으로 바꿨다. ORM `InstrumentedAttribute`와 `Label`이 모두 여기에 속한다.
- [이유] `ColumnElement`는 ORM 속성(`Chunk.doc_id` 등)의 정적 타입을 포함하지 않아 basic 모드에서 에러가 났다. bm25 쪽은 M2.9부터 있던 기존 에러였고, lexical 쪽은 R1-3에서 만든 헬퍼의 어노테이션이 원인이었다.
- [정합성] 런타임 표현식 객체는 동일하며 어노테이션만 넓혔다. `tests/retrieval` `172`개 통과.

### R2-2. M1·M2 테스트 타입 정합성 (86건)

- [대상] `tests/db/`, `tests/retrieval/`
- [변경] (a) `hit_values` 등 이질 값 페이로드의 `dict[str, object]`를 `dict[str, Any]`로 — pydantic이 런타임 검증을 담당하는 딕셔너리의 정직한 타입이다. (b) `RetrievalFilters`에 리스트를 넘기던 자리를 선언 타입 그대로 튜플로 — 검증기 canonicalize 경로는 동일하게 지나며 컴파일된 SQL과 바인드 값도 변하지 않는다. (c) 의도적으로 계약을 위반하는 자리(`filing.item_index` 오류 주입, 덕타이핑 `_Engine`, 스텁 세션)는 `cast`로 의도를 표시했다. (d) `Model.__table__` 접근은 `isinstance(..., Table)` assert로 좁혀 런타임 확인을 겸한다. (e) pydantic-settings의 `_env_file` 인자는 런타임에 유효하지만 합성 시그니처에 없는 오탐이라, `tests/retrieval/conftest.py`의 `make_settings(**overrides)` 헬퍼에 억제를 한 곳으로 모으고 retrieval 테스트의 모든 `Settings` 직접 생성을 이 헬퍼로 통일했다 — 기본값을 검증하는 테스트가 개발자 `.env`에 흔들리지 않게 되는 격리 효과도 있다.
- [정합성] `tests/retrieval`+`tests/chunk`+`tests/db` `235`개, `make test` `333`개 통과. 억제는 서드파티 스텁 오탐에만 사용했고 `_ClassName`식 타입 맞춤 클래스는 만들지 않았다.

### R2-3. scripts 타입 정합성 (8건)

- [대상] `scripts/check_doc_code.py`, `scripts/check_doc_parity.py`, `scripts/measure_tables.py`
- [변경] (a) `symbol_span`의 네 return 지점에서 `node.end_lineno`를 `assert ... is not None`로 좁혔다 — 파싱된 소스에는 항상 존재한다. (b) `load_manifest`는 등가성 가드를 통과한 `raw.get()` 값 대신 검증 기준값(`expected_root`, `config.locales`)을 `InventoryManifest`에 직접 전달한다 — 증명된 동치라 동작이 같고 타입이 자명해진다. (c) `_normalize_destination`에서 `list[str]`로 선언된 `parts`에 tuple을 재대입하던 것을 `document_parts`로 분리했다. (d) `_span`의 bs4 `get` 기본값을 `cell.get(name) or 1`로 바꿨다 — None/빈 문자열 모두 기존과 동일하게 1로 수렴한다.
- [정합성] `make docs` 전 단계와 `make test`의 문서 게이트 테스트 통과. 스크립트 출력 불변.

## R3 — M3 평가 경계와 반복 파싱 제거 (2026-08-26)

M3.5 완료 시점의 M1 시드 준비, M2 검색 서비스, M3 평가·큐레이션 경계를 함께 검토했다. 골든 범위, 10개 실험군, 검색 결과와 품질 지표는 보존하고 동일 filing 파싱만 실행당 한 번으로 줄였다.

### R3-1. M1 시드 준비 분리 → M3 parse-once

- [대상] `app/ingestion/seed.py`, `app/evals/retrieval_eval.py`
- [변경] `parse_seed_filings`와 `build_seed_batch_from_filings`를 추가해 파싱과 청킹 경계를 분리하고, M3 CLI가 문서 `20`개를 한 번 파싱한 뒤 500/1200 청크 배치를 순차 생성하도록 바꿨다. 기존 `build_seed_batch`의 filing별 `parse → chunk` 순서와 공개 시그니처는 유지했다.
- [이유] 기존 M3 러너는 같은 20개 filing을 청크 목표마다 다시 파싱해 전체 실행에서 parser를 `40`회 호출했다. 청크 크기는 파싱 결과가 아니라 청킹에만 영향을 주므로 두 번째 파싱은 중복이었다.
- [정합성] 두 목표의 전체 `SeedBatch` SHA-256, 문서 `20`개, 청크 `12,984`/`9,172`개가 기존 경로와 정확히 같고 재사용 전후 `ParsedFiling` deep snapshot도 동일했다. AB/BA 5쌍 모두 의미 동등성을 통과했으며 `data/profiles`와 영구 코퍼스는 바뀌지 않았다.
- [벤치마크] 동일 Python·loopback PostgreSQL·deterministic provider에서 예열 후 AB/BA 5쌍을 측정했다. 전체 two-target 인덱싱 중앙값은 `79.235초 → 60.579초`로 `18.655초`(`23.54%`) 줄었고 parse+batch 중앙값은 `39.136초 → 22.759초`로 `41.85%` 줄었다.

### R3-2. 검색 전략 비교 조건과 provenance 통일

- [대상] `app/retrieval/service.py`, `app/retrieval/__init__.py`, `app/evals/ablation.py`, `app/evals/retrieval_eval.py`
- [변경] `normalize_query`를 공개 계약으로 승격하고 lexical·vector·hybrid 평가가 모두 같은 정규화 문자열을 받게 했다. BM25 실험군은 실제 `k1`·`b`·IDF를 구성과 artifact에 기록하고 lexical/hybrid 양쪽 호출에 같은 값을 전달한다.
- [이유] 이전에는 hybrid만 서비스 내부 정규화를 거쳤고 BM25 단일 경로는 함수 기본값, hybrid는 `Settings` 값을 사용해 환경 override가 있으면 비교 축 외 조건이 달라질 수 있었다.
- [정합성] 기존 private 이름은 동일 함수 객체를 가리키는 호환 별칭으로 남겼다. 최종 10개 실험 artifact는 시간과 새 provenance를 제외한 hit 순서·점수·Recall@5·Hit Rate@5·MRR이 `20260824T203336Z` 기준선과 모두 같았고, reranker 실험군은 추가하지 않았다.
- [벤치마크] 비교 정합성 수정에는 독립 성능 향상을 주장하지 않는다. 관련 `tests/db`·`tests/chunk`·`tests/retrieval`·`tests/evals` `342`개와 실제 PostgreSQL 경로가 통과했다.

### R3-3. 변경 경계 NumPyDoc 동기화

- [대상] `app/ingestion/seed.py`, `app/retrieval/service.py`, `app/evals/ablation.py`, `app/evals/retrieval_eval.py`, `app/evals/curation.py`, `app/evals/breakdown.py`, `scripts/benchmark_m3_parse_once.py`
- [변경] 공개 함수·메서드와 입력 검증·I/O·트랜잭션·동시성 경계에 실제 시그니처와 일치하는 `Parameters`·`Returns`/`Yields`·`Raises`·`Notes`를 적용했다. M3.5에서는 후보 입장·결정·승격·새 파일 출력과 엄격한 사례-점수 분해 계약을 추가했고, 클래스는 필드를 반복하지 않고 막는 잘못된 상태를 설명하며 짧은 헬퍼만 한 줄 docstring을 사용한다.
- [이유] Ruff의 `D` 규칙 통과만으로는 NumPyDoc 섹션과 호출자 계약이 존재하는지 보장할 수 없다. 코드 변경과 docstring을 같은 작업에서 맞춘다는 [docstring 기준](docstring.md)을 실제 소스와 최적화 기록에 함께 반영했다.
- [정합성] 기존 다섯 파일은 교정 전 staged 코드와 현재 코드에서 docstring을 제거한 AST가 동일하다. M3.5 두 파일은 집중 테스트 14개로 실행 계약을 검증했고, M1.4·M2.7·M3.4·M3.5 `[수정코드]`를 최종 docstring을 포함한 소스와 일치시켰다.
- [벤치마크] 실행 동작을 바꾸지 않은 문서화 작업이므로 성능 향상을 주장하지 않는다.

### R3-4. M3 테스트 타입 검사 복구

- [대상] `pyproject.toml`, `tests/evals/test_03_regression.py`, `tests/evals/test_06_postgres.py`
- [변경] M3 완료에 맞춰 `tests/evals`를 pyright 제외 목록에서 제거했다. ORM `__table__`은 `Table`, `created_at.type`은 `DateTime`임을 런타임 assert로 좁혔고, PostgreSQL 실험군 튜플은 `RetrievalStrategy`와 `LexicalRanker`로 선언해 parametrized 문자열의 실제 Literal 계약을 보존했다.
- [이유] 테스트 실행은 통과했지만 제외를 제거하면 SQLAlchemy의 넓은 합성 타입과 pytest 파라미터의 `str` 추론 때문에 basic 모드 오류 4건이 드러났다. 억제나 cast 대신 테스트가 실제로 요구하는 런타임 타입과 Literal 축을 명시했다.
- [정합성] 대상 테스트 20개와 전체 `tests/evals` 131개가 통과했고, `basedpyright app tests scripts`는 `0 errors`다. 실행되는 SQL 표현식과 실험군 값은 바뀌지 않았다.

## R4 — M4 공급자·관측·워크플로 경계 정합성 (2026-08-26)

M4.4 완료 시점의 strict provider, observability adapter, 네 노드 workflow를 함께 검토했다. 외부 SDK와 Pydantic 결과, Protocol trace, workflow Literal 사이의 실행 계약은 유지하고 정적 타입이 그 경계를 그대로 표현하게 했다.

### R4-1. M4 경계 타입과 NumPyDoc 동기화

- [대상] `app/llm/`, `app/observability/`, `app/workflow/`
- [변경] OpenAI injected client는 `object` 입력을 최소 Responses Protocol로 한 번 좁히고, provider 결과를 받는 observability Protocol은 read-only property로 만들어 구체 Pydantic 필드의 좁은 타입을 허용했다. 노드 failure 변환은 `BaseModel` bound generic과 `GradeOrCheckNode`를 사용한다. 누락된 모듈 docstring을 복원하고 공개·복합 파싱, 예산, I/O, 상태 전이 경계의 NumPyDoc을 실제 시그니처·예외·반환값에 맞췄으며, 호출마다 재생성되던 `_jsonable_refusal`은 캡처가 없는 모듈 헬퍼로 복원했다.
- [이유] `Any` client·response와 mutable Protocol 속성은 실제 duck-typed 경계를 너무 넓게 만들거나 invariant로 만들어, 올바른 `ProviderResult[RelevanceJudgment]`와 `ProviderResult[AnswerDecision]`도 adapter에 전달할 수 없었다. Ruff 통과만으로는 provider repair·secret persistence·workflow budget의 실패 조건이 문서화되지 않는다.
- [정합성] M4 offline 테스트 `81 passed`, live OpenAI 1건은 명시적 opt-in 조건으로만 skip되며, scoped Ruff와 basedpyright는 `0 errors`다. 외부 요청 인자, provider 상태, trace JSON, 노드 순서와 observer 동작은 변경하지 않았다.

### R4-2. M4 테스트 타입 검사 복구

- [대상] `pyproject.toml`, `tests/workflow/test_03_observability.py`, `tests/workflow/test_06_openai_live.py`
- [변경] M4 완료에 맞춰 `tests/workflow`를 pyright 제외 목록에서 제거했다. ORM table은 `Table` assert로 좁혔고, skip 조건이 보장하는 live model·credential은 테스트 안에서 non-None임을 확인했다.
- [이유] decorator의 skip 조건은 정적 흐름을 좁히지 않고 SQLAlchemy `__table__`의 합성 타입은 constraints를 노출하지 않아, 실행은 맞아도 basic 모드 오류 3건이 남았다.
- [정합성] `basedpyright tests/workflow`가 `0 errors`이며 offline 테스트 결과와 live opt-in 조건은 그대로다.

### R4에서 검토 후 보류한 항목

- `Trace(run_id, step)`의 unique constraint와 같은 열의 명시적 index 중복 제거: PostgreSQL은 unique index를 이미 만들지만, 스키마·migration 변경이며 실제 `EXPLAIN`·insert·relation-size 측정 없이 제거하지 않았다.
- runner의 세 success-report 조립을 helper로 합치기: 코드 중복은 줄지만 clock 읽기 시점과 observer 순서를 바꿀 위험이 있고 성능 이득이 없어 유지했다.
- retrieve·grade·check 패스 결합: 기본 evidence 수가 작고 제거 사유·source order·context 절단 순서가 관측 가능한 계약이라 유지했다.

## R5 — M5 HTTP·runtime·SSE 경계 정합성 (2026-08-27)

M5.4 완료 시점의 public schema, FastAPI error handling, runtime/CLI composition, SSE task 수명을 함께 검토했다. 외부 응답은 내부 detail을 노출하지 않고, import와 DB connection은 실제 요청 전까지 만들지 않으며, client disconnect는 진행 중 workflow를 취소한다.

### R5-1. 비누출 HTTP 오류와 OpenAPI 일치

- [대상] `app/api/errors.py`, `schemas.py`, `app.py`, `routes/*.py`
- [변경] 5xx detail을 고정 public 메시지로 닫고 HTTPException header를 보존했으며, unexpected exception은 server traceback만 기록한다. Run status와 failure subtype을 상관 검증하고 public JSON 전체를 built-in credential redaction에 통과시켰다. 공통 422·500과 resource별 400·404·503, review terminal 429·502·503, SSE media type을 실제 OpenAPI response schema로 선언했다.
- [이유] 기존 구현은 5xx detail과 workflow exception 문자열을 외부에 노출하고 405 `Allow`를 버렸으며, FastAPI 기본 422 schema와 누락된 terminal status를 광고했다. `budget_exceeded + NodeError` 같은 모순도 429 body로 통과했다.
- [정합성] 기존 성공·typed failure 상태 코드는 유지하고 sentinel secret, status/failure 교차행렬, transport header와 OpenAPI `$ref`/`anyOf`를 집중 테스트로 고정했다.

### R5-2. import·event loop·DB transaction 수명 축소

- [대상] `app/api/runtime.py`, `app/main.py`, `app/cli.py`, `app/api/routes/stream.py`
- [변경] process session/engine은 실제 DB 작업까지 lazy resolve하고 CLI help는 retrieval runtime import 전에 완료한다. ingest의 동기 corpus 준비는 worker thread로 옮기고 retrieval read transaction은 provider 호출 전에 종료한다. review provider 오류는 typed 503으로 통일하며 secret-safe report를 persistence와 HTTP/SSE가 공유한다. SSE producer는 iterator 소비 시 시작하고 response-level close가 disconnect/send failure에서 task를 취소한다.
- [이유] import가 잘못된 DB URL 때문에 실패하고 CLI help가 무관한 설정 검증에 막혔으며, event loop와 DB connection이 parsing·LLM 대기 동안 점유됐다. SSE도 client가 사라진 뒤 유료 workflow를 계속 실행할 수 있었다.
- [정합성] invalid 환경 subprocess, worker-thread identity, transaction fake, provider error, explicit secret, direct ASGI send failure를 검증했다. fresh import 15회 중앙값은 `1,426.215ms → 1,387.657ms`(`2.70%`)였지만 채택의 주 근거는 외부 자원 수명이다.

### R5-3. M5 타입·NumPyDoc·테스트 검사 복구

- [대상] `app/api/`, `app/main.py`, `app/cli.py`, `tests/api/`, `pyproject.toml`
- [변경] DB 문자열은 strict `TypeAdapter`로 public Literal에 좁히고 argparse subparser 타입은 실제 generic으로 선언했다. package/module docstring과 Protocol·복합 I/O NumPyDoc을 현재 동작에 맞췄다. `tests/api`를 basedpyright 제외에서 제거하고 partial test double·CLI JSON envelope·ORM table 경계를 명시적으로 좁혔다.
- [이유] 기능 테스트는 통과해도 DB→domain Literal, Protocol, argparse, test-double 타입 오류와 누락된 public 문서 계약이 남아 있었다.
- [정합성] M5 focused test, scoped Ruff/format, app+tests basedpyright를 통과하고 test double의 실행 동작은 바꾸지 않았다.

### R5에서 검토 후 보류한 항목

- `/ingest` 인증과 server-local manifest root 제한: 외부 공개 서비스라면 필수지만 신뢰된 local control-plane인지 공개 endpoint인지 제품 정책이 정해지지 않아 임의로 권한 모델을 추가하지 않았다. M7 auth/rate/body-size 정책과 함께 결정해야 한다.
- default runtime의 deterministic embedding: `Settings.embedding_provider`와 다르지만 환경값만으로 유료 호출하지 않는 현재 fail-closed 정책을 우선해 유지했다.
- injected session factory와 bootstrap engine의 단일 DB 보증: 현재 Protocol만으로 두 객체의 identity를 증명할 수 없어 paired database resource 도입을 별도 구조 결정으로 남겼다.
- CLI `sbert` choice 추가: Settings는 지원하지만 M5 CLI 공개 계약은 deterministic/openai 두 값으로 고정돼 있어 선택적 provider 노출 여부를 별도 결정으로 남겼다.
- API public façade lazy화: cold import 대부분이 M2/M4 façade의 eager re-export에서 와서 M5 내부 import만 바꾸는 것으로 해결되지 않으며, re-export identity 계약을 건드리는 교차 모듈 변경이라 보류했다.
- SSE heartbeat: 필요한 주기는 M7 proxy timeout 정책에 의존하므로 buffering 방지 header만 추가하고 임의 heartbeat는 넣지 않았다.

## R6 — M6 정직한 데모 투영과 Gradio 경계 정합성 (2026-08-27)

M6.3 완료 시점의 canned fixture, injected M5 runtime projection, Gradio event와 portfolio evidence 표면을 함께 검토했다. retrieval-only 후보는 미검토 상태로 구분하고 화면의 support 표시는 최종 workflow 판정과 evidence identity가 모두 일치할 때만 열리며, optional UI dependency와 credential-bearing 출력은 application import 또는 browser로 새지 않는다.

### R6-1. terminal report·evidence card 단일 support 계약

- [대상] `app/demo.py`, `tests/demo/test_demo.py`
- [변경] `M5Service.review`를 `RunReport` 반환으로 고정하고 `RunResponse.from_run_report`가 terminal status·typed failure·`WorkflowReport`를 검증한다. review answer는 최종 report answer를 사용하며 `SUPPORTED` citation의 chunk ID·문서 ID·citation·span·source SHA-256이 별도 retrieval hit와 모두 일치할 때만 해당 body를 evidence card로 공개한다. retrieval-only query는 `supported=None`으로 구분하고 `NOT_IN_DOCS`, typed failure, malformed response, identity mismatch는 evidence 없는 결과로 닫는다.
- [이유] 기존 구현은 retrieval 후보가 하나라도 있으면 최종 workflow가 `NOT_IN_DOCS` 또는 `error`여도 지원됐다고 표시하고 answer 대신 report dict를 문자열로 노출했다. M6는 evidence body를 위해 별도 retrieval을 수행하므로 두 실행이 같은 source identity라는 가정도 검증해야 한다.
- [정합성] M5 공개 반환 타입과 query-only evidence shape는 유지했다. 실제 `RunReport` 성공·부재·실패와 SHA mismatch 회귀가 answer, reviewed/unreviewed support, evidence, trace 상태를 고정한다.

### R6-2. canned·credential·optional UI fail-closed 경계

- [대상] `app/demo.py`, `tests/demo/test_demo.py`
- [변경] canned revenue는 정규화된 선언 질문 세 개만 지원하고 나머지는 빈 evidence로 거부한다. answer·완성 trace·release notice는 final presentation 경계에서 기존 redactor를 통과하며 invalid Pydantic request는 `invalid_request` UI 결과로 닫는다. Gradio component는 `build_demo()` 안에서만 import하고 누락 시 stable `RuntimeError`를 반환하며 기본 module 실행은 `127.0.0.1`, `share=False`를 명시한다.
- [이유] `"revenue"`·`"acme"` 부분 문자열은 다른 회사나 무관한 Acme 질문에 가짜 revenue 근거를 붙였고, injected 오류의 API key·bearer token은 화면에 그대로 나왔다. top-level Gradio import는 optional dependency handler보다 먼저 실패하고 환경변수 기반 외부 bind/share도 M6 local 경계를 약화했다.
- [정합성] 두 기존 revenue fixture의 답변·evidence·zero-cost trace는 유지한다. 빈 query, answer·model·cost·error·release notice의 실제 secret token, missing import, Gradio `Blocks` construction과 canned `process_api` callback을 회귀로 실행한다.

### R6-3. M6 타입·NumPyDoc·검사 범위 복구

- [대상] `app/demo.py`, `tests/demo/test_demo.py`, `pyproject.toml`, `docs/optimize/m6/`
- [변경] mode Literal, `RunReport` Protocol 반환, Gradio `Blocks` 반환을 실제 분기와 맞추고 module·Protocol method·public method·복합 helper에 영어 NumPyDoc을 적용했다. `tests/demo`를 basedpyright 제외에서 제거하고 review·redaction·UI callback 테스트를 추가했다.
- [이유] 기존 6개 기능 테스트가 통과해도 Ruff 9건과 basedpyright 9건이 남아 review 결과를 `None`으로 추론하고 runtime mode와 optional dependency 경계를 검사하지 못했다.
- [정합성] source-level `Any`나 타입 억제를 추가하지 않았고 M6 집중 suite `17 passed`, M6+API 결합 `23 passed`, M7·M9 미래 테스트를 제외한 M1–M6 전체 `891 passed, 1 skipped`, Ruff, format, app+demo basedpyright를 통과했다. UI callback의 경고 1건은 Python 3.14의 deprecated `asyncio.iscoroutinefunction`을 사용하는 Gradio 6.15.1 내부 경고이며 application 실패가 아니다.

### R6에서 검토 후 보류한 항목

- review와 evidence body의 단일 retrieval 보증: 현재 M5 `RunReport`는 citation identity만 전달하고 body를 포함하지 않아 M6가 별도 retrieval을 해야 한다. M5 combined response 또는 workflow-state 공개는 API 계약을 넓히므로 이번에는 complete identity 대조 후 불일치를 거부하는 방식으로 닫았다.
- `LiveDemoService` 제거: 단순 위임이지만 기존 M6 공개 surface와 source-linked 문서가 사용한다. 정확성 결함을 만들지 않으며 제거 이득이 작아 유지했다.
- Gradio UI 성능 최적화·component 분할: 화면은 수개의 component와 최대 10개 evidence card만 만들고 provider·retrieval I/O가 지배적이다. 측정된 병목 없이 캐시나 새 UI abstraction을 추가하지 않았다.
- 배포 인증·rate limit·body-size·proxy heartbeat: M7의 공개 bind와 비용 정책이 소유하므로 local M6 demo에서 임의 정책을 선반영하지 않았다.

## R7 — M9 에이전트 실패 경로 투영 단일화 (2026-08-27)

M9.6 완료 시점의 tool registry, agent loop, MCP server를 함께 검토했다. 실패 경로의 공개 문자열과 fail-closed 계약은 그대로 두고, 두 표면에 복사돼 있던 시크릿 편집 규칙만 소유자를 하나로 모았다. 변경 전후 `tests/agent` `42`개와 `make test` `312`개가 초록이다.

### R7-1. 시크릿 안전 오류 투영 단일화 → `tools.safe_runtime_error`

- [대상] `app/agent/tools.py`(헬퍼 신설), `app/agent/loop.py`, `app/agent/mcp_server.py`
- [변경] `loop._safe_runtime_error`를 `tools.safe_runtime_error`로 승격하고 NumPyDoc을 채웠다. loop의 4개 호출 지점(tool 실행·직렬화·evidence 추출·provider 요청)과 MCP server가 f-string으로 직접 조립하던 2개 지점(`tool execution`, `tool serialization`)이 모두 이 함수에 위임한다.
- [이유] "예외 타입명만 남기고 메시지 본문은 버린다"는 편집 규칙이 두 파일에 두 가지 구현으로 존재했다. loop 쪽만 고치면 MCP server가 조용히 옛 형식을 유지하고, 그 형식이 노출하는 대상은 자격증명이 실릴 수 있는 서버 내부 예외 메시지다. 모듈 경계를 넘는 헬퍼이므로 R1-4와 같은 이유로 언더스코어를 떼고 공개 이름으로 옮겼다.
- [정합성] 생성되는 문자열은 여섯 지점 모두 이전과 바이트 단위로 같다(`f"{type(error).__name__}: {action} failed"`). `tools.py`는 `app.agent.types`만 import하므로 MCP server가 openai SDK를 끌어오는 `loop`에 의존하게 되지 않는다. `app/agent/__init__.py`의 `__all__`은 바꾸지 않았다 — 패키지 공개 표면이 아니라 모듈 간 내부 헬퍼다. 시크릿 미노출을 고정하는 `tests/agent/test_04_loop.py::test_provider_failure_does_not_expose_exception_secrets`와 `test_07_mcp_cli.py::test_mcp_call_tool_converts_execution_and_serialization_failures` 통과.

### R7에서 검토 후 보류한 항목

- `builtin_tools.py`·`decompose.py`의 지연 `retrieve` shim 통합: 두 파일이 `TYPE_CHECKING` 블록, `_RetrievalResult` Protocol, `retrieve` 래퍼, `DEFAULT_RRF_K`를 거의 그대로 복사한다. 공유 모듈로 합치면 각 모듈의 monkeypatch 이음매(`sys.modules[...].retrieve`)는 유지되지만, shim이 존재하는 이유 자체가 "이 모듈이 `app.retrieval`을 즉시 import하지 않는다"이므로 세 번째 모듈은 그 경계를 한 단계 더 흐린다. 사용처가 두 곳뿐이라 중복 비용보다 간접화 비용이 커서 유지했다.
- `merge_ranked_lists`의 `identity()`에 `index_text` 사용: 현재 tuple은 `body`를 포함하고 `context_header`는 제외해, 같은 body에 다른 header를 단 두 hit을 통과시킨다. `index_text`(= header + body)로 바꾸면 엄밀히 더 강한 검사지만 새로 거절되는 입력이 생기는 동작 변경이라 완료 검수 범위 밖으로 두었다. 실제 두 hit은 같은 DB 행에서 오므로 현재 관측 가능한 결함은 없다.
- `AgentStep(step=len(steps) + 1, ...)` 5개 지점의 조립 통일: 각 지점의 `observations` 인자가 서로 달라(`()`·rejections·실제 관측) 공통 헬퍼가 분기를 되살린다. 반복은 형태뿐이고 계약은 지점마다 달라서 유지했다.

## R1에서 검토 후 보류한 항목

- `app/retrieval/__init__.py` façade 제거: conftest의 `R` fixture와 `RETRIEVAL_MODULE` 스왑 메커니즘이 "전체 계약을 노출하는 모듈 하나"를 전제하고, 미래 M4/M5 테스트도 `from app.retrieval import ...`를 쓴다. 제거하면 같은 표면을 테스트 쪽에서 재조립해야 해 순복잡도가 늘어서 유지한다.
- `parser.py` 분할: 분할하면 parser.py가 재수출 façade가 돼야 하고(`PARSER_MODULE` 경로와 문서 `src:` 마커 `86`개가 심볼을 고정) 피하려는 패턴을 재생산한다. 파일 내부 정리는 이후 패스에서 재검토.
- `ChunkKind` Literal 중복(`ingestion/chunk.py`·`retrieval/types.py`): 패키지 간 의존을 추가하지 않기 위한 의도적 중복.
- `from __future__ import annotations` 통일: pydantic 모델이 런타임 어노테이션에 의존해 일괄 적용이 안전하지 않고, 파일별 이득이 없다.
- `db/session.py`의 import 시점 엔진 생성: `Session`·`engine` 모듈 속성이 공개 표면이라 지연화는 `seed`·`__main__`·테스트로 파급된다. M3+에서 필요해질 때 재검토.
- `app/db/__init__.py` 추가: 참조 구현도 namespace 패키지라서 추가하면 구조만 갈라진다.
- 테스트 더블 네이밍 통일(`_X`/`FakeX`/bare): 테스트 전용 관례 문제로 이번 범위에서 제외.

## 이후 모듈 케이던스

모듈 하나가 완료될 때마다 그 모듈까지를 범위로 한 R-pass를 추가한다(M3 완료 → R3, M4 완료 → R4). 아직 구현되지 않은 모듈의 코드는 미리 손보지 않고, 이 문서와 [docstring.md](docstring.md)의 컨벤션을 구현 시점부터 적용한다.
