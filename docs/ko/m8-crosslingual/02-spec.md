# M8 명세 — 쌍둥이, 실험군, 동등성 게이트

## 1. 범위

이 명세는 M8 경로 전체를 정의한다. 영어 스위트와 같은 불변 정답 span에 묶인 한국어 쌍둥이 골든 스위트, 정규 출처를 싣는 교차 언어 실험군 행렬, 질의 경로 진단 두 개, 검색 서비스의 언어 인식 질의 처리, 그리고 게이트가 딸린 ko/en 동등성 정의다. 계층은 순서대로 만든다. M8.1 쌍둥이, M8.2 측정, M8.3 질의 처리, M8.4 동등성이다.

M8은 어떤 평가 계약도 바꾸지 않는다. `app/evals/scoring.py`, `app/evals/breakdown.py`, `app/evals/regression.py`와 산출물 스키마는 M3가 남긴 그대로 쓴다. 언어는 채점기 안의 새 축이 아니라 같은 하니스의 두 번째 실행으로 들어온다.

## 2. 쌍둥이 스위트 계약

한국어 스위트는 별도 파일 `data/golden/retrieval_ko.json`이며, `m3c-NN` 형태의 ID를 `data/golden/retrieval.json`과 공유하는 사례 28개를 담는다. 이 모듈은 `data/golden/retrieval.json`을 편집하지 않는다.

파일 분리는 선호가 아니라 강제다. `load_golden_cases`는 한 번에 적재된 배치 안에서 중복 정답 span 식별자를 거부하고 쌍둥이는 설계상 모든 span을 공유한다. `load_golden_cases`를 두 번 호출하면 각 파일이 로더의 완전한 매니페스트, SHA-256, 경계, 눈으로 확인 가능한 증거 검증을 독립적으로 받는다.

`validate_twin_cases(en_cases, ko_cases)`는 이 계약을 강제하고 순서가 맞춰진 짝을 돌려준다. 요구 사항은 다음과 같다.

1. 두 스위트 모두 비어 있지 않고, 각 스위트 안에 중복 사례 ID가 없다. 2. 두 스위트의 ID 집합이 동일하다. 3. 짝마다 `TWIN_INVARIANT_FIELDS`의 모든 필드 — `category`, `facet`, `tags`, `answers`, `expected_label`, `reference_answer` — 값이 동일하다. 4. 짝마다 대소문자와 공백을 정규화한 뒤 질문이 서로 다르다. 5. 영어 질문에 한글이 없다. 6. 한국어 질문에 한글이 최소 한 자 있다.

규칙 4는 규칙 5와 6보다 먼저 검사한다. 질문을 그대로 복사해 붙여 넣는 것이 실제로 일어나는 저작 실수이고, 이를 "한글이 없음"으로 보고하면 원인이 아니라 증상을 이름 붙이게 된다.

`reference_answer`는 양쪽 모두 영어로 남는다. 검색 채점은 이 필드를 절대 읽지 않으며, 동일성을 요구하면 불변 조건이 근사치가 아니라 검사 가능한 것이 된다. `app/evals/bilingual.py`의 한글 스캔은 `app/retrieval/language.py`에서 가져오지 않고 이 모듈 안에 둔다. 스위트 계약은 질의 경로 코드가 존재하기 전에 성립해야 하는데, 헬퍼를 공유하면 첫 체크포인트가 세 번째 체크포인트에 의존하게 된다.

부재 사례는 두 언어 모두에서 부재로 남는다. 정답 span이 0개이고 `expected_label="NOT_IN_DOCS"`, `reference_answer="NOT_IN_DOCS"`인 한국어 질문 네 개다. 모든 사례는 `curation_status="agent-curated"`, `approval_status="pending-author-approval"`, `human_verified=false`를 유지한다. 쌍둥이는 이미 선별된 영어 사례의 번역이며, 검증기는 그 기계 게이트일 뿐 작성자 검토를 대신하지 않는다.

## 3. 실험군 문법

실험군 이름은 소문자 케밥 표기법이고 파일 이름으로 써도 살아남아야 한다.

```text
xling-<provider>-<strategy>[-<ranker-slug>][-<handling>]-<lang>
```

- `<provider>`는 `deterministic`, `openai`, `sbert`, `sbert-multi` 중 하나다.
- `<strategy>`는 `lexical`, `vector`, `hybrid` 중 하나다.
- `<ranker-slug>`는 `ts-rank-cd` 또는 `bm25`이며, lexical 질의를 던지는 전략에는 반드시 있고 `vector`에는 없다.
- `<handling>`은 `routed` 또는 `translated`이며, 처리가 `direct`일 때는 통째로 생략한다.
- `<lang>`은 `en` 또는 `ko`다.

예시: `xling-deterministic-vector-en`, `xling-deterministic-hybrid-ts-rank-cd-en`, `xling-sbert-multi-hybrid-ts-rank-cd-routed-ko`.

실험군 생성자는 숫자의 귀속이 불가능해지는 형태를 거부한다. lexical 랭커를 이름에 넣은 `vector` 실험군, 랭커를 빠뜨린 lexical 또는 하이브리드 실험군, `routed` 또는 `translated` 실험군이 `hybrid`가 아닌 전략 위에 놓인 경우, 번역 모델이 없는 `translated` 실험군이나 번역 모델을 가진 비번역 실험군, 그리고 서로 모순되는 `k`, `candidate_k`, `rrf_k`가 그렇다. 청킹은 M3의 승리 목표인 1200자에 고정하므로 행렬의 축은 임베딩 공간, 검색 전략, 질의 언어, 질의 처리 넷뿐이다.

## 4. 정규 config 딕셔너리

모든 실험군은 `evaluate_retriever`가 기록하고 `latest_comparable_baseline`이 대조하는 config 딕셔너리를 발행한다.

```json
{
  "name": "xling-sbert-multi-hybrid-ts-rank-cd-routed-ko",
  "chunking": {
    "strategy": "structure-aware",
    "target_text_chars": 1200,
    "golden_identity": "source-sha256-and-half-open-span"
  },
  "retrieval": {
    "strategy": "hybrid",
    "lexical_ranker": "ts_rank_cd",
    "reranker": null,
    "k": 5,
    "candidate_k": 20,
    "rrf_k": 60
  },
  "embedding": {
    "provider": "sbert-multi",
    "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "dimensions": 384
  },
  "query": {
    "language": "ko",
    "handling": "routed",
    "translator": null
  },
  "measurement": {
    "environment": "isolated-temporary-postgresql",
    "paid_api_calls": false,
    "populated_corpus_embeddings_modified": false
  }
}
```

이 모듈의 모든 회귀 숫자의 무게는 `embedding.model`과 `query.language`가 진다. `latest_comparable_baseline`은 직렬화된 config로 대조하므로, 둘 중 하나를 빠뜨린 실험군은 다른 벡터 공간이나 다른 언어의 실행과 비교되고 그 비교는 유효해 보이면서 엉뚱한 차이를 재게 된다.

`retrieval.reranker`는 모든 M8 실험군에서 생략하지 않고 `null`로 기록하며, M2.6 cross-encoder는 모든 실험군에서 꺼 둔다. 그 모델은 영어 질의-구절 쌍으로 학습됐으므로 켜면 한국어 입력에서 측정된 적 없는 채점기가 한국어 슬라이스를 재정렬하게 된다. null을 적어 두면 나중에 리랭커를 켠 실행이 한국어 숫자를 조용히 오염시키는 대신 눈에 띄게 비교 불가능해진다.

`measurement.paid_api_calls`는 임베딩 공급자가 `openai`이거나 처리가 `translated`일 때 정확히 참이다. 평가 러너는 `temporary_corpus_session`으로 임시 테이블에 자기 코퍼스를 직접 만들므로 어떤 실험군도 채워진 코퍼스 임베딩을 수정하지 않는다.

## 5. 질의 처리

처리 값은 셋이고 전부 무수정 M3 리트리버 팩토리 위의 래퍼로 만든다. 그래서 비교는 질의 경로 사이에서 일어나며 절대 평가 코드 경로 사이에서 일어나지 않는다.

| 처리 | 한국어 질의 경로 | 영어 질의 경로 | 비용 |
|---|---|---|---|
| `direct` | 완전한 하이브리드, lexical 구성 요소 포함 | 완전한 하이브리드 | 없음 |
| `routed` | lexical 구성 요소 생략, 랭킹은 벡터만 | 완전한 하이브리드 | 없음 |
| `translated` | 영어로 번역한 뒤 완전한 하이브리드 | 완전한 하이브리드 | 질의당 LLM 호출 한 번 |

`detect_query_language(query)`는 비어 있지 않은 질의 하나를 유니코드 범위 셋 — 완성형 음절 `U+AC00`–`U+D7A3`, 조합용 자모 `U+1100`–`U+11FF`, 호환 자모 `U+3130`–`U+318F` — 을 훑어 분류한다. 한글이 하나라도 있으면 한국어다. 규칙은 비율이 아니라 존재다. 이 코퍼스에 관한 한국어 질문은 티커, 공정 노드, 회계연도를 라틴 문자로 싣고 다니므로, 다수 문자 기준 규칙은 이 모듈이 존재하는 이유인 바로 그 질의들을 잘못 라우팅한다. 빈 질의는 영어로 기본값을 잡는 대신 예외를 던진다.

`retrieve()`에는 매개변수 하나 `route_by_language: bool | None = None`이 붙는다. M2.6의 `reranker` 매개변수와 같은 형태다. `None`이면 `Settings`에서 해석한다. 라우팅이 켜진 상태에서 한국어 질의가 들어오면 lexical 구성 요소는 빈 리스트를 돌려주고, 그래서 어떤 경로를 탔는지가 설정에서 추론되는 대신 `ComponentRankings.lexical`에서 읽힌다.

`app/config.py`에는 정확히 필드 하나 `query_language_routing: bool = False`가 붙는다. 꺼진 채로 출하한다. M8은 출하된 질의 경로를 바꾸기 전에 붕괴를 측정한다.

번역은 명시적 주입만 허용하며 의도적으로 `Settings` 모드가 아니다. `translate_query(query, *, llm_provider, provider_budget)`는 호출자가 공급자와 예산을 이미 쥐고 있기를 요구하므로, 어떤 설정 플래그도 유료 네트워크 호출을 요청하지 않은 요청 안에 밀어 넣을 수 없다. 공급자가 거부하거나, 예산을 소진하거나, 스키마 검증에 실패하거나, 한글이 여전히 남은 질의를 돌려주면 `QueryTranslationError`를 던진다. `decompose_query`와 달리 입력으로 폴백하지 않는다. 번역이 실패했는데 폴백하면 번역된 것처럼 한국어 질의가 채점되고, 그러면 측정된 숫자는 실행된 적 없는 실험군을 묘사하게 된다.

## 6. 동등성 정의

`query.language`만 다른 실험군 짝 하나에 대해, 클수록 좋은 지표 `m` — `recall_at_k`, `hit_rate_at_k`, `mrr` — 각각을 이렇게 계산한다.

```text
delta_m = m_en - m_ko
ratio_m = m_ko / m_en
```

`assess_parity(en_eval, ko_eval, *, min_recall_ratio=0.85)`는 세 쌍을 모두 돌려주고, 비교 불가능한 입력은 거부한다. 다른 스위트, 다른 `k`, 다른 사례 ID 집합, 다른 채점 사례 집합, 또는 `query.language`와 그것을 인코딩한 실험군 `name` 외의 무언가에서 어긋나는 config가 그렇다.

영어 슬라이스가 0점이면 비율은 정의되지 않고, 그 경우는 **fail-closed로 실패한다**. 영어 슬라이스가 아무것도 검색하지 못한 실험군에는 주장할 동등성이 없으며, 몫 `0/0`은 죽은 실험군 둘을 묘사하면서 완벽한 일치처럼 읽힌다.

게이트는 `ratio`를 `recall_at_k`에 적용하며 바닥은 `0.85`이고 경계는 포함이다. 처리가 `routed` 또는 `translated`인 하이브리드 실험군에만 적용된다. `direct` 하이브리드 실험군은 이전 측정이고 실패가 예상된다. 이것을 게이트하면 게이트가 모듈이 드러내려고 만들어진 바로 그 실패를 보고하게 되고, 통과시키면 라우팅 변경이 측정된 적이 없다는 뜻이 된다. 해당 실험군 짝이 없는 `--gate`는 공허하게 통과하는 대신 예외를 던진다.

언어별 상시 회귀 허용 오차는 지표당 `0.05`이며 기존 `compare_against_baseline`을 통해 적용한다. 언어당 양성 사례가 24개라는 것은 한 사례가 뒤집히면 매크로 지표가 약 `0.042` 움직인다는 뜻이므로, 단일 사례 해상도 이하의 허용 오차는 게이트가 노이즈에 흔들리게 만든다. 모든 보고 표가 지표 옆에 사례 수를 함께 찍는 이유도 같다. 카테고리별 슬라이스는 보고하되 절대 게이트하지 않는다. `exact_number`는 사례가 다섯 개라 한 사례가 슬라이스의 5분의 1이다.

동등성은 함께 측정된 두 실험군 사이의 비율이므로 게이트의 절반일 뿐이다. `language_regression(baseline, current)`은 언어마다 자기 저장 기준선을 상대로 돌아간다. 한국어 슬라이스를 올리면서 영어 슬라이스를 조용히 떨어뜨려도 비율은 좋아지기 때문이다.

## 7. 비용

서로 다른 모델의 벡터는 공간을 공유하지 않으므로 공급자 실험군마다 코퍼스를 다시 임베딩한다. 실험군 하나가 청크 9,172개를 색인하며, 토큰당 4자라는 계획 근사치로 대략 270만~300만 토큰이다.

| 공급자 | 실험군당 재임베딩 | 벽시계 시간 | 참고 |
|---|---|---|---|
| `deterministic` | 없음 | 즉시 | 토큰 해시, 오프라인, 의미 주장 없음 |
| `sbert`, `sbert-multi` | 없음 | CPU에서 수 분 | `sentence-transformers`는 이미 설치된 extra다 |
| `openai` | 실행당 약 $0.06 | 수 분 | `text-embedding-3-small`, 100만 토큰당 $0.02 |

질의 쪽 비용은 무시할 수준이다. 질의 임베딩 56개에 번역 실험군의 `gpt-4.1-mini` 번역 약 24회를 더해도 합계 $0.01 미만이다. *운영* 코퍼스의 공급자를 바꾸는 것은 임베딩 비용이 같은 별개 작업이며 — `chunks.embedding`을 비우고 `embed_missing_chunks`를 다시 돌린다 — 어떤 M8 실행의 일부도 아니다.

## 8. 범위 밖

- **한국어 답변.** "한국어 질문, 한국어 검토 답변, 영어 인용"은 M4 워크플로에서 프롬프트 한 줄이지만 여기에 결정론적 지표가 없다. 이 저장소에는 LLM-as-judge가 없으므로 답변 언어 충실도는 단언만 가능하다. 이것을 출하하면 모든 주장이 측정된 숫자라는 이 모듈 자신의 논지가 깨진다. 2차 여지로 남긴다.
- **DART 또는 20-F 코퍼스.** 한국어 원문 어댑터, 문서별 언어 태그, lexical 컬럼용 한국어 텍스트 검색 구성은 2차 확장이다. 여기서 만드는 동등성 게이트가 그 코퍼스를 인수할 물건이다.
- **M2.6 cross-encoder 활성화.** 영어로 학습됐고, 모든 실험군에서 꺼져 있으며, 그 배제가 산출물 안의 사실이 되도록 `null`로 기록한다.
- **운영 라우팅 기본값.** `query_language_routing`은 `false`로 출하하고, 측정된 표도 이를 바꾸라고 요구하지 않는다. 라우팅은 OpenAI 실험군에서 한국어 사례를 하나도 뒤집지 못했고 다국어 실험군에서는 하나를 잃었다. 이것을 켜는 것은 표가 뒷받침해야 하는 결정이지 이 모듈이 내리는 결정이 아니다.

## 9. 인수 게이트

```bash
uv run pytest tests/crosslingual -q
uv run ruff check app/evals app/retrieval tests/crosslingual
uv run ruff format --check app/evals app/retrieval tests/crosslingual
uv run python scripts/check_doc_code.py docs/en/m8-crosslingual
```

오프라인 테스트 69개가 네트워크도 데이터베이스도 키도 없이 통과하고, [검증](05-verify.md)의 측정 실행이 이전 표와 이후 표를 동등성 판정과 함께 기록하면 M8은 기계적으로 완료다. 한국어 골든 사례에 대한 작성자 승인은 영어 스위트와 똑같이 별도의 수동 게이트로 남는다.
