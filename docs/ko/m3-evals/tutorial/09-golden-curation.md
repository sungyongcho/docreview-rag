# M3.5 튜토리얼 9 — 골든 큐레이션과 분류 체계 분해

측정 도구는 완성됐다. 튜토리얼 8까지의 결과로 어떤 설정이든 격리된 코퍼스를 상대로 실행되고, 끝에는 비교 가능한 아티팩트가 남는다. 모듈이 아직 열어 둔 것은 성장이다. 28개 사례는 도구가 작동한다는 증명으로는 충분하지만 검색이 어디서 실패하는지 지도를 그리기에는 너무 적고, 새 사례가 어떤 경로로 스위트에 들어와야 하는지는 아직 아무것도 정의하지 않았다. 골든 셋을 키우는 일이 **동결된 정답지를 녹이지 않게** 만들어야 한다.

이 계층이 없으면 성장 자체가 오염 경로가 된다. 사례를 이어 붙이는 사람이, 앞으로의 모든 실행이 무엇을 기준으로 측정되는지를 함께 조용히 다시 정의하게 되기 때문이다. 이 튜토리얼이 세우는 불변조건은 이것이다. **기록된 사람의 결정 없이는 어떤 사례도 측정 풀에 들어오지 못하고, 어떤 승격도 인증을 부여하지 않는다.**

**선행 조건:** 튜토리얼 8까지 M3.4의 전체 평가 경로가 통과한 상태여야 한다.

### 생성된 사례는 증거가 아니라 주장이다

커밋된 28개 사례는 에이전트가 선별한 결과다. LLM이 질문을 쓰고 원문 span을 찾았고, 사람이 인증한 적이 없으므로 전부 `pending-author-approval`을 달고 있다. 셋을 키우는 방법도 같다 — 질문을 쓰고 오프셋을 찾는 노동이야말로 기계에 맡길 가치가 있는 일이다. 그러면 갓 생성된 사례를 `retrieval.json`에 곧바로 이어 붙이면 무슨 일이 생기는가?

**정답지가 조용히 썩는다.** 해시가 코퍼스에 묶이지 않은 span은 영원히 못 찾는 정답으로 채점되고, 기존 질문의 근사 중복은 하나의 사실을 모든 매크로 평균에 두 번 넣으며, 46,000자짜리 정찰용 span은 어떤 겹침 규칙이든 그 규칙의 허점을 파고든다. 아무것도 큰 소리로 실패하지 않는다. 지표가 검색기 대신 생성기의 습관을 재기 시작할 뿐이다.

그래서 생성된 사례는 별도의 후보 네임스페이스로 들어오고, `app/evals/curation.py`가 사람이 판단에 1분을 쓰기 전에 모든 기계 게이트를 먼저 돌린다. 기계가 증명하는 것은 사례가 **형식에 맞고 원문에 정직하게 묶여 있다**는 것까지다. 입장은 기록된 명시적 결정만이 허락하고, 침묵은 아무것도 허락하지 않는다.

```
generated candidates (m3s-*) → machine gates: schema / dedup / source binding → review queue markdown
    → explicit human decisions → promotion mints the next m3c ids → golden-shaped JSON for a reviewed merge
```

커밋된 `data/golden/candidates/r1.json`이 이 체크포인트의 실습 재료다. `claude-fable-5`가 불변 코퍼스를 상대로 생성한 후보 4건으로, positive 3건의 정답 span은 원문 기준 104자, 176자, 559자 폭이라 span 상한에 여유 있게 들어오고, absent 1건인 `m3s-04`는 계약대로 span이 0개다. 질문은 일부러 원문 어휘를 피해 바꿔 썼다 — 파일링이 net revenue라고 쓰는 곳을 "overall sales"로, top ten customers를 "ten biggest buyers"로 묻는다 — 그래서 배치 전체가 스위트의 알려진 어휘 편향을 찌르는 패러프레이즈 프로브를 겸한다. 배치는 모든 기계 게이트를 통과했고 결정은 하나도 붙어 있지 않다. 각 후보는 기계 검증을 마친 pending 상태로 수명 주기의 출발점에 서 있고, 검수는 저자의 몫이다.

이것은 원래의 28개 사례가 아직 머물러 있는 것과 같은 수명 주기다. 그들의 검수 큐는 `data/golden/REVIEW.md`로 커밋되어 있고, 모든 행이 agent-curated에 pending이다 — 기계 검증은 끝났고 저자 승인은 남아 있다. 후보를 앞으로 움직이는 것은 이 튜토리얼이 만들게 하고 그 다음 직접 수행하게 하는 역할, 즉 검수자다. 명시적 결정을 쓰고, 큐를 렌더링하고, 승인된 나머지를 **새** 골든 모양 파일로 승격한다. 그 파일을 `retrieval.json`에 병합하는 일은 별도의 버전 릴리스 사건으로 남는다. 커밋된 스위트의 개수 — 사례 28개와 category·facet 히스토그램 — 가 `tests/evals/golden.py`에 계약으로 동결되어 있기 때문이다. 성장은 같은 커밋에서 계약을 함께 갱신하는 검토된 diff로 도착해야 하지, 스크립트 실행의 부수 효과여서는 안 된다.

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `CandidateCase` | **구조 작성** | 후보는 골든 id가 없는 골든 사례다 |
| 입장 게이트 | 기계 검증을 **직접 구현** | 사람이 판단을 쓰기 전에 기계 검증부터 끝낸다 |
| `ReviewDecision`과 `candidate_states` | **설계 결정 확인** | 침묵은 아무것도 승인하지 않는다 |
| `promote_approved` | 승격을 **직접 구현** | 승격은 id를 발급할 뿐 인증을 발급하지 않는다 |
| `breakdown_by_category` | **구조 작성** | 분류 체계가 숫자로 값을 하는 지점 |

### 1. 후보는 골든 id가 없는 골든 사례다

#### `app/evals/curation.py` 생성 — 후보 계약

**학습 행동 — 구조 작성:** 서브클래스가 다시 쓰지 않고 그대로 물려받는 불변조건이 무엇인지 확인한다.

파일은 헤더와 모듈 상수 셋으로 시작한다. 아래의 모든 게이트가 이들을 재사용하므로 가장 먼저 타이핑한다.

```python
"""Candidate intake, machine validation, review queue, and fail-closed promotion."""

from __future__ import annotations

from collections.abc import Sequence
import json
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, TypeAdapter, ValidationError
from pydantic.functional_validators import field_validator

from app.evals.loader import DEFAULT_MANIFEST_PATH, GoldenDataError, validate_golden_sources
from app.evals.types import GoldenCase
```

<!-- src: app/evals/curation.py::MAX_CANDIDATE_SPAN_CHARS,CandidateState -->
```python
MAX_CANDIDATE_SPAN_CHARS: Final[int] = 2_500

DecisionLabel = Literal["approve", "reject"]
CandidateState = Literal["pending", "approved", "rejected"]
```

소스에서 `MAX_CANDIDATE_SPAN_CHARS` 위의 주석이 이유를 말한다 — 그보다 넓은 span은 정답이 아니라 정찰이다. 두 별칭은 어떤 클래스가 쓰기 전에 검수 결정과 후보 상태에 닫힌 어휘를 준다.

<!-- src: app/evals/curation.py::CurationError,ReviewDecision -->
```python
class CurationError(ValueError):
    """A candidate file, review decision, or promotion violates the curation contract."""


class CandidateCase(GoldenCase):
    """One generated golden candidate that has not earned an ``m3c`` id yet.

    A candidate carries the full golden payload plus generator provenance, so every
    golden invariant is inherited and enforced at intake. Only promotion may mint a
    golden id, and a candidate can never claim any status beyond the pinned pending
    literals it inherits.
    """

    id: Annotated[StrictStr, Field(pattern=r"^m3s-[0-9]{2}$")]
    generator: Annotated[StrictStr, Field(min_length=1)]

    @field_validator("generator", mode="after")
    @classmethod
    def reject_blank_generator(cls, value: str) -> str:
        """Keep generator provenance non-empty, single-line, and table-safe."""
        if not value.strip():
            raise ValueError("generator must not be blank")
        if "|" in value or "\n" in value:
            raise ValueError("generator must not contain pipes or newlines")
        return value


class ReviewDecision(BaseModel):
    """One explicit human verdict on one candidate. Absence of a verdict is pending."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: Annotated[StrictStr, Field(pattern=r"^m3s-[0-9]{2}$")]
    decision: DecisionLabel
    reviewer: Annotated[StrictStr, Field(min_length=1)]
    note: Annotated[StrictStr, Field(min_length=1)]

    @field_validator("reviewer", "note", mode="after")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """Reject strings that contain only whitespace."""
        if not value.strip():
            raise ValueError("text fields must not be blank")
        return value
```

**코드에서 확인할 것**

- `CandidateCase`는 `GoldenCase`를 상속하므로, M3.1의 absent/positive 상호배타 규칙, 공백 문자열 거부, span 유일성, 반개구간 검사가 전부 다시 쓰지 않아도 입장 시점에 실행된다.
- 바뀌는 것은 둘뿐이다. id 패턴이 `m3s` 네임스페이스로 옮겨가고, `generator`가 어느 모델이나 사람이 사례를 썼는지 기록한다.
- 고정 리터럴도 그대로 상속된다 — 후보는 `human_verified=true`나 승인 상태를 표현조차 할 수 없다. 생성된 사례가 인증을 주장하지 못하게 막는 것은 규율이 아니라 스키마다.
- `ReviewDecision`은 `reviewer`와 `note`를 요구한다. 아무도 서명하지 않았거나 이유가 없는 판정은 나중에 감사할 수 없으므로, 모델이 표현 자체를 거부한다.

> **개념 — 계약을 좁히는 서브클래싱**
>
> 기존 타입보다 최소한 같거나 더 엄격해야 하는 경계 타입은 기존 타입을 흉내 내는 대신 상속해야 한다. 상속하면 베이스의 모든 검증기가 새 타입 위에서 자동으로 돌기 때문에, 더 엄격한 계약이 "베이스 계약 더하기 오버라이드"로 표현된다 — 아무것도 다시 쓰지 않고, 아무것도 잊어버릴 수 없다.
>
> 대안인 검증기 복사는 서로 독립적으로 표류하는 두 계약을 만든다. 한쪽에만 필드가 추가되는 순간 경계 하나가 조용히 느슨해지는데, 각 모델은 여전히 내부적으로 정합하므로 어떤 테스트도 실패하지 않는다. 상속으로 좁히면 이 실패 모드가 구조적으로 사라진다 — 후보 계약은 골든 계약보다 약해질 수 없고, 그 위에 제약을 더할 수만 있다.

또 하나의 명백한 설계는 네임스페이스를 아예 나누지 않는 것이다. 임시 `m3c` id를 발급하고 후보 표시 플래그를 다는 방식이다. 그러면 측정된 진실과 입장하지 못한 주장의 차이가 플래그 확인을 기억하는 일에 달리게 된다 — 필터 하나를 잊는 순간 생성된 사례가 정답지와 구분되지 않고, 오늘 발급한 임시 id가 내일 커밋되는 id와 충돌할 수 있다. 별도의 `m3s` 패턴은 이 분리를 기계적으로 만든다. 어떤 id도 두 집단에 동시에 속하지 않으므로, 어떤 코드 경로도 둘을 혼동할 수 없다.


모듈 수준 어댑터 둘이 계약 계층을 닫는다. 후보 파일과 결정 파일 전체를 리스트로 검증하며, 로더의 `GOLDEN_CASES`를 그대로 따라간 형태다.

<!-- src: app/evals/curation.py::CANDIDATE_CASES,REVIEW_DECISIONS -->
```python
CANDIDATE_CASES = TypeAdapter(list[CandidateCase])
REVIEW_DECISIONS = TypeAdapter(list[ReviewDecision])
```

### 2. 사람이 판단을 쓰기 전에 기계 검증부터 끝낸다

#### `app/evals/curation.py` 확장 — 입장 게이트

**학습 행동 — 기계 검증 직접 구현:** 사람이 읽기 전에 후보 배치가 거부될 수 있는 경로가 몇 가지인지 센다.

작은 도우미 다섯이 먼저 온다 — 아래 모든 게이트가 기대는 엄격한 읽기와 정체성 추출기다.

<!-- src: app/evals/curation.py::_reject_duplicate_keys,_span_identities -->
```python
def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CurationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except CurationError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CurationError(f"cannot read valid UTF-8 JSON from {path}: {exc}") from exc


def _candidate_files(path: Path) -> list[Path]:
    if path.is_dir():
        files = sorted(path.glob("*.json"))
        if not files:
            raise CurationError(f"no candidate JSON files found in {path}")
        return files
    return [path]


def _normalized_question(question: str) -> str:
    return " ".join(question.casefold().split())


def _span_identities(case: GoldenCase) -> list[tuple[str, str, int, int]]:
    return [
        (answer.doc_id, answer.source_sha256, answer.start_char, answer.end_char)
        for answer in case.answers
    ]
```

`_read_json`은 아래 중복 키 개념 박스가 코드가 되는 자리고, `_candidate_files`는 `sorted`로 디렉터리 로딩을 결정론적으로 유지하며, 추출기 둘은 이 파일의 나머지 전부에서 "같은 질문"과 "같은 span"이 무엇을 뜻하는지 정의한다.

<!-- src: app/evals/curation.py::_validate_unique_candidates,_validate_disjoint_from_golden -->
```python
def _validate_unique_candidates(candidates: Sequence[CandidateCase]) -> None:
    ids: set[str] = set()
    questions: set[str] = set()
    identities: set[tuple[str, str, int, int]] = set()
    for candidate in candidates:
        if candidate.id in ids:
            raise CurationError(f"duplicate candidate id: {candidate.id}")
        ids.add(candidate.id)

        normalized = _normalized_question(candidate.question)
        if normalized in questions:
            raise CurationError(f"duplicate normalized candidate question: {candidate.question}")
        questions.add(normalized)

        for identity in _span_identities(candidate):
            if identity in identities:
                raise CurationError(f"duplicate answer span identity in {candidate.id}")
            identities.add(identity)

        for answer in candidate.answers:
            width = answer.end_char - answer.start_char
            if width > MAX_CANDIDATE_SPAN_CHARS:
                raise CurationError(
                    f"{candidate.id} span is reconnaissance, not an answer: "
                    f"{width} > {MAX_CANDIDATE_SPAN_CHARS} chars"
                )


def _validate_disjoint_from_golden(
    candidates: Sequence[CandidateCase],
    golden_cases: Sequence[GoldenCase],
) -> None:
    golden_questions = {_normalized_question(case.question) for case in golden_cases}
    golden_identities = {identity for case in golden_cases for identity in _span_identities(case)}
    for candidate in candidates:
        if _normalized_question(candidate.question) in golden_questions:
            raise CurationError(
                f"{candidate.id} duplicates a golden question: {candidate.question}"
            )
        for identity in _span_identities(candidate):
            if identity in golden_identities:
                raise CurationError(f"{candidate.id} reuses a golden answer span identity")
```

입장은 두 검사를 골든 로더가 쓰는 것과 같은 엄격한 읽기·원문 바인딩에 묶는다.

<!-- src: app/evals/curation.py::load_candidate_cases -->
```python
def load_candidate_cases(
    path: str | Path,
    *,
    golden_cases: Sequence[GoldenCase],
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> list[CandidateCase]:
    """Load one file or a directory of candidate files and run every machine gate.

    Structural validation, uniqueness, disjointness from the committed golden set,
    and raw-source binding all run here, so a candidate that survives intake fails
    later only on human judgment, never on mechanics.
    """
    candidates: list[CandidateCase] = []
    for candidate_path in _candidate_files(Path(path)):
        payload = _read_json(candidate_path)
        if not isinstance(payload, list):
            raise CurationError(f"candidate file root must be a JSON array: {candidate_path}")
        try:
            candidates.extend(CANDIDATE_CASES.validate_python(payload))
        except ValidationError as exc:
            raise CurationError(f"invalid candidate cases in {candidate_path}: {exc}") from exc

    _validate_unique_candidates(candidates)
    _validate_disjoint_from_golden(candidates, golden_cases)
    try:
        validate_golden_sources(candidates, manifest_path)
    except GoldenDataError as exc:
        raise CurationError(str(exc)) from exc
    return candidates
```

**코드에서 확인할 것**

- 중복 제거는 두 번 돈다. 배치 내부에서 한 번, 커밋된 골든 셋을 상대로 한 번이다. 살아남은 근사 중복은 성장처럼 보이면서 하나의 사실을 모든 매크로 평균에 두 번 넣는다.
- 2,500자 span 상한이 입장 시점에 강제된다. 커밋된 셋이 이미 이 경계를 지키고 있고, 그보다 넓은 span은 생성기가 정답을 찾은 것이 아니라 구역을 인용했다는 뜻이다.
- `validate_golden_sources`는 **골든 로더가 신뢰하는 바로 그 함수**다 — 해시 바인딩, 경계, 가시 증거 검사를 다시 구현하지 않으므로 두 경로가 어긋날 수 없다.
- 모든 실패가 `CurationError`로 나오고, 감싼 `GoldenDataError`도 마찬가지다. 입장의 오류 표면은 하나라서, 호출자가 어느 계층이 배치를 거부했는지 추측할 필요가 없다.

사람이 한 글자도 읽기 전에 입장이 거부할 수 있는 것을 세면 이렇다. 읽을 수 없거나 키가 중복된 JSON, 배열이 아닌 루트, 골든 계약에서 상속된 모든 스키마 위반, 중복 id, 중복 정규화 질문, 중복 span 정체성, 상한보다 넓은 span, 커밋된 질문과의 충돌, 커밋된 span 정체성의 재사용, 그리고 모든 원문 바인딩 실패. 검수자에게 남는 것은 정확히 기계가 판단할 수 없는 잔여물이다 — 질문이 모호하지 않은지, 인용된 span이 정말 그 질문에 답하는지, category와 facet이 유용한지. 커밋된 후보들이 정직한 정답 span의 의도된 규모를 보여 준다. positive span 3개는 원문 기준 104자에서 559자로 — 문장과 문단 크기의 증거이며 — 2,500자 상한에 크게 못 미친다.

### 3. 침묵은 아무것도 승인하지 않는다

#### `app/evals/curation.py` 확장 — 명시적 결정과 검수 큐

**학습 행동 — 설계 결정 확인:** 결정 하나의 부재는 pending일 뿐인데 결정 파일의 부재는 왜 오류여야 하는지 따져 본다.

<!-- src: app/evals/curation.py::load_review_decisions,review_queue_markdown -->
```python
def load_review_decisions(path: str | Path) -> list[ReviewDecision]:
    """Load explicit review decisions. A missing file is an error, never an empty set."""
    decisions_path = Path(path)
    if not decisions_path.is_file():
        raise CurationError(f"decisions file does not exist: {decisions_path}")
    payload = _read_json(decisions_path)
    if not isinstance(payload, list):
        raise CurationError(f"decisions file root must be a JSON array: {decisions_path}")
    try:
        decisions = REVIEW_DECISIONS.validate_python(payload)
    except ValidationError as exc:
        raise CurationError(f"invalid review decisions in {decisions_path}: {exc}") from exc

    seen: set[str] = set()
    for decision in decisions:
        if decision.candidate_id in seen:
            raise CurationError(f"duplicate review decision for {decision.candidate_id}")
        seen.add(decision.candidate_id)
    return decisions


def candidate_states(
    candidates: Sequence[CandidateCase],
    decisions: Sequence[ReviewDecision] = (),
) -> dict[str, CandidateState]:
    """Map every candidate id to pending, approved, or rejected.

    Every decision must name a known candidate, and at most one decision may exist
    per candidate. A candidate without a decision stays pending — silence never
    approves anything.
    """
    known = {candidate.id for candidate in candidates}
    if len(known) != len(candidates):
        raise CurationError("candidate ids must be unique")

    states: dict[str, CandidateState] = {candidate.id: "pending" for candidate in candidates}
    decided: set[str] = set()
    for decision in decisions:
        if decision.candidate_id not in known:
            raise CurationError(f"decision references unknown candidate: {decision.candidate_id}")
        if decision.candidate_id in decided:
            raise CurationError(f"duplicate review decision for {decision.candidate_id}")
        decided.add(decision.candidate_id)
        states[decision.candidate_id] = "approved" if decision.decision == "approve" else "rejected"
    return states


def review_queue_markdown(
    candidates: Sequence[CandidateCase],
    decisions: Sequence[ReviewDecision] = (),
) -> str:
    """Render the deterministic review queue an author walks before any promotion."""
    states = candidate_states(candidates, decisions)
    lines = [
        "| ID | Category | Facet | Positive source | Generator | Decision |",
        "|---|---|---|---|---|---|",
    ]
    for candidate in sorted(candidates, key=lambda case: case.id):
        doc_ids = sorted({answer.doc_id for answer in candidate.answers})
        source = ", ".join(doc_ids) if doc_ids else "none"
        lines.append(
            f"| {candidate.id} | {candidate.category} | {candidate.facet} | "
            f"{source} | {candidate.generator} | {states[candidate.id]} |"
        )
    return "\n".join(lines)
```

**코드에서 확인할 것**

- 결정이 없는 후보는 `pending`이고, pending은 절대 승격되지 않는다. 이 파이프라인의 기본 상태는 "아무것도 하지 않는다"이다.
- 결정 파일이 없으면 빈 집합으로 읽히는 대신 예외가 난다. 부재를 빈 집합으로 취급하면 오타 난 경로와 "저자가 아무것도 승인하지 않았다"가 구분되지 않고, 결정이 발견조차 되지 않았다는 신호 없이 모든 후보가 조용히 pending에 머문다.
- 모르는 후보를 가리키는 결정과 같은 후보에 대한 두 번째 결정은 둘 다 거부된다. 자기 배치 위에 재생할 수 없는 결정 로그는 지저분한 것이 아니라 손상된 것이다.
- 큐는 id 정렬 순서로 후보당 한 줄씩 렌더링되므로, 같은 상태를 두 번 렌더링하면 바이트까지 같아 `diff`가 깨끗하게 된다 — M3.4의 모든 아티팩트가 이미 갖고 있는 성질이다.

> **개념 — fail-closed 기본값**
>
> 파이프라인의 기본 상태는 사람이 아무것도 하지 않을 때 벌어지는 일이고, 이 파이프라인은 서로 다른 세 자리에서 "아무것도 하지 않는다"를 기본값으로 삼는다. 결정되지 않은 후보는 pending에 머문다 — 반쯤 끝난 검수가 아무도 살펴보지 못한 사례를 조용히 입장시키는 경로를 닫는다. 결정 파일이 없으면 빈 집합으로 읽히는 대신 예외가 난다 — 오타 난 경로가 "아무것도 승인하지 않고 완료된 검수"를 사칭하는 경로를 닫는다. 그리고 승격은 pending 출처를 보존한다 — 입장이 인증을 사칭하는 경로를 닫는다.
>
> 세 선택은 한 가지 모양을 공유한다. 정보가 없는 곳마다 시스템은 관대한 해석을 추측하는 대신 전진을 거부한다. fail-open 설계는 정확히 여기서 샌다 — 기본값 하나하나는 무해해 보이고, 피해는 기본값이 사고로 발동됐는데 그 사실을 아무것도 기록하지 않았을 때에야 나타난다.

숨어 있는 결정이 둘 더 있다. 결정은 후보 JSON을 고쳐 쓰는 대신 자기 파일에 산다. 결정이란 책임지는 검수자와 명시된 이유가 붙은 사건이기 때문이다. 분리해 두면 로그를 배치 위에 처음부터 재생할 수 있어 어떤 손상이든 감지되지만, 제자리 편집은 생성기가 원래 무엇을 만들었는지에 대한 증거를 덮어쓴다. 그리고 큐가 검수 UI 대신 마크다운으로 렌더링되는 이유는 큐 자체가 검수 증거이기 때문이다 — 풀 리퀘스트에서 diff로 읽히고, 자신이 설명하는 데이터 옆에서 버전 관리되며, 렌더링할 때마다 바이트까지 같다. `data/golden/REVIEW.md`가 원래 28개 사례에 대해 정확히 이 아티팩트다.

### 4. 승격은 id를 발급할 뿐 인증을 발급하지 않는다

#### `app/evals/curation.py` 확장 — fail-closed 승격

**학습 행동 — 승격 직접 구현:** 승격된 사례가 왜 여전히 `pending-author-approval`인지 추적한다.

<!-- src: app/evals/curation.py::_next_golden_number,write_golden_cases -->
```python
def _next_golden_number(golden_cases: Sequence[GoldenCase]) -> int:
    return max((int(case.id.split("-", 1)[1]) for case in golden_cases), default=0) + 1


def promote_approved(
    candidates: Sequence[CandidateCase],
    decisions: Sequence[ReviewDecision],
    golden_cases: Sequence[GoldenCase],
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> tuple[GoldenCase, ...]:
    """Mint golden cases from explicitly approved candidates only.

    Promotion re-runs every machine gate — uniqueness, disjointness from the
    committed set, and raw-source binding for the approved cases — assigns the next
    free ``m3c`` ids in candidate-id order, and keeps the pinned pending-approval
    provenance: entering the golden pool queues a case for the author, it never
    certifies one.
    """
    _validate_unique_candidates(candidates)
    _validate_disjoint_from_golden(candidates, golden_cases)
    states = candidate_states(candidates, decisions)

    approved = [
        candidate
        for candidate in sorted(candidates, key=lambda case: case.id)
        if states[candidate.id] == "approved"
    ]
    try:
        validate_golden_sources(approved, manifest_path)
    except GoldenDataError as exc:
        raise CurationError(str(exc)) from exc
    number = _next_golden_number(golden_cases)
    promoted: list[GoldenCase] = []
    for candidate in approved:
        if number > 99:
            raise CurationError("golden id namespace m3c-NN is exhausted")
        payload = candidate.model_dump(mode="json", exclude={"generator"})
        payload["id"] = f"m3c-{number:02d}"
        try:
            promoted.append(GoldenCase.model_validate(payload))
        except ValidationError as exc:
            raise CurationError(f"promoted case from {candidate.id} is invalid: {exc}") from exc
        number += 1
    return tuple(promoted)


def write_golden_cases(path: str | Path, cases: Sequence[GoldenCase]) -> Path:
    """Write promoted cases as a golden-shaped JSON array for a reviewed merge."""
    target = Path(path)
    if target.suffix != ".json":
        raise CurationError(f"golden output must be a .json file: {target}")
    payload = [case.model_dump(mode="json") for case in cases]
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target
```

**코드에서 확인할 것**

- `approved`만, 후보 id 순서로 승격되고, id는 커밋된 가장 큰 `m3c` 번호 다음부터 이어진다. 승격 순서는 dict 순회가 아니라 데이터의 성질이다.
- 승격 payload는 `generator`를 떼고 `GoldenCase.model_validate`로 재검증되며, 승인된 모든 span은 먼저 원문에 다시 바인딩된다. M3.1의 골든 계약이 마지막 게이트라서, 로더가 거부할 것을 승격이 만들어낼 수 없다.
- 출처는 `pending-author-approval`과 `human_verified=false`로 남는다. 입장 검수는 사례가 풀에 들어갈 자격을 판단했을 뿐이고, 저자의 span 수준 인증은 별도의 나중 사건이다. 여기서 코드가 인증을 부여하면 출처를 조작하는 것이다.
- `write_golden_cases`는 **새** JSON 파일을 쓴다. `retrieval.json`으로의 병합은 의도된 버전 릴리스 결정이다. 커밋된 셋의 개수가 `tests/evals/golden.py`에 동결 계약으로 박혀 있어서, 조용한 병합은 설계상 테스트를 깨뜨리게 되어 있다.

> **개념 — 입장과 인증**
>
> 이 파이프라인은 "승인됨" 비트 하나로 뭉개기 쉬운 두 판단을 분리한다. 입장은 후보가 측정 풀의 한 자리를 차지할 자격이 있는지를 묻는다. 질문이 잘 세워졌는지, 중복이 없는지, span이 정직하게 바인딩됐는지다. 인증은 책임지는 저자가 답의 모든 사실을 원문과 대조해 검증했는지를 묻는다. 앞의 것은 검수자가 몇 분 안에 내리는 선별 결정이고, 뒤의 것은 골든 계약 전체가 지키려고 존재하는 출처 주장이다.
>
> 둘을 뭉개면 엄밀한 의미에서 출처가 조작된다. 어떤 검증 사건도 만들어낸 적 없는 검증 상태를 사례가 달게 되기 때문이다. 두 단계를 분리하는 비용은 필드 하나를 더 읽는 것이고, 뭉개는 비용은 그 필드를 다시는 신뢰할 수 없게 되는 것이다.

구체적으로, 커밋된 28개 스위트를 상대로 승격을 실행하면 처음 발급되는 id는 `m3c-29`다 — 번호는 커밋된 수열을 이어가지만, 승격된 payload는 여전히 agent-curated, pending, 미검증이라고 읽힌다. 이 파이프라인은 어느 지점에서도 실제로 일어난 일보다 많은 것을 서류가 주장하는 사례를 만들어내지 않는다.

### 5. 분류 체계가 값을 하는 지점

#### `app/evals/breakdown.py` 생성 — category와 facet으로 묶인 지표

**학습 행동 — 구조 작성:** 평균을 내기 전에 엄격한 짝짓기가 무엇을 거부하는지 확인한다.

이 파일도 헤더로 시작한다 — import가 설계를 소리 내어 말한다. 점수는 `scoring`에서, 어휘는 `types`에서 오고, 그 밖에는 아무것도 들어오지 않는다.

```python
"""Taxonomy-grouped retrieval metrics over one scored golden suite."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import get_args

from app.evals.scoring import CaseScore, score_suite
from app.evals.types import GoldenCase, GoldenCategory, GoldenFacet
```

<!-- src: app/evals/breakdown.py::GroupScore -->
```python
@dataclass(frozen=True, slots=True)
class GroupScore:
    """Macro-averaged retrieval metrics for one taxonomy group of positive cases."""

    group: str
    k: int
    case_count: int
    recall_at_k: float
    hit_rate_at_k: float
    mrr: float
```

<!-- src: app/evals/breakdown.py::_positive_case_index -->
```python
def _positive_case_index(cases: Sequence[GoldenCase]) -> dict[str, GoldenCase]:
    index: dict[str, GoldenCase] = {}
    for case in cases:
        if case.id in index:
            raise ValueError(f"duplicate golden case id: {case.id}")
        index[case.id] = case
    return index
```

<!-- src: app/evals/breakdown.py::_validated_pairs -->
```python
def _validated_pairs(
    cases: Sequence[GoldenCase],
    scores: Sequence[CaseScore],
) -> list[tuple[GoldenCase, CaseScore]]:
    """Pair every score with its positive case and reject partial or stray scoring.

    A breakdown over a subset would silently misrepresent a group, so every positive
    case must carry exactly one score, an absent case must carry none, and every
    score must point at a known case.
    """
    index = _positive_case_index(cases)
    if not scores:
        raise ValueError("scores must not be empty")
    if len({score.k for score in scores}) != 1:
        raise ValueError("all case scores must use the same k")

    pairs: list[tuple[GoldenCase, CaseScore]] = []
    scored_ids: set[str] = set()
    for score in scores:
        case = index.get(score.case_id)
        if case is None:
            raise ValueError(f"score references unknown golden case: {score.case_id}")
        if case.category == "absent":
            raise ValueError(f"absent case cannot carry a retrieval score: {score.case_id}")
        if score.case_id in scored_ids:
            raise ValueError(f"duplicate case score: {score.case_id}")
        scored_ids.add(score.case_id)
        pairs.append((case, score))

    unscored = [
        case.id for case in cases if case.category != "absent" and case.id not in scored_ids
    ]
    if unscored:
        raise ValueError(f"positive cases missing a score: {', '.join(sorted(unscored))}")
    return pairs
```

> **개념 — 엄격한 전단사**
>
> 그룹 평균은 그룹의 구성원 명단이 닫혀 있을 때만 신뢰할 수 있다. 분해가 건네받은 점수를 그대로 받아들이면 각 그룹의 숫자는 "우연히 채점된 사례들"의 평균이 된다 — 산술은 흠잡을 데 없는데 주장은 거짓이다. 어려운 사례 하나를 그룹에서 빠뜨리면 렌더링된 표에 아무 흔적도 남기지 않은 채 그 그룹의 평균이 올라가기 때문이다. 이것이 분류 체계로 거짓말하는 가장 강력한 방법이다. 보이는 숫자는 전부 검산이 맞고, 거짓말은 보이지 않는 구성원 명단에만 산다.
>
> positive 사례마다 정확히 하나의 점수, absent 사례에는 0개, 낯선 점수는 거부 — 이 요구가 불완전한 구성원 명단을 조용한 재가중이 아니라 명시적 오류로 만든다. 그러면 렌더링할 수 있는 표는 그 실행에 존재할 수 있는 유일한 표가 된다.

짝짓기와 공개 함수 사이에 그룹핑 엔진이 앉는다. 선언 순서 순회, 빈 그룹 건너뛰기, 그룹당 `score_suite` 호출 한 번이다.

<!-- src: app/evals/breakdown.py::_grouped -->
```python
def _grouped(
    pairs: Sequence[tuple[GoldenCase, CaseScore]],
    groups: Sequence[str],
    key: Callable[[GoldenCase], str],
) -> tuple[GroupScore, ...]:
    results: list[GroupScore] = []
    for group in groups:
        members = [score for case, score in pairs if key(case) == group]
        if not members:
            continue
        suite = score_suite(members)
        results.append(
            GroupScore(
                group=group,
                k=suite.k,
                case_count=suite.case_count,
                recall_at_k=suite.recall_at_k,
                hit_rate_at_k=suite.hit_rate_at_k,
                mrr=suite.mrr,
            )
        )
    return tuple(results)
```

<!-- src: app/evals/breakdown.py::breakdown_by_category,breakdown_markdown -->
```python
def breakdown_by_category(
    cases: Sequence[GoldenCase],
    scores: Sequence[CaseScore],
) -> tuple[GroupScore, ...]:
    """Group suite metrics by golden category in declaration order."""
    pairs = _validated_pairs(cases, scores)
    return _grouped(pairs, get_args(GoldenCategory), lambda case: case.category)


def breakdown_by_facet(
    cases: Sequence[GoldenCase],
    scores: Sequence[CaseScore],
) -> tuple[GroupScore, ...]:
    """Group suite metrics by golden facet in declaration order."""
    pairs = _validated_pairs(cases, scores)
    return _grouped(pairs, get_args(GoldenFacet), lambda case: case.facet)


def breakdown_markdown(dimension: str, groups: Sequence[GroupScore]) -> str:
    """Render one taxonomy breakdown as a compact comparison table."""
    if not dimension.strip():
        raise ValueError("dimension must not be blank")
    if not groups:
        raise ValueError("groups must not be empty")
    lines = [
        f"| {dimension} | Cases | Recall@k | Hit rate@k | MRR |",
        "|---|---:|---:|---:|---:|",
    ]
    for group in groups:
        lines.append(
            f"| {group.group} | {group.case_count} | {group.recall_at_k:.6f} | "
            f"{group.hit_rate_at_k:.6f} | {group.mrr:.6f} |"
        )
    return "\n".join(lines)
```

**코드에서 확인할 것**

- 짝짓기는 엄격한 전단사다. 모든 positive 사례가 정확히 하나의 점수를 갖고, absent 사례는 하나도 갖지 않으며, 낯선 점수와 중복 점수는 거부된다. 부분집합을 허용하는 분해는 우연히 살아남은 사례들의 평균을 그룹 평균이라고 보고하게 된다.
- 그룹 순서는 `Literal` 선언에서 `get_args`를 거쳐 나온다. 표는 항상 `simple_lookup, exact_number, multi_hop` 순서로 읽히고 — 알파벳 순서의 기습이 없다 — 채점된 사례가 없는 그룹은 빈 평균을 내는 대신 사라진다.
- 그룹별 집계는 M3.2의 `score_suite`를 재사용한다. 이 코드베이스에 매크로 평균 구현은 하나뿐이라서, 스위트 표와 그룹 표가 산술을 두고 다툴 수 없다.
- 집계 하나는 어떤 종류의 질문이 실패하는지 숨긴다. category로 묶으면 커밋된 실행의 실패가 고르게 퍼지는 대신 한곳에 날카롭게 몰린다. 분류 체계는 정확히 숫자 하나를 실패 지도로 바꾸기 위해 존재한다 — 커밋된 실행의 category별 해석은 [평가 리포트](../../eval-report.md)에 있다.

여기서 모듈의 숫자가 숫자 하나이기를 멈춘다. 커밋된 최강 실험군 — 1200자 BM25 lexical 검색, 집계 Recall@5 0.520833 — 을 다시 묶으면 `simple_lookup`은 13개 사례에서 recall 0.730769, `multi_hop`은 0.500000, `exact_number`는 모든 지표에서 0.000000이 된다. facet으로는 `numeric`만이 0이다. 집계가 완전히 실패하는 category 하나를 숨기고 있었던 것이다. 커밋된 아티팩트에서 category 표를 오프라인으로 재현할 수 있다.

```bash
uv run python -c "
import json

from app.evals.breakdown import breakdown_by_category, breakdown_markdown
from app.evals.loader import load_golden_cases
from app.evals.scoring import CaseScore

cases = load_golden_cases('data/golden/retrieval.json', manifest_path='data/corpus/manifest.json')
run = json.load(open('data/eval_runs/20260824T203336Z-structure-1200-lexical-bm25.json'))
scores = [CaseScore(**case['score']) for case in run['cases'] if case['score'] is not None]
print(breakdown_markdown('Category', breakdown_by_category(cases, scores)))
"
```

그 0점들 뒤의 진단 — 답이 큰 재무 테이블 안에 살고, 그 원문 span이 현재의 겹침 규칙 아래에서 골든 정답을 압도한다는 것 — 은 평가 리포트에 정리되어 있다. 이 0을 "검색기가 숫자를 못 찾는다"로 읽으면 측정 인공물을 검색 실패로 오해하는 것이다. 분해의 역할은 실패의 위치를 짚는 데서 끝나고, 실패를 설명하는 것은 분해의 몫이 아니다.

### 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/evals/test_07_curation.py -q
```

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| `retrieval.json`에 곧바로 이어 붙인 생성 사례 | 후보는 `m3s` 네임스페이스에 살고 `m3c` id는 승격만이 발급한다. |
| 패러프레이즈된 근사 중복 질문 | 입장이 배치 내부와 커밋된 셋 양쪽에서 정규화 질문 충돌을 거부한다. |
| 조용한 승인 | 결정 없는 후보는 pending에 머물고, 결정 파일의 부재는 오류다. |
| 인증을 주장하는 승격 사례 | 승격은 `pending-author-approval`과 `human_verified=false`를 보존한다. |
| 부분 채점 위의 분해 | 사례-점수 짝짓기는 엄격한 전단사다. |

이 스위트는 전부 오프라인으로 돈다 — 큐레이션과 분해는 검색을 수행하지 않으므로 PostgreSQL이 필요 없다 — 그리고 핀 고정된 리비전에서 13 passed를 보고한다. 커밋된 후보 테스트는 `data/golden/candidates/r1.json`에 대해 모든 기계 게이트를 다시 돌리므로, 손상된 커밋 후보는 손상된 골든 사례와 같은 방식으로 빌드를 실패시킨다.

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 코드와 연결해 설명해 본다.

- **후보에 임시 `m3c` id 대신 별도 네임스페이스를 주는 이유는 무엇인가?**
  - **답:** `m3c` 네임스페이스는 동결된 정답지다. 검수되지 않은 사례가 골든 모양의 id를 달 수 있으면 측정된 진실과 입장하지 못한 주장을 기계적으로 가를 수단이 사라지고, 승격이 커밋된 id와 조용히 충돌할 수 있다.
- **입장이 배치 내부만이 아니라 커밋된 골든 셋을 상대로도 중복을 제거하는 이유는 무엇인가?**
  - **답:** 근사 중복 질문이나 재사용된 span 정체성은 같은 사실을 매크로 평균 지표에 두 번 넣는다. 검색기가 이미 다루는 것에 이중 가중치를 주면서 겉보기 성장을 부풀린다.
- **결정 하나의 부재는 pending일 뿐인데 결정 파일의 부재는 왜 오류인가?**
  - **답:** 결정 하나의 부재는 검수자가 남겨 두기로 선택한 상태지만, 파일 전체의 부재는 오타 난 경로와 구분되지 않는다. 이를 빈 집합으로 취급하면 잃어버린 결정 로그가 "아무것도 승인 안 됨"으로 읽히고, 검수가 있었는지에 대한 신호가 사라진다.
- **승격된 사례가 여전히 `pending-author-approval`인 이유는 무엇인가?**
  - **답:** 입장 결정은 후보가 풀에 들어갈 자격이 있는지를 판단했을 뿐이고, 저자의 span 수준 인증은 별도로 기록되는 사건이다. 승격이 인증을 부여하면 골든 계약이 지키려는 바로 그 출처를 파이프라인이 조작하게 된다.
- **분해가 부분 채점을 받아들이면 무엇을 보고할 수 있게 되는가?**
  - **답:** 우연히 점수를 받은 사례들만의 그룹 평균이다. 빠진 구성원이 숫자를 보이지 않게 움직이는데, 이는 산술은 맞아 보이면서 분류 체계로 거짓말하는 가장 강력한 방법이다.

---

[← 이전: 격리 실행과 CLI](08-evaluation-cli.md) · [모듈 개요](../03-build.md)
