# M8.4 튜토리얼 4 — 동등성 주장에는 바닥과 허용 오차와 판정이 필요하다

"한국어도 됩니다"는 누구도 확인할 수 없는 주장이다. **정의된 비율도, 바닥도, 허용 오차도 없는 동등성 진술은 조용히 회귀한다. 이름 붙인 적 없는 숫자를 지켜보는 것은 시스템 어디에도 없기 때문이다.** 이 문서는 비율을 정의하고, 무언가를 고쳤다고 주장하는 실험군에 그것을 게이트로 걸고, 그다음 루프를 공개적으로 한 번 돈다. 기준선, 실패 분석, 변경, 재측정, 델타 표다.

**선행 조건:** M8.3 완료, `uv run pytest tests/crosslingual/test_03_language.py tests/crosslingual/test_04_translate.py -q` 통과.

### 무엇을 정의하고, 무엇을 구현하고, 무엇을 들여다볼 것인가

| 영역 | 학습 행동 | 가져갈 것 |
|---|---|---|
| 임곗값들 | 상수를 **작성한다** | 단일 사례 해상도 아래의 허용 오차는 노이즈다 |
| `ParityMetric`, `ParityAssessment` | 값 객체를 **작성한다** | 정의되지 않은 비율은 `None`이지 결코 `1.0`이 아니다 |
| `assess_parity` | 비교를 **구현한다** | 비교 가능성은 산술보다 먼저 검사된다 |
| `parity_pairs`, `gated_assessments` | 선택을 **구현한다** | 게이트는 실패가 아니라 수정을 심판한다 |
| 개선 사이클 | 측정을 **돌린다** | 산출물은 델타 표다 |

### 1. 임곗값을 정하는 숫자들

#### `app/evals/parity.py` 생성 — 상수

**학습 행동 — 상수를 작성한다:** 이 스위트의 단일 사례 해상도를 먼저 계산한 다음 허용 오차를 고른다.

<!-- src: app/evals/parity.py::DEFAULT_MIN_RECALL_RATIO,PARITY_REGRESSION_TOLERANCE,GATED_METRIC -->
```python
DEFAULT_MIN_RECALL_RATIO: Final[float] = 0.85

# One positive case out of 24 moves a macro metric by about 0.042. A tolerance below
# that would let a single flipped case fail the gate, so the standing per-language
# regression allowance sits deliberately above single-case granularity.
PARITY_REGRESSION_TOLERANCE: Final[float] = 0.05

GATED_METRIC: Final[MetricName] = "recall_at_k"
```

**코드에서 꼭 볼 것**

- 언어당 채점된 양성이 24개라는 것은 한 사례가 매크로 지표의 약 0.042 값어치라는 뜻이다. **그 값 이하의 허용 오차는 뒤집힌 사례 하나가 게이트를 흔들게 하고, 그러면 모두가 게이트를 무시하도록 훈련된다.** 0.05는 의도적으로 그 위에 놓인다.
- 게이트 대상 지표는 셋이 아니라 하나다. recall은 이 모듈이 하는 주장이고, hit rate와 MRR은 독자가 recall이 *어떻게* 움직였는지 볼 수 있도록 보고한다. 셋을 다 게이트하면 추가 정보 없이 흔들림 면적만 세 배가 된다.
- 카테고리별 슬라이스를 절대 게이트하지 않는 이유도 같다. `exact_number`는 사례가 다섯 개라 한 사례가 슬라이스의 5분의 1이다.

### 2. 정의되지 않음은 1이 아니다

#### `app/evals/parity.py` 확장 — 값 객체

**학습 행동 — 값 객체를 작성한다:** 산술을 쓰기 전에 `ratio`의 타입을 정한다.

<!-- src: app/evals/parity.py::ParityMetric,ParityAssessment -->
```python
@dataclass(frozen=True, slots=True)
class ParityMetric:
    """One metric measured on both language slices of the same arm."""

    metric: MetricName
    en: float
    ko: float
    delta: float
    ratio: float | None


@dataclass(frozen=True, slots=True)
class ParityAssessment:
    """The complete cross-language verdict for one arm pair."""

    suite: str
    k: int
    case_count: int
    min_recall_ratio: float
    metrics: tuple[ParityMetric, ...]
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return whether the gated ratio cleared its floor."""
        return not self.failures

    def metric(self, name: MetricName) -> ParityMetric:
        """Return one measured metric pair by name."""
        for result in self.metrics:
            if result.metric == name:
                return result
        raise KeyError(name)

    @property
    def recall_ratio(self) -> float | None:
        """Return the gated ko/en recall ratio, or None when the English slice is 0."""
        return self.metric(GATED_METRIC).ratio
```

**코드에서 꼭 볼 것**

- `ratio: float | None`이다. **`0/0`을 `1.0`으로 강제 변환하면 아무것도 검색하지 못한 두 실험군을 묘사하면서 "두 언어가 완벽히 일치한다"로 읽힌다** — 타입이 그것을 표현하기를 거부한다.
- `passed`는 저장되지 않고 `failures`에서 파생된다. 이유와 독립적으로 설정될 수 있는 판정은 틀릴 수 있는 판정이다.
- `case_count`가 평가 결과와 함께 다니므로, 렌더링된 표는 언제나 비율 옆에 `n`을 찍을 수 있다.

### 3. 산술보다 비교 가능성이 먼저다

#### `app/evals/parity.py` 확장 — 비교

**학습 행동 — 비교를 구현한다:** 비율이 의미를 갖기 전에 무엇이 일치해야 하는지 전부 나열하고, 그 검사들을 먼저 쓴다.

<!-- src: app/evals/parity.py::assess_parity -->
```python
def assess_parity(
    en_eval: RetrievalEvaluation,
    ko_eval: RetrievalEvaluation,
    *,
    min_recall_ratio: float = DEFAULT_MIN_RECALL_RATIO,
) -> ParityAssessment:
    """Compare two evaluations that differ only in query language.

    For each higher-is-better metric the assessment records ``delta = en - ko`` and
    ``ratio = ko / en``. The ratio is the claim the module makes — "Korean retrieves
    at least this fraction of what English retrieves" — and the delta is what the
    per-language regression gate watches over time.

    The ratio is undefined when the English slice scores 0, and that case fails
    closed. An arm whose English slice retrieves nothing has no parity to claim: the
    quotient 0/0 would read as perfect agreement while describing two dead arms.

    The two evaluations must be the same suite, the same ``k``, over the same case
    ids, under configs that agree on everything except ``query.language`` and the arm
    ``name`` that encodes it. Without that check a Korean run could be silently
    compared against an English run of a different provider or chunking, and the
    ratio would measure the wrong difference.
    """
    if not isinstance(en_eval, RetrievalEvaluation) or not isinstance(ko_eval, RetrievalEvaluation):
        raise TypeError("parity requires two RetrievalEvaluation values")
    if not math.isfinite(min_recall_ratio) or not 0.0 < min_recall_ratio <= 1.0:
        raise ValueError("min_recall_ratio must be in (0, 1]")
    if en_eval.suite != ko_eval.suite:
        raise ValueError("parity requires both evaluations to share one suite")
    if en_eval.score.k != ko_eval.score.k:
        raise ValueError("parity requires both evaluations to use the same k")

    en_ids, en_scored = _case_ids(en_eval)
    ko_ids, ko_scored = _case_ids(ko_eval)
    if en_ids != ko_ids or en_scored != ko_scored:
        raise ValueError("parity requires both evaluations to cover the same golden cases")
    if _config_identity(en_eval.config, "en") != _config_identity(ko_eval.config, "ko"):
        raise ValueError("parity arms must differ only in query language")

    en_values = en_eval.metric_values()
    ko_values = ko_eval.metric_values()
    metrics: list[ParityMetric] = []
    failures: list[str] = []
    for name in HIGHER_IS_BETTER_METRICS:
        english = en_values[name]
        korean = ko_values[name]
        ratio = None if english == 0.0 else korean / english
        metrics.append(
            ParityMetric(
                metric=name,
                en=english,
                ko=korean,
                delta=english - korean,
                ratio=ratio,
            )
        )
        if name != GATED_METRIC:
            continue
        if ratio is None:
            failures.append(f"{name}: English slice scored 0, so parity is undefined")
        elif ratio < min_recall_ratio and not math.isclose(
            ratio,
            min_recall_ratio,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            failures.append(f"{name}: ratio {ratio:.6f} is below the floor {min_recall_ratio:.6f}")

    return ParityAssessment(
        suite=en_eval.suite,
        k=en_eval.score.k,
        case_count=en_eval.score.case_count,
        min_recall_ratio=min_recall_ratio,
        metrics=tuple(metrics),
        failures=tuple(failures),
    )
```

**코드에서 꼭 볼 것**

- 나눗셈 한 번보다 먼저 비교 가능성 검사 다섯 개가 돈다. **그것들이 없으면 한국어 실행이 다른 공급자나 다른 청킹의 영어 실행으로 나뉠 수 있고, 그 비율은 엉뚱한 차이를 재는 진짜 숫자가 된다.**
- `_config_identity`는 `name`과 `query.language`를 떼어 내고 나머지 전부가 일치하기를 요구한다. M8.2의 config 계약이 완전해야 했던 이유가 이것이다.
- 바닥은 `math.isclose`로 경계를 포함하며, `app/evals/regression.py`가 허용 오차에 이미 쓰는 관례와 같다.
- 게이트 대상이 하나뿐인데도 델타와 비율을 세 지표 모두에 기록한다. 게이트되지 않는 쌍이 "한국어가 더 적은 span을 찾았다"와 "한국어가 그것들을 더 아래에서 찾았다"를 구분해 주는 방법이다.

동등성은 함께 측정된 두 실험군 사이의 비율이므로 게이트의 절반일 뿐이다. `language_regression`은 언어마다 자기 저장 기준선을 상대로 0.05 허용 오차에서 돈다. **한국어 슬라이스를 올리면서 영어 슬라이스를 조용히 떨어뜨려도 비율은 좋아지기 때문이다.**

### 4. 게이트는 실패가 아니라 수정을 심판한다

#### `app/evals/crosslingual.py` 확장 — 짝짓기와 선택

**학습 행동 — 선택을 구현한다:** 게이트를 `direct` 실험군에 겨누면 무슨 일이 벌어지는지 물어본다.

<!-- src: app/evals/crosslingual.py::parity_pairs,gated_assessments -->
```python
def parity_pairs(
    runs: Sequence[LanguageRun],
    *,
    min_recall_ratio: float = DEFAULT_MIN_RECALL_RATIO,
) -> tuple[tuple[CrosslingualArm, ParityAssessment], ...]:
    """Assess parity for every arm that was measured in both languages."""
    by_identity: dict[tuple[str, str, str | None], dict[str, LanguageRun]] = {}
    for run in runs:
        identity = (run.arm.strategy, run.arm.handling, run.arm.lexical_ranker)
        by_identity.setdefault(identity, {})[run.arm.language] = run
    assessments: list[tuple[CrosslingualArm, ParityAssessment]] = []
    ordered = sorted(
        by_identity,
        key=lambda key: (STRATEGY_ORDER[key[0]], HANDLING_ORDER[key[1]], key[2] or ""),
    )
    for identity in ordered:
        slices = by_identity[identity]
        if set(slices) != {"en", "ko"}:
            continue
        assessments.append(
            (
                slices["ko"].arm,
                assess_parity(
                    slices["en"].evaluation,
                    slices["ko"].evaluation,
                    min_recall_ratio=min_recall_ratio,
                ),
            )
        )
    return tuple(assessments)


def gated_assessments(
    assessments: Sequence[tuple[CrosslingualArm, ParityAssessment]],
) -> tuple[tuple[CrosslingualArm, ParityAssessment], ...]:
    """Select the shipping arms whose parity the gate is allowed to judge.

    Only a hybrid arm with language-aware handling can claim parity. The direct arm
    is the "before" measurement — gating it would make the gate report the very
    failure the module was built to expose, and passing it would mean the routing
    change had not been measured at all.
    """
    return tuple(
        (arm, assessment)
        for arm, assessment in assessments
        if arm.strategy == "hybrid" and arm.handling != "direct"
    )
```

**코드에서 꼭 볼 것**

- `parity_pairs`는 두 언어에서 측정된 것을 전부 평가하고, `gated_assessments`는 게이트가 심판해도 되는 것으로 좁힌다. 보고와 게이트를 나눈 것은 의도적이다. `direct` 행은 모든 표에 계속 보이되 빌드를 실패시키지 못한다.
- **`direct` 실험군을 게이트하면 게이트가 모듈이 드러내려고 만들어진 바로 그 실패를 보고하게 되고, 통과시키면 변경이 측정된 적이 없다는 뜻이 된다.** 어느 쪽도 게이트가 아니다.
- routed 또는 translated 짝이 없는 `--gate`는 0으로 종료하는 대신 예외를 던진다. 심판할 것을 찾지 못해서 통과하는 게이트는 게이트가 없느니만 못하다.

### 5. 개선 사이클, 한 번, 공개적으로

이 부분이 이 모듈을 리포트가 아니라 루프로 만든다. 아래의 측정 칸은 전부 [검증](../05-verify.md)에 기록된 실행, 그중에서도 세 질의 경로를 끝까지 측정한 `openai` 공급자에서 채운다.

#### 1단계 — 기준선

```bash
uv run python -m app.evals.crosslingual --provider openai --languages en ko --strategies vector hybrid --handling direct
```

| 슬라이스 | 사례 | Recall@5 | Hit rate@5 | MRR |
|---|---:|---:|---:|---:|
| en | 24 | 0.395833 | 0.416667 | 0.362500 |
| ko | 24 | 0.208333 | 0.208333 | 0.105556 |
| 비율 (ko/en) | 24 | 0.526316 | 0.500000 | 0.291188 |

#### 2단계 — 실패 분석

집계가 아니라 카테고리 슬라이스와 진단을 읽는다. lexical 커버리지 실행은 후보가 0건인 한국어 사례 4개를 보고하며, 그 ID는 `zero_candidate_case_ids`에 있다.

| 카테고리 | 사례 | KO recall@5 | EN recall@5 | 격차 |
|---|---:|---:|---:|---:|
| `simple_lookup` | 13 | 0.307692 | 0.653846 | 0.346154 |
| `exact_number` | 5 | 0.000000 | 0.000000 | 0.000000 |
| `multi_hop` | 6 | 0.166667 | 0.166667 | 0.000000 |

격차 전체가 카테고리 하나에 있다. `multi_hop`은 이미 두 언어가 같은 점수이고, `exact_number`는 **양쪽** 모두 0점이라 교차 언어 발견이 아니라 이 실행이 마침 드러낸 영어 쪽 검색 공백이다. 이것을 교차 언어 발견으로 읽는 것이 이 페이지에서 가장 빠지기 쉬운 거짓 결론이다.

가장 나쁜 한국어 카테고리의 산출물을 열고 사례 하나의 원시 히트를 읽는다. 답해야 할 질문은 상위 5개를 어느 구성 요소가 만들었는가이고, 측정된 답은 뻔한 추측과 어긋난다. 한국어 lexical 구성 요소는 침묵하지 *않았다*. 한국어 질문 28개 중 아무것도 돌려주지 않은 것은 4개뿐이고, 나머지 24개는 후보 20개 중 평균 16.82개를 받았는데도 한국어 lexical recall@5는 0.000000이었다. **융합을 망치는 구성 요소는 아무 말도 하지 않는 쪽이 아니라 자신 있게 틀린 답을 하는 쪽인 경우가 대부분이다.**

#### 3단계 — 변경한 뒤 재측정

```bash
uv run python -m app.evals.crosslingual --provider openai --languages en ko --strategies hybrid --handling direct routed translated --translator-model gpt-4.1-mini
```

| 처리 | KO recall@5 | KO hit rate@5 | KO MRR | 비율 (recall) |
|---|---:|---:|---:|---:|
| direct | 0.208333 | 0.208333 | 0.105556 | 0.526316 |
| routed | 0.208333 | 0.208333 | 0.131944 | 0.526316 |
| translated | 0.395833 | 0.416667 | 0.336806 | 1.000000 |

**라우팅은 한국어를 고치지 못했다.** 사례를 하나도 뒤집지 못해 recall과 hit rate는 소수 여섯째 자리까지 그대로이고, 틀린 lexical 목록을 버리자 이미 찾아둔 청크 둘이 올라오면서 MRR만 0.105556에서 0.131944로 움직였다. 2단계에서 곧바로 따라 나오는 결과다. 질문 28개 중 4개에서만 완전히 실패한 구성 요소를 버리면 순위 왜곡이 사라질 뿐 검색 실패는 사라지지 않는다. 격차를 닫는 것은 번역이고, 정확히 닫는다. 영어가 맞히는 `simple_lookup` 사례 다섯 그대로이며 그 이상은 없다. recall과 hit rate 비율이 1.000000인데 MRR 비율이 0.929119인 이유는 같은 문서가 다른 순위로 돌아오기 때문이다.

#### 4단계 — 판정

```bash
uv run python -m app.evals.crosslingual --provider openai --languages en ko --strategies hybrid --handling routed translated --gate
echo "exit: $?"
```

| 게이트 대상 실험군 | 비율 (recall) | 바닥 | 판정 |
|---|---:|---:|---|
| `xling-openai-hybrid-ts-rank-cd-routed-ko` | 0.526316 | 0.85 | FAIL |
| `xling-openai-hybrid-ts-rank-cd-translated-ko` | 1.000000 | 0.85 | PASS |

이 커맨드는 1로 종료한다. 전체 게이트가 게이트 대상 실험군들에 대한 논리곱인데 라우팅 실험군이 바닥 아래이기 때문이다. 그것이 사이클이 작동하는 모습이다. 설계가 성공을 기대했던 변경이 실험군으로 들어가 측정되었고, 넘어야 할 게이트에 의해 기각되었다.

**통과한 비율이 자동으로 좋은 소식인 것은 아니다.** 같은 게이트를 `sbert-multi`에서 돌리면 비율 0.909091로 0으로 종료한다. 그런데 그 실험군의 영어 recall은 0.229167로 행렬에서 가장 약한 영어 하이브리드 숫자이고, 벡터 실험군은 비율 1.666667로 한국어가 영어보다 *위*에 있다. 비율은 "한국어가 따라잡았다"와 "영어가 내려앉았다"를 구별하지 못한다. `language_regression`이 그 옆에서 함께 도는 이유가 전부 이것이다. 그 라우팅은 `m3c-16`도 잃었다. 이 한국어 질문은 `GDDR6`와 `GDDR6X`를 라틴 문자로 담고 있었고, 한국어 질의에는 lexical 신호가 없다고 가정한 라우트가 진짜 신호를 통째로 버렸다.

**산출물은 델타 표다.** 그 옆의 문장은 해설이고, 둘이 어긋나면 옳은 쪽은 표다.

### 집중 테스트와 그것이 지키는 계약

```bash
uv run pytest tests/crosslingual/test_05_parity.py -q
```

기대 결과: `11 passed`.

| 테스트가 깨뜨리는 것 | 지키는 계약 |
|---|---|
| 0점을 받은 영어 슬라이스 | 비율은 정의되지 않고 게이트는 fail-closed로 실패한다 |
| 바닥에 정확히 걸친 비율 | 경계는 이 저장소의 다른 모든 곳처럼 포함이다 |
| 서로 다른 공급자의 평가 두 개 | 비교 가능성은 어떤 나눗셈보다 먼저 검사된다 |
| 뒤집힌 사례 하나만큼의 하락 | 회귀 허용 오차는 단일 사례 해상도 위에 놓인다 |
| 정의되지 않은 비율이 담긴 렌더링 표 | `undefined`는 숫자가 아니라 단어로 찍힌다 |

### 이제 설명할 수 있어야 하는 것

답은 위의 **굵은 핵심 문장**에 있다.

- **회귀 허용 오차는 왜 0.01이 아니라 0.05인가?**
  - **답:** 24개 중 한 사례가 매크로 지표를 약 0.042 움직이므로, 더 조인 허용 오차는 노이즈에 게이트를 실패시키고 모두가 그것을 무시하도록 훈련한다.
- **정의되지 않은 비율은 왜 통과가 아니라 실패인가?**
  - **답:** `0/0`은 아무것도 검색하지 못한 두 실험군을 묘사하면서 완벽한 일치로 읽힌다. 영어 슬라이스가 죽은 실험군에는 주장할 동등성이 없다.
- **게이트는 왜 `direct` 실험군을 심판하기를 거부하는가?**
  - **답:** 그것은 이전 측정이다. 게이트하면 이미 아는 실패를 보고하게 되고, 통과시키면 수정이 측정된 적이 없다는 뜻이 된다.
- **통과한 비율이 왜 그 자체로 좋은 소식이 아닌가?**
  - **답:** 비율은 "한국어가 따라잡았다"와 "영어가 내려앉았다"를 구별하지 못하므로 언어별 회귀 검사 옆에서 함께 읽어야 한다.

---

[← 이전: 라우팅과 번역](03-routing-and-translation.md) · [모듈 개요](../03-build.md) · [검증](../05-verify.md)
