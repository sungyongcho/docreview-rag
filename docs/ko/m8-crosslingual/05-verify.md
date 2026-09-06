# M8 검증

인수는 의존 순서대로 실행한다. 처음 실패하는 곳에서 멈춘다. 뒤의 표가 아래 계층의 계약을 고쳐 주지 못한다.

## 1. 오프라인 게이트

```bash
uv run pytest tests/crosslingual/test_01_bilingual.py -q
uv run pytest tests/crosslingual/test_02_crosslingual.py -q
uv run pytest tests/crosslingual/test_03_language.py tests/crosslingual/test_04_translate.py -q
uv run pytest tests/crosslingual/test_05_parity.py -q
uv run pytest tests/crosslingual -q
```

| 테스트 파일 | 체크포인트 | 기대 |
|---|---|---:|
| `tests/crosslingual/test_01_bilingual.py` | M8.1 | 13 passed |
| `tests/crosslingual/test_02_crosslingual.py` | M8.2 | 23 passed |
| `tests/crosslingual/test_03_language.py` | M8.3 | 15 passed |
| `tests/crosslingual/test_04_translate.py` | M8.3 | 7 passed |
| `tests/crosslingual/test_05_parity.py` | M8.4 | 11 passed |
| **`tests/crosslingual`** | M8.1–M8.4 | **69 passed** |

디렉터리 전체가 오프라인이고 결정론적이다. PostgreSQL도, 네트워크도, API 키도 없다. 이 스위트에서 skip이 나오면 외부 서비스를 쓸 수 없었다는 뜻이 아니라 정규 심벌이 없다는 뜻이다.

M8이 들어온 뒤의 저장소 전체 스위트는 이렇다.

```bash
uv run pytest -q
```

기대 결과: `959 passed, 1 skipped`. 유일한 skip은 라이브 PostgreSQL 테스트이며, 구성된 데이터베이스를 쓸 수 없거나 루프백이 아닐 때 안전하게 건너뛴다.

## 2. 스위트가 못 박는 것

- 쌍둥이 동일성: 두 스위트가 같은 사례 ID를 덮고 카테고리, 패싯, 태그, 정답, 예상 레이블, 참조 답변에서 일치하며, 번역되지 않은 복사본은 한글 규칙이 돌기 전에 거부된다(`test_01`).
- 실험군 출처: 실험군 이름이 공급자, 전략, 랭커, 처리, 언어를 인코딩하고, config 딕셔너리는 `latest_comparable_baseline`이 갈라내야 하는 모든 것을 싣는다(`test_02`).
- 가정하지 않고 측정하는 진단: 쌍둥이 정렬은 코퍼스 없이 돌며 0이 아니라 0에 가까움을 단언하고, lexical 커버리지는 비율을 단언하는 대신 빈 결과를 센다(`test_02`).
- 감지와 라우팅: 유니코드 범위 셋, 문자 혼용 질문의 한국어 분류, 빈 입력 거부, 그리고 한국어일 때 그리고 라우팅이 켜졌을 때만 생략되는 lexical 구성 요소(`test_03`).
- 번역 규율: 검증된 출력, 거부·스키마 위반·여전히 한국어인 결과에서의 fail-closed, 그리고 네트워크 공급자로 가는 경로 없음(`test_04`).
- 동등성 산술: 게이트 대상 지표별 델타와 비율, 포함 경계 바닥, 영어 슬라이스가 0일 때의 fail-closed, 비교 불가능한 짝의 거부, 단일 사례 해상도보다 큰 회귀 허용 오차(`test_05`).

## 3. 측정 실행

측정은 테스트가 아니라 언제나 커맨드라인 실행이다. M2에서 시드한 로컬 PostgreSQL이 필요하고, 임시 테이블에 자기 코퍼스를 직접 만든다. 한 번의 호출은 코퍼스를 한 번만 임베딩해 그 호출 안의 모든 실험군이 나눠 쓰므로, 공급자별로 필요한 실험군을 한꺼번에 요청할 때 행렬이 가장 싸다.

```bash
docker compose up -d db
uv run python -m app.evals.crosslingual --provider deterministic --languages en ko --strategies lexical vector hybrid --handling direct --artifact-dir data/eval_runs
uv run python -m app.evals.crosslingual --provider sbert --languages en ko --strategies vector --handling direct --artifact-dir data/eval_runs --persist-results
uv run python -m app.evals.crosslingual --provider sbert-multi --languages en ko --strategies vector hybrid --handling direct routed --artifact-dir data/eval_runs --persist-results --gate
uv run python -m app.evals.crosslingual --provider openai --languages en ko --strategies vector hybrid --handling direct routed translated --translator-model gpt-4.1-mini --artifact-dir data/eval_runs --persist-results --gate
```

기대 동작은 다음과 같다.

- 호출마다 격리된 임시 코퍼스를 하나씩 만들고 폐기한다.
- 요청된 모든 실험군을 무수정 M3 하니스를 통해 자기 언어 슬라이스에서 평가한다.
- 실행마다 사례 28개를 전부 기록하고 양성 24개만 채점한다.
- 실험군마다 타임스탬프가 붙은 원시 JSON 산출물을 하나씩 쓴다.
- 모든 config에 임베딩 공급자와 `paid_api_calls`를 정직하게 기록한다.
- 채워진 코퍼스 임베딩을 그대로 남긴다.

2026-08-27에 기록된 실행은 이 네 번의 호출로 문서 20개, 청크 9,172개의 코퍼스 위에서 산출물 22개를 썼다. 인덱싱 시간은 `deterministic` 15.28초, `openai` 59.56초, `sbert-multi` 125.08초, `sbert` 136.64초로 전부 300초 예산 안이다. 두 sentence-transformer의 시간 차이는 CPU 스케줄링에서 온 것이지 모델 크기에서 온 것이 아니며, 모델 비교가 아니다.

이 페이지에는 사례 수가 두 종류 나란히 놓여 있어 혼동하기 쉽다. 아래의 모든 품질 지표는 채점된 양성 24개 기준이고, 두 진단은 사례 28개 전체 기준이다. 정답 스팬이 없는 질문도 질의 벡터를 갖고 lexical 인덱스를 때리기 때문이다.

## 4. 이전 — 측정된 붕괴

direct 처리, 청크 목표 1200, `k=5`, `candidate_k=20`, `ts_rank_cd`, 언어당 채점된 양성 사례 24개. `deterministic` 공급자가 구조적 이전이다. 이 공급자의 벡터는 토큰 해시라, 이 표는 의미 공간이 아니라 질의 경로를 서술한다.

| 실험군 | 전략 | 언어 | 사례 | Recall@5 | Hit rate@5 | MRR | P95 ms |
|---|---|---|---:|---:|---:|---:|---:|
| `xling-deterministic-lexical-ts-rank-cd-en` | lexical | en | 24 | 0.270833 | 0.291667 | 0.171528 | 186.053 |
| `xling-deterministic-lexical-ts-rank-cd-ko` | lexical | ko | 24 | 0.000000 | 0.000000 | 0.000000 | 84.695 |
| `xling-deterministic-vector-en` | vector | en | 24 | 0.062500 | 0.083333 | 0.083333 | 27.184 |
| `xling-deterministic-vector-ko` | vector | ko | 24 | 0.000000 | 0.000000 | 0.000000 | 27.833 |
| `xling-deterministic-hybrid-ts-rank-cd-en` | hybrid | en | 24 | 0.104167 | 0.125000 | 0.097222 | 209.503 |
| `xling-deterministic-hybrid-ts-rank-cd-ko` | hybrid | ko | 24 | 0.000000 | 0.000000 | 0.000000 | 110.736 |

한국어 행은 모든 지표에서 정확히 0이다. 영어 행도 약한데, 그게 F3의 요지다. 토큰 해시 벡터는 노이즈 바닥이므로 이 표에서 정직하게 읽을 것은 영어 열이 아니라 한국어 열이다.

### 실제 임베딩 공간, direct 처리

의미를 실제로 인코딩하는 세 공간에서 돌린 같은 direct 실험군이다.

| 실험군 | 전략 | 언어 | 사례 | Recall@5 | Hit rate@5 | MRR | P95 ms |
|---|---|---|---:|---:|---:|---:|---:|
| `xling-openai-vector-en` | vector | en | 24 | 0.375000 | 0.375000 | 0.300000 | 203.673 |
| `xling-openai-vector-ko` | vector | ko | 24 | 0.208333 | 0.208333 | 0.131944 | 182.466 |
| `xling-openai-hybrid-ts-rank-cd-en` | hybrid | en | 24 | 0.395833 | 0.416667 | 0.362500 | 346.982 |
| `xling-openai-hybrid-ts-rank-cd-ko` | hybrid | ko | 24 | 0.208333 | 0.208333 | 0.105556 | 292.065 |
| `xling-sbert-multi-vector-en` | vector | en | 24 | 0.125000 | 0.125000 | 0.097222 | 41.798 |
| `xling-sbert-multi-vector-ko` | vector | ko | 24 | 0.208333 | 0.208333 | 0.107639 | 43.888 |
| `xling-sbert-multi-hybrid-ts-rank-cd-en` | hybrid | en | 24 | 0.229167 | 0.250000 | 0.168056 | 227.325 |
| `xling-sbert-multi-hybrid-ts-rank-cd-ko` | hybrid | ko | 24 | 0.250000 | 0.250000 | 0.114583 | 129.579 |
| `xling-sbert-vector-en` | vector | en | 24 | 0.416667 | 0.416667 | 0.277778 | 37.023 |
| `xling-sbert-vector-ko` | vector | ko | 24 | 0.125000 | 0.125000 | 0.063889 | 39.815 |

어떤 개선을 논하기 전에 이 표에서 읽어야 할 것이 셋이다. 영어 전용 `all-MiniLM-L6-v2`가 측정된 모든 실험군 중 영어 벡터 recall이 가장 높아 0.416667로 OpenAI 실험군의 0.375000을 넘는다. 교차 언어 취약성은 벡터 공간의 성질이지 모델 품질에 대한 판정이 아니다. 다국어 sentence-transformer는 두 실험군 모두에서 영어보다 한국어 점수가 *높은데*, 이것만으로도 ko/en 비율이 품질 척도가 아님이 드러난다. 그리고 OpenAI 하이브리드 실험군은 행렬에서 가장 강한 영어 실험군이면서 한국어 슬라이스는 그 절반에 앉아 있다. 이 페이지의 나머지가 다루는 격차가 바로 그것이다.

### 쌍둥이 질의 정렬

각 한국어 질의 벡터와 영어 쌍둥이 사이 코사인의 평균, 최솟값, 최댓값. 짝 28개, 코퍼스도 데이터베이스도 없음.

| 공급자 | 모델 | 짝 | 평균 코사인 | 최소 코사인 | 최대 코사인 |
|---|---|---:|---:|---:|---:|
| `deterministic` | `token-hash-384` | 28 | 0.103210 | −0.048113 | 0.316228 |
| `sbert` | `all-MiniLM-L6-v2` | 28 | 0.339279 | −0.034543 | 0.750546 |
| `openai` | 384차원의 `text-embedding-3-small` | 28 | 0.568644 | 0.329923 | 0.861984 |
| `sbert-multi` | `paraphrase-multilingual-MiniLM-L12-v2` | 28 | 0.811329 | 0.634176 | 0.913633 |

이 순서는 청크를 하나도 인덱싱하기 전에 보이며, 위 벡터 실험군들의 ko/en 비율 순서를 예측한다. deterministic 행은 따로 읽어야 한다. 최댓값이 정확히 0.316228, 즉 1/√10인데, 이것은 공유된 의미가 아니라 384차원에서 일어나는 해시 충돌의 서명이다. 구조적 0 위에 충돌 노이즈가 얹힌 값이므로 0.3162를 의미 신호로 보고해서는 안 된다.

### lexical 후보 커버리지

영어 `to_tsvector('english')` 인덱스가 `candidate_k=20`에서 아무것도 돌려주지 않는 빈도. 언어별, 사례 28개 전체 기준. 이 숫자는 질문 텍스트와 영어 인덱스에만 의존하므로 네 번의 호출에서 전부 동일했다.

| 언어 | 사례 | 후보 0건 사례 | 후보 0건 비율 | 평균 후보 수 |
|---|---:|---:|---:|---:|
| en | 28 | 0 | 0.000000 | 20.00 |
| ko | 28 | 4 | 0.142857 | 16.82 |

한국어 비율은 가정된 100%가 아니라 측정값이다. 한국어 질문 안의 라틴 토큰 — 티커, 공정 노드, 회계연도 — 은 여전히 영어 인덱스에 매칭된다. 아무것도 돌려주지 않는 한국어 질문은 넷뿐이다. `m3c-13`과 `m3c-21`에는 라틴 문자가 아예 없고, `m3c-08`은 연도를 `2019년`으로 적어 숫자가 홀로 된 렉심이 되지 못하며, `m3c-18`이 싣고 있는 `CAC`는 코퍼스에 나오지 않는다.

나머지 한국어 질문 24개는 후보 20개 중 평균 16.82개를 받는데, 한국어 lexical recall@5는 여전히 0.000000이다. **이것이 발견이다. 한국어에서 lexical 구성 요소는 침묵하는 것이 아니라 자신 있게 틀린다.** 아무것도 돌려주지 않는 구성 요소는 `ComponentRankings.lexical`에서 보이지만, 무관한 청크 스무 개를 돌려주는 구성 요소는 정상 동작한 구성 요소와 똑같이 보인다.

### 카테고리별 실패 분석

OpenAI direct 하이브리드 실험군을 무수정 `breakdown_by_category`로 골든 카테고리별로 자르고 렌더링 시점에 조인한 것이다.

| 실험군 | 언어 | 카테고리 | 사례 | Recall@5 | Hit rate@5 | MRR |
|---|---|---|---:|---:|---:|---:|
| `xling-openai-hybrid-ts-rank-cd-en` | en | `simple_lookup` | 13 | 0.653846 | 0.692308 | 0.630769 |
| `xling-openai-hybrid-ts-rank-cd-en` | en | `exact_number` | 5 | 0.000000 | 0.000000 | 0.000000 |
| `xling-openai-hybrid-ts-rank-cd-en` | en | `multi_hop` | 6 | 0.166667 | 0.166667 | 0.083333 |
| `xling-openai-hybrid-ts-rank-cd-ko` | ko | `simple_lookup` | 13 | 0.307692 | 0.307692 | 0.156410 |
| `xling-openai-hybrid-ts-rank-cd-ko` | ko | `exact_number` | 5 | 0.000000 | 0.000000 | 0.000000 |
| `xling-openai-hybrid-ts-rank-cd-ko` | ko | `multi_hop` | 6 | 0.166667 | 0.166667 | 0.083333 |

카테고리 슬라이스는 보고하되 절대 게이트하지 않는다. `exact_number`는 사례가 다섯 개라 한 사례가 뒤집히면 슬라이스가 0.2 움직인다.

교차 언어 격차는 전부 `simple_lookup`에 산다. `multi_hop`은 이미 두 언어가 같은 점수이고, `exact_number`는 이 페이지의 모든 실험군에서, 두 언어 모두에서, 모든 공급자에서 0.000000이다. **`exact_number`는 이 모듈이 측정은 하되 원인은 아닌 영어 쪽 검색 공백이다. 이것을 언어 탓으로 돌리면 거짓 교차 언어 발견이 된다.**

## 5. 이후 — 라우팅과 번역

하이브리드 전략만 다룬다. 라우팅과 번역은 두 구성 요소가 모두 도는 곳에서만 의미가 있기 때문이다.

| 실험군 | 처리 | 언어 | 사례 | Recall@5 | Hit rate@5 | MRR | P95 ms |
|---|---|---|---:|---:|---:|---:|---:|
| `xling-openai-hybrid-ts-rank-cd-routed-en` | routed | en | 24 | 0.395833 | 0.416667 | 0.362500 | 349.120 |
| `xling-openai-hybrid-ts-rank-cd-routed-ko` | routed | ko | 24 | 0.208333 | 0.208333 | 0.131944 | 170.274 |
| `xling-openai-hybrid-ts-rank-cd-translated-en` | translated | en | 24 | 0.395833 | 0.416667 | 0.362500 | 4086.188 |
| `xling-openai-hybrid-ts-rank-cd-translated-ko` | translated | ko | 24 | 0.395833 | 0.416667 | 0.336806 | 2934.909 |
| `xling-sbert-multi-hybrid-ts-rank-cd-routed-en` | routed | en | 24 | 0.229167 | 0.250000 | 0.168056 | 223.994 |
| `xling-sbert-multi-hybrid-ts-rank-cd-routed-ko` | routed | ko | 24 | 0.208333 | 0.208333 | 0.107639 | 44.547 |

### 개선 사이클 델타

세 질의 경로를 가로지른 OpenAI 하이브리드 실험군의 한국어 슬라이스와, 사이클이 주장하는 변화다.

| 지표 | KO direct | KO routed | KO translated | direct 대비 최선 델타 |
|---|---:|---:|---:|---:|
| `recall_at_k` | 0.208333 | 0.208333 | 0.395833 | +0.187500 |
| `hit_rate_at_k` | 0.208333 | 0.208333 | 0.416667 | +0.208333 |
| `mrr` | 0.105556 | 0.131944 | 0.336806 | +0.231250 |

**라우팅은 한국어를 고치지 못했고, 설계는 고칠 것으로 기대했다.** OpenAI 실험군에서 라우팅은 사례를 하나도 뒤집지 못했다. 한국어 recall과 hit rate는 소수 여섯째 자리까지 그대로이고, 움직인 것은 MRR뿐이다. 0.105556에서 0.131944로 오른 이유는 틀린 lexical 목록을 버리자 이미 찾아둔 청크 둘이 올라왔기 때문이다(`m3c-11`은 2위에서 1위로, `m3c-23`은 5위에서 3위로). 커버리지 표가 예측한 그대로다. 버릴 것이 없었던 한국어 질문은 28개 중 4개뿐이므로, lexical 실험군을 제거하면 순위 왜곡이 사라질 뿐 검색 실패는 사라지지 않는다. 한국어의 약점은 벡터 쪽에 살고, 그것을 움직이는 것은 번역이다.

번역은 recall과 hit rate 비율에서 정확히 1.000000에 닿으며, 영어가 맞히는 `simple_lookup` 사례 다섯을 그대로 되찾고 그 이상은 없다. MRR 비율은 1.0이 아니라 0.929119다. 맞힌 *집합*은 영어와 동일하지만 *순위*가 다르다(`m3c-08`은 1위에서 4위로, `m3c-11`은 2위에서 3위로, `m3c-13`은 5위에서 2위로). 여기서 동등성은 같은 문서를 찾는다는 뜻이지 같은 순서라는 뜻이 아니다. 대가는 지연이다. 이제 모든 한국어 질의가 LLM 호출을 기다리므로 P95가 292ms에서 2,935ms로 오른다.

그 대가로 영어 슬라이스가 움직여서는 안 되고, 실제로 움직이지 않는다.

| 지표 | EN direct | EN routed | EN translated | 이동 |
|---|---:|---:|---:|---:|
| `recall_at_k` | 0.395833 | 0.395833 | 0.395833 | 0.000000 |
| `hit_rate_at_k` | 0.416667 | 0.416667 | 0.416667 | 0.000000 |
| `mrr` | 0.362500 | 0.362500 | 0.362500 | 0.000000 |

라우팅은 한글에서만 발화하고, 번역기는 영어에 대해 검증된 무동작이다. 영어 질의 28개가 전부 바이트 단위로 동일하게 돌아왔고 `source_language`도 영어로 보고되었다. 번역된 영어 실험군이 direct 실험군을 그대로 재현하는 이유가 이것이다. 이 실행들은 이 데이터베이스에서 `m8-crosslingual-v1`의 첫 실행이라 영속화된 모든 행이 기준선 null, 비교 null을 보고한다. 이 실행 자체가 기준선이고, 지표당 0.05 회귀 허용 오차는 다음 실행부터 지키기 시작한다.

## 6. 동등성 판정

게이트 대상 지표는 `recall_at_k`이고 바닥은 0.85, 경계는 포함이며, 처리가 `routed` 또는 `translated`인 하이브리드 실험군에 적용된다. `direct` 행은 대조를 위해 찍되 게이트하지 않는다.

| 실험군 짝 | 처리 | 사례 | Recall@5 EN | Recall@5 KO | 델타 | 비율 | 게이트 | 판정 |
|---|---|---:|---:|---:|---:|---:|---|---|
| `xling-openai-hybrid-ts-rank-cd` | direct | 24 | 0.395833 | 0.208333 | 0.187500 | 0.526316 | 아니오 | 이전 측정 |
| `xling-openai-hybrid-ts-rank-cd-routed` | routed | 24 | 0.395833 | 0.208333 | 0.187500 | 0.526316 | 예 | FAIL |
| `xling-openai-hybrid-ts-rank-cd-translated` | translated | 24 | 0.395833 | 0.395833 | 0.000000 | 1.000000 | 예 | PASS |
| `xling-sbert-multi-hybrid-ts-rank-cd` | direct | 24 | 0.229167 | 0.250000 | −0.020833 | 1.090909 | 아니오 | 이전 측정 |
| `xling-sbert-multi-hybrid-ts-rank-cd-routed` | routed | 24 | 0.229167 | 0.208333 | 0.020833 | 0.909091 | 예 | PASS |

```bash
uv run python -m app.evals.crosslingual --provider openai --languages en ko --strategies hybrid --handling routed translated --gate
echo "exit: $?"
```

전체 게이트는 게이트 대상 실험군들에 대한 논리곱이므로 이 커맨드는 1로 종료한다. 번역 실험군은 통과하고 라우팅 실험군이 비율 0.526316에서 실패하기 때문이다. 라우팅 실험군만 있는 `sbert-multi` 실행은 0으로 종료한다.

종료 코드 0이 동등성 주장이다. 0이 아닌 종료는 비율이 바닥 아래로 떨어졌거나 영어 슬라이스가 0점이라 비율이 정의되지 않았다는 뜻이다. 둘 다 실패이고, 어느 쪽도 통과로 보고할 수 없다. 종료 코드 0 옆에 붙여둘 주의가 하나 더 있다. 페이로드에 게이트 대상 실험군이 하나도 없을 때도 `gate.passed`는 `true`인데, 빈 목록에 대한 논리곱은 공허하게 참이기 때문이다. 게이트 가능한 짝 없이는 실행을 거부하는 `--gate`만이 종료 코드에 의미를 준다.

**비율은 더 나빠지는 방식으로도 통과될 수 있다.** `sbert-multi` 라우팅 실험군은 0.909091로 0.85 바닥을 넘지만, 그 영어 recall 0.229167은 이 페이지에서 가장 약한 영어 하이브리드 숫자다. OpenAI 실험군의 0.395833보다 낮고 영어 전용 sentence-transformer의 0.416667보다도 낮다. 벡터 실험군에서는 비율이 1.666667로 한국어가 영어를 앞선다. 비율은 두 슬라이스가 함께 내려앉은 것을 전혀 알아채지 못한다. `language_regression`이 존재하는 이유가 이것이고, 게이트의 두 절반이 선택 사항이 아닌 이유가 이것이다. 라우팅도 공짜가 아니다. 비율을 올린 그 `sbert-multi` 라우팅이 `m3c-16`을 *잃었다*. 이 한국어 질문은 `GDDR6`와 `GDDR6X`를 라틴 문자로 담고 있었고, 그것은 진짜 lexical 신호였는데 라우트가 통째로 버렸다. 맞힌 집합은 6개에서 5개로, recall은 0.250000에서 0.208333으로 내려갔다.

## 7. 비용과 출처

이 페이지의 무료 게이트는 `--provider sbert-multi --handling routed`다. CPU에서 돌고 LLM 호출을 하지 않으며 0으로 종료한다. 동시에 바로 위 절이 경고하는 실험군이기도 하므로, 출하 주장을 재현하려는 실행에는 유료 경로가 필요하다.

```bash
OPENAI_API_KEY="your-key" uv run python -m app.evals.crosslingual --provider openai --languages en ko --strategies vector hybrid --handling direct routed
OPENAI_API_KEY="your-key" uv run python -m app.evals.crosslingual --provider openai --languages en ko --strategies hybrid --handling translated --translator-model gpt-4.1-mini
```

기록된 OpenAI 세션의 총비용은 약 $0.05이고 상한은 $0.06이다. 청크 9,172개, 토큰 약 200만 개의 코퍼스 임베딩 한 번이 $0.038에서 $0.044, 질의 임베딩 224건이 $0.001 미만, `gpt-4.1-mini` 번역 호출 56건이 약 $0.008이다. OpenAI 실험군 여덟 개가 임시 코퍼스 세션 하나를 공유했으므로 코퍼스 임베딩 비용은 한 번만 지불되었다. 번역기는 두 언어 모두에 대해 각각 28회 돌았는데, 동등성 짝이 번역된 영어 실험군도 요구하기 때문이다. 번역된 질의는 모두 실행 페이로드에 기록되므로 — 그 페이로드에 사례 ID가 없어 질문 텍스트로 조인해야 하지만 — 보고된 번역 숫자는 사례 단위로 다시 읽을 수 있다. 게이트 실행은 결정론적 경로를 쓰고, 측정된 번역 실행은 보고하되 기준선으로 삼지 않는다.

한국어 골든 검토는 별도의 수동 게이트로 남는다. 쌍둥이 계약의 기계 검증은 어떤 사례도 사람이 검증한 것으로 만들지 않는다.

## 8. 실패 분류

| 증상 | 유력한 경계 | 첫 조치 |
|---|---|---|
| 중복 span에 대한 `GoldenDataError` | M8.1 적재 | 두 스위트를 디렉터리가 아니라 파일 두 개로 적재한다 |
| 필드를 지목하는 `TwinCaseError` | M8.1 쌍둥이 | 한국어 사례를 영어 사례에 맞춘다. 불변 필드 목록은 절대 완화하지 않는다 |
| 동등성이 "arms must differ only in query language"를 던짐 | M8.2 config | 양쪽 config의 `embedding.model`과 `query.handling`을 확인한다 |
| 한국어 후보 0건 비율이 기대보다 낮음 | M8.2 진단 | 매칭된 렉심을 읽는다. 한국어 질문 안의 라틴 토큰은 예상된 것이다 |
| routed 실험군이 테스트에서 실제 세션에 닿음 | M8.3 처리 | routed는 `retrieve`를 직접 호출한다. 가짜로 만들 대상은 `retrieve`이며 `make_retriever`가 아니다 |
| 모든 사례에서 `QueryTranslationError` | M8.3 번역 | 공급자 예산과 스키마를 확인한다. 이 실험군은 폴백하면 안 된다 |
| 비율이 `undefined`로 보고됨 | M8.4 동등성 | 영어 슬라이스가 0점이다. 한국어를 읽기 전에 영어 실험군을 고친다 |
| `--gate`가 심판하지 않고 예외를 던짐 | M8.4 게이트 | 행렬에 두 언어 모두를 가진 `routed` 또는 `translated` 하이브리드 짝이 없다 |
