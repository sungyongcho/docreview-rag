# M8.1 튜토리얼 1 — 두 언어, 하나의 정답 집합

이제 한국어 검색과 영어 검색을 비교하려 한다. 두 질문 집합이 무엇이 정답인지에 대해 합의하지 않으면 그 비교는 아무 값어치가 없다 — 그리고 여기서 "합의"는 "비슷해 보인다"일 수 없다. **필드가 둘 이상 다른 두 스위트 사이의 지표 격차는 이름 붙일 수 있는 무엇도 측정하지 못하기 때문이다.** 이 문서는 한국어 쌍둥이 스위트와, 그 유일한 차이를 구조로 만드는 검증기를 만든다.

**선행 조건:** M1–M7 완료, `uv run pytest tests/evals -q` 통과.

### 무엇을 정의하고, 무엇을 구현하고, 무엇을 들여다볼 것인가

| 영역 | 학습 행동 | 가져갈 것 |
|---|---|---|
| `data/golden/retrieval_ko.json` | 쌍둥이를 **저작한다** | 왜 `language` 필드가 아니라 두 번째 파일인가 |
| `TWIN_INVARIANT_FIELDS` | 선언을 **작성한다** | 이 목록이 곧 "질문만 다르다"의 정의다 |
| `validate_twin_cases` | 짝 규칙을 **구현한다** | 검사 순서는 계약의 일부다 |
| `load_bilingual_suites` | 두 번 호출하는 적재를 **구현한다** | 로더의 검증을 공짜로, 두 번 받는다 |

### 1. 파일 배치를 결정하는 실패

뻔한 설계에서 출발해 그것이 죽는 것을 본다. 한국어 사례를 영어 사례 옆 `data/golden/`에 두고 디렉터리를 적재한다.

```bash
uv run python -c "from app.evals.loader import load_golden_cases; load_golden_cases('data/golden')"
```

중복 정답 span 식별자를 문제 삼는 `GoldenDataError`가 나온다. 로더는 디렉터리를 받아 모든 `*.json`을 한 배치에 병합하고, `_validate_unique_cases`는 *한 배치 안의 사례들에 걸친* 중복 span을 거부한다. 쌍둥이는 의도적으로 모든 span을 공유한다. **로더는 방해물이 아니라 쌍둥이를 의미 있게 만드는 바로 그 규칙을 강제하고 있고, 그것을 만족시키는 유일한 길은 둘을 한 배치에 넣기를 그만두는 것이다.**

사례에 `language` 필드를 다는 방법은 로더를 피해 가지만 비용이 더 크다. `GoldenCase`는 M3부터 동결돼 있고, `id`는 여전히 `^m3c-[0-9]{2}$`에 맞아야 하며, 채점·브레이크다운·큐레이션·산출물 스키마 등 모든 소비자가 아무도 필요로 하지 않는 차원을 배워야 한다. 파일 두 개는 아무것도 바꾸지 않고 아무것도 더하지 않는다.

#### `data/golden/retrieval_ko.json` 생성 — 쌍둥이 스물여덟

**학습 행동 — 쌍둥이를 저작한다:** 질문을 번역하고 나머지는 바이트 단위로 복사한다.

```json
{
  "id": "m3c-01",
  "question": "AMD의 매출총이익률은 2018 회계연도에서 2019 회계연도까지 어떻게 변화했습니까?",
  "category": "multi_hop",
  "facet": "comparison",
  "tags": [],
  "answers": [
    {
      "doc_id": "AMD-FY2019",
      "source_sha256": "45e9c96250b900ff5d329b1e76515e4ac1d93ceb5a1c28dccb7fe8a1a0b5be14",
      "start_char": 643376,
      "end_char": 644582
    }
  ],
  "expected_label": "SUPPORTED",
  "reference_answer": "Gross margin increased from 38% to 43%, a rise of 5 percentage points.",
  "note": "Year-over-year percentage comparison in an MD&A table. Korean twin of the EN case.",
  "curation_status": "agent-curated",
  "approval_status": "pending-author-approval",
  "human_verified": false
}
```

구성은 영어 스위트와 정확히 같다. `simple_lookup` 13개, `exact_number` 5개, `multi_hop` 6개, `absent` 4개다. 부재 사례 넷은 한국어로 묻되 span 0개와 `expected_label="NOT_IN_DOCS"`, `reference_answer="NOT_IN_DOCS"`를 유지한다 — 정직한 "문서에 없음"도 번역을 견뎌야 한다.

`reference_answer`는 영어로 남는다. 검색 채점은 이 필드를 절대 읽지 않으며, 두 파일이 동일한 문자열을 갖도록 요구하면 무른 기대가 검사 가능한 불변 조건으로 바뀐다.

### 2. 불변 필드 목록이 곧 계약이다

#### `app/evals/bilingual.py` 생성 — 달라져서는 안 되는 것

**학습 행동 — 선언을 작성한다:** 검색 지표가 귀속될 수 있는 필드를 전부 나열하고, 하나씩 이유를 댄다.

<!-- src: app/evals/bilingual.py::HANGUL,TWIN_INVARIANT_FIELDS -->
```python
HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")

# Every field a retrieval metric could be attributed to. Holding all of them identical
# is what makes an en/ko metric gap a fact about retrieval rather than about the data.
TWIN_INVARIANT_FIELDS = (
    "category",
    "facet",
    "tags",
    "answers",
    "expected_label",
    "reference_answer",
)
```

**코드에서 꼭 볼 것**

- 한글 패턴은 `app/retrieval/language.py`에서 가져오지 않고 이 모듈 안에 둔다. 그 감지기는 M8.3의 산출물이고, **스위트 계약은 질의 경로 코드가 존재하기 전에 성립해야 한다** — 헬퍼를 공유하면 첫 체크포인트가 세 번째에 의존하게 되고 학습자의 빌드 순서가 깨진다.
- `answers`가 목록에 있고, 이것이 가장 중요하다. span이 동일하다는 것은 한국어 실행과 영어 실행이 같은 불변 원문 좌표를 상대로 채점된다는 뜻이다.
- `category`와 `facet`이 목록에 있는 이유는 리포트의 모든 슬라이스가 이 둘로 묶기 때문이다. 다른 카테고리로 분류된 쌍둥이는 검색이 하나도 바뀌지 않았는데도 카테고리 평균을 움직인다.

#### `app/evals/bilingual.py` 확장 — 스위트 값 객체

<!-- src: app/evals/bilingual.py::BilingualSuite -->
```python
@dataclass(frozen=True, slots=True)
class BilingualSuite:
    """One English suite and its validated Korean twin, in shared case-id order."""

    en: tuple[GoldenCase, ...]
    ko: tuple[GoldenCase, ...]

    def pairs(self) -> tuple[tuple[GoldenCase, GoldenCase], ...]:
        """Return ``(en, ko)`` case pairs ordered by their shared id."""
        by_id = {case.id: case for case in self.ko}
        return tuple((case, by_id[case.id]) for case in self.en)

    def cases(self, language: str) -> tuple[GoldenCase, ...]:
        """Return the suite for one language, so a run can name its slice."""
        if language == "en":
            return self.en
        if language == "ko":
            return self.ko
        raise ValueError(f"unsupported suite language: {language}")
```

**코드에서 꼭 볼 것**

- `cases(language)`는 평범한 `GoldenCase` 튜플을 반환하며, 이는 `evaluate_retriever`가 이미 받는 것과 정확히 같다. **언어별 실행은 새로운 종류의 평가가 아니라 다른 슬라이스 위의 같은 평가다.**
- `pairs()`는 다음 장의 진단을 위해 존재한다. 그 진단은 코퍼스 없이 두 질문을 나란히 놓아야 한다.

### 3. 검사 순서는 계약의 일부다

#### `app/evals/bilingual.py` 확장 — 검증기

**학습 행동 — 짝 규칙을 구현한다:** 검사를 작성한 뒤 하나씩 일부러 깨뜨리고 나오는 메시지를 읽는다.

<!-- src: app/evals/bilingual.py::validate_twin_cases -->
```python
def validate_twin_cases(
    en_cases: Sequence[GoldenCase],
    ko_cases: Sequence[GoldenCase],
) -> tuple[tuple[GoldenCase, GoldenCase], ...]:
    """Validate that two suites differ in exactly one field, and return the pairs.

    Twin cases share their ids, their taxonomy, and — decisively — their answer spans,
    so a Korean run and an English run are scored against the same immutable source
    coordinates. That is the whole reason the parity number means anything: if the
    suites could drift, a ko/en gap would be ambiguous between "retrieval is worse in
    Korean" and "the Korean cases ask something easier".

    ``reference_answer`` stays English on both sides. Retrieval scoring never reads it,
    and requiring identity makes the invariant checkable instead of approximate.

    The two suites must live in separate files. ``load_golden_cases`` rejects duplicate
    answer-span identities inside one loaded batch, and twins share every span by
    design, so loading a directory that holds both raises before this validator runs.
    """
    if not en_cases or not ko_cases:
        raise TwinCaseError("both twin suites must be nonempty")

    en_index = {case.id: case for case in en_cases}
    ko_index = {case.id: case for case in ko_cases}
    if len(en_index) != len(en_cases) or len(ko_index) != len(ko_cases):
        raise TwinCaseError("twin suites must not repeat a case id")
    if set(en_index) != set(ko_index):
        missing = sorted(set(en_index) ^ set(ko_index))
        raise TwinCaseError(f"twin suites do not cover the same cases: {', '.join(missing)}")

    pairs: list[tuple[GoldenCase, GoldenCase]] = []
    for case_id in sorted(en_index):
        english = en_index[case_id]
        korean = ko_index[case_id]
        for field in TWIN_INVARIANT_FIELDS:
            if getattr(english, field) != getattr(korean, field):
                raise TwinCaseError(f"{case_id} twins disagree about {field}")
        # Checked before the script rules: a copied-across question is the likely
        # authoring slip, and reporting it as "no Hangul" would name the symptom.
        if _normalized(english.question) == _normalized(korean.question):
            raise TwinCaseError(f"{case_id} twins share one untranslated question")
        if HANGUL.search(english.question) is not None:
            raise TwinCaseError(f"{case_id} English question contains Hangul")
        if HANGUL.search(korean.question) is None:
            raise TwinCaseError(f"{case_id} Korean question contains no Hangul")
        pairs.append((english, korean))
    return tuple(pairs)
```

**코드에서 꼭 볼 것**

- 번역 누락 검사가 한글 검사보다 먼저 돌고, 그 순서가 하중을 받는다. 영어 질문을 한국어 사례에 붙여 넣으면 두 규칙이 모두 실패하지만 원인을 이름 붙이는 것은 하나뿐이다. **2차 결과를 보고하는 검증기는 그저 번역되지 않았을 뿐인 사례에서 인코딩 버그를 찾아 헤매게 만든다.**
- 모든 실패는 예외를 던진다. 건너뛰거나 복구하거나 정규화하지 않는다. M3 로더가 취한 자세와 같고 이유도 같다.
- 오류 메시지는 사례 ID를 싣는다. 쌍둥이 실패에서 가장 먼저 하는 일이 두 파일에서 그 사례 하나를 여는 것이기 때문이다.

### 4. 두 번의 적재, 완전한 검증, 두 번

#### `app/evals/bilingual.py` 확장 — 진입점

<!-- src: app/evals/bilingual.py::load_bilingual_suites -->
```python
def load_bilingual_suites(
    en_path: str | Path = DEFAULT_GOLDEN_PATH,
    ko_path: str | Path = KO_GOLDEN_PATH,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> BilingualSuite:
    """Load both suites through the unmodified loader and validate them as twins.

    Two separate ``load_golden_cases`` calls, not one directory load: each file gets
    the loader's full SHA-256 and span-source verification, and the Korean file is
    bound to the same raw filings as the English one, for free.
    """
    en_cases = load_golden_cases(en_path, manifest_path=manifest_path)
    ko_cases = load_golden_cases(ko_path, manifest_path=manifest_path)
    validate_twin_cases(en_cases, ko_cases)
    order = sorted(en_cases, key=lambda case: case.id)
    ko_index = {case.id: case for case in ko_cases}
    return BilingualSuite(
        en=tuple(order),
        ko=tuple(ko_index[case.id] for case in order),
    )
```

**코드에서 꼭 볼 것**

- `app/evals/loader.py`는 한 줄도 바뀌지 않는다. **파일 두 개를 강제한 그 제약이, 두 파일 모두를 코퍼스 매니페스트와 원시 공시 해시에 대고 검증되게 만드는 제약이기도 하다.**
- 두 스위트가 같은 사례 ID 순서로 돌아오므로 `pairs()`와 이후의 모든 조인은 운이 아니라 위치로 맞는다.

### 집중 테스트와 그것이 지키는 계약

```bash
uv run pytest tests/crosslingual/test_01_bilingual.py -q
```

기대 결과: `13 passed`.

| 테스트가 깨뜨리는 것 | 지키는 계약 |
|---|---|
| 다른 span을 가리키는 한국어 사례 | 쌍둥이는 하나의 원문 좌표 집합을 상대로 채점된다 |
| 영어 질문을 그대로 복사한 한국어 질문 | 번역 누락 검사가 이름을 달고 먼저 발화한다 |
| 한글이 없는 한국어 질문 | 두 문자 규칙이 양방향으로 성립한다 |
| 누락되거나 남는 사례 ID | 두 스위트는 같은 질문들을 덮는다 |
| 다른 `category`나 `reference_answer` | 지표가 귀속될 수 있는 모든 필드가 동일하게 남는다 |

### 이제 설명할 수 있어야 하는 것

답은 위의 **굵은 핵심 문장**에 있다.

- **한국어 스위트는 왜 사례의 필드가 아니라 별도 파일인가?**
  - **답:** 로더가 한 배치 안의 중복 정답 span 식별자를 거부하고 쌍둥이는 설계상 모든 span을 공유한다 — 병합을 막는 그 규칙이 쌍둥이를 비교 가능하게 만드는 규칙이다.
- **`validate_twin_cases`는 왜 한글보다 질문 동일성을 먼저 검사하는가?**
  - **답:** 번역되지 않은 복사본에서는 두 규칙이 모두 실패하는데, 증상이 아니라 원인을 이름 붙이는 것은 앞의 규칙뿐이다.
- **`bilingual.py`는 왜 자기 한글 패턴을 들고 있는가?**
  - **답:** 스위트 계약은 질의 경로 코드가 존재하기 전에 성립해야 한다. M8.3의 감지기를 가져오면 첫 체크포인트가 세 번째 체크포인트에 의존하게 된다.

---

[모듈 개요](../03-build.md) · [다음: 붕괴를 측정한다 →](02-measuring-the-collapse.md)
