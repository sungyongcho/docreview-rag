# M3.1 튜토리얼 2 — 정답 파일을 믿을 수 있게 읽는다

튜토리얼 1은 유효한 사례가 무엇**인지**를 정의했다. `GoldenCase`는 JSON 한 건 안에서 보이는 것을 전부 검증한다 — 형태부터 라벨-정답 모순 같은 내부 정합성까지. 하지만 타입 검증이 증명할 수 없는 것이 하나 있다. 사례가 코퍼스에 대해 진실을 말하고 있는가다. 구조적으로 완벽하게 검증을 통과한 사례가 존재하지 않는 바이트를 인용하고 있을 수 있다.

같은 질문이 두 번 들어가 있는 경우, 좌표가 가리키는 filing이 코퍼스에 없는 경우, 해시는 적혀 있지만 그 파일이 그 사이에 바뀐 경우, 구간이 문서 끝을 넘어가는 경우, 구간 안에 HTML 태그만 있고 사람이 읽을 텍스트가 없는 경우가 그렇다.

pydantic은 이 중 어느 것도 잡지 못한다. 전부 **케이스 하나만 봐서는** 보이지 않고, 다른 사례·매니페스트·디스크 위 원문과의 관계에서만 드러나기 때문이다. 이 관계를 검사하는 계층이 없어도 평가는 그대로 돌고 숫자도 그대로 나온다. 깨진 사례가 영원히 검색 실패로 채점될 뿐이고, 성적표는 데이터 오류를 검색기 탓으로 돌린다. 이것을 막는 것이 이 파일의 일이며, 검증 가능한 불변조건 하나로 압축된다. **`load_golden_cases`가 반환하는 모든 사례는 자신이 인용한 바로 그 코퍼스 스냅샷과 바이트 단위 대조를 마친 상태다 — 로드할 때마다, 캐시된 신뢰 없이.**

**선행 조건:** 튜토리얼 1의 `app/evals/types.py` 작성이 끝나 있어야 한다. 그 집중 테스트는 이 문서 끝에서 패키지 공개 API가 열리는 시점부터 통과하기 시작한다.

### 로더가 거부하는 것

`data/golden/retrieval.json` → 엄격한 `GoldenCase` 파싱 → 매니페스트 조회 → 원문 바이트 SHA-256 검증 → UTF-8 반열린 범위 검증 → 불변 메모리 내 사례.

로더는 알 수 없는 필드, 강제 변환, 중복 키, 중복 ID 또는 정규화 후 중복되는 질문, 잘못된 해시, 경계를 벗어난 범위, 보이지 않는 증거를 거부한다. 좌표계가 달라지지 않도록 **원문 바이트를 UTF-8로 디코딩하기 전에** 해시한다.

해시 대상이 바이트라는 점이 중요하다. 디코딩한 문자열을 해시하면 같은 파일이라도 디코딩 처리 방식에 따라 다른 해시가 나올 수 있다. 바이트를 해시해야 해시 값이 파일 하나를 정확히 가리킨다.

`data/golden/retrieval.json` 자체의 이력도 알아야 신뢰 여부를 판단할 수 있다. 이 파일은 골든 큐레이션 단계가 만들었다. 에이전트가 불변 코퍼스를 대상으로 28개 사례를 작성했고, 기계 검증이 구조와 원문 무결성을 확인했으며, 전체 집합이 `human_verified` 거짓 상태로 — 즉 모든 사례가 작성자 승인 대기 상태로 — 커밋되었다. 이 상태를 기록하는 검토 큐와 상태를 옮기는 체크리스트가 `data/golden/REVIEW.md`다. 승인 상태는 작성자만, 검토를 거친 변경으로만 바꾼다. 로더는 두 상태를 구분하지 않는다. 승인 전이든 후든 로드할 때마다 같은 검증을 수행한다.

### 무엇을 작성하고 어디를 직접 구현할까

`app/evals/loader.py`를 여섯 단계로 작성하고, 마지막에 패키지 공개 API를 정의한다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| 모듈 헤더와 경로 상수 | **구조 작성** | 기본 경로가 코드에 있고 호출자가 덮을 수 있다는 것 |
| `GoldenDataError` | **설계 결정 확인** | 데이터 오류를 한 예외로 모으는 이유 |
| JSON 읽기와 중복 키 거부 | 파싱 가드를 **직접 구현** | 표준 JSON 파서가 조용히 버리는 것 |
| 사례 간 유일성 | 배치 불변조건을 **직접 구현** | 파일 하나로는 볼 수 없는 오류 |
| 매니페스트 조회 | **필드 매핑 작성 후 경계 변환 검토** | 정답이 실제 코퍼스와 이어지는 지점 |
| 원문 대조 | 핵심 검증 로직을 **직접 구현** | 해시·범위·가시성 세 관문 |

### 1. 모듈 헤더와 기본 경로

#### `app/evals/loader.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** import 목록에서 `BeautifulSoup`이 필요한 이유를 확인한다. 이 로더가 원문 HTML을 직접 읽는다는 뜻이다.

```python
"""Load strict golden cases and bind every positive span to the raw corpus."""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from pydantic import TypeAdapter, ValidationError

from app.evals.types import GoldenCase
```

#### `app/evals/loader.py` 확장 — 경로 상수와 데이터 오류

**학습 행동 — 설계 결정 확인:** 상수 네 개와 예외 하나를 작성한다. 이 예외가 `ValueError`를 상속하는 이유를 설명할 수 있어야 한다.

<!-- src: app/evals/loader.py::REPO_ROOT,GoldenDataError -->
```python
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDEN_PATH = REPO_ROOT / "data" / "golden" / "retrieval.json"
DEFAULT_MANIFEST_PATH = REPO_ROOT / "data" / "corpus" / "manifest.json"
GOLDEN_CASES = TypeAdapter(list[GoldenCase])


class GoldenDataError(ValueError):
    """A golden file or its cited source snapshot violates the M3 contract."""
```

**코드에서 꼭 볼 것**

- `REPO_ROOT`를 `__file__` 기준으로 계산한다. 평가를 어느 디렉터리에서 실행하든 기본 경로가 같은 위치를 가리킨다.
- `GOLDEN_CASES = TypeAdapter(list[GoldenCase])`를 모듈 수준에서 한 번만 만든다. `TypeAdapter` 생성은 스키마를 컴파일하는 비용이 있으므로, 파일마다 새로 만들면 같은 컴파일을 반복한다.
- `GoldenDataError`는 `ValueError`를 상속한다. 호출자는 이 모듈을 몰라도 `ValueError`로 잡을 수 있고, 데이터 문제만 따로 처리할 때는 이 예외 타입으로 구분할 수 있다.

> **개념 — 데이터 오류를 한 표면으로 모은다**
>
> 로더가 파일을 거부하는 이유는 열 가지가 넘는다. 읽을 수 없는 바이트, 깨진 JSON, 중복 키, pydantic 검증 실패, 없는 filing, 틀린 해시. 호출자에게 중요한 것은 어느 라이브러리가 문제를 발견했는지가 아니라 단 하나의 질문이다. 데이터가 잘못됐는가, 코드가 잘못됐는가. 모든 데이터 오류를 GoldenDataError 하나로 모으면 except 절 하나로 이 질문에 답할 수 있다.
>
> 진입점이 pydantic의 ValidationError를 그대로 흘려보내지 않고 감싸는 이유도 같다. ValidationError가 밖으로 새면 구현 선택이 모든 호출자에게 번진다. 평가 CLI와 테스트가 예외를 잡기 위해 pydantic을 import해야 하고, 검증 라이브러리를 바꾸는 순간 전부 깨진다. 원래 예외를 원인으로 연결해 감싸면 상세 내용은 트레이스백에 그대로 남고, 공개 타입은 이 모듈의 것으로 유지된다.
>
> 기각한 대안 — 오류 종류마다 예외 클래스를 두는 계층 구조 — 은 여기서 아무것도 사 주지 않는다. 틀린 해시와 중복 키에서 다르게 복구하는 호출자는 없다. 둘 다 멈추고 데이터를 손으로 고치라는 뜻이다. 파일과 사례를 지목하는 메시지를 가진 타입 하나가 수리 작업에 필요한 정확한 해상도다.

### 2. 표준 JSON 파서가 조용히 버리는 것

`json.loads`는 중복 키를 오류로 처리하지 않는다. `{"id": "m3c-01", "id": "m3c-02"}`를 넘기면 마지막 값만 남기고 앞의 값을 버린다. 직접 확인할 수 있다.

```bash
python3 -c "import json; print(json.loads('{\"id\": \"m3c-01\", \"id\": \"m3c-02\"}'))"
```

출력은 `{'id': 'm3c-02'}`다. 경고도 오류도 없다. 첫 번째 쌍은 그냥 사라지고, 만들어진 딕셔너리에는 그 쌍이 존재했다는 흔적이 남지 않는다.

> **개념 — 중복 키는 합법적인 JSON이고, 그래서 문제다**
>
> JSON 명세는 객체의 이름이 유일해야 한다(must)고 말하지 않는다. 유일한 것이 좋다(should)고만 말한다. 명세를 만족하는 파서는 중복을 거부해도, 첫 값을 남겨도, 마지막 값을 남겨도 된다. 파이썬은 마지막 값을 조용히 남긴다. 그러니 이것은 우회하면 되는 파서 버그가 아니다. 허용된 동작이고, 정보가 아직 존재하는 유일한 시점에 막아야 하는 위험이다.
>
> 그 시점은 쌍들이 딕셔너리로 합쳐지기 전이다. 훅은 파싱된 키·값 목록을 그대로 받는다. 합쳐진 뒤에는 두 중복이 슬롯 하나로 붕괴해서, pydantic이든 유일성 검사든 어떤 후속 검증도 값이 덮어써졌다는 사실을 알아낼 수 없다.
>
> 현실적인 사고는 id 중복이 아니다. 구간을 손으로 고치다가 끝 오프셋 줄을 복사해 좌표를 조정하고 옛 줄을 지우는 것을 잊는 경우다. 파서는 뒤에 온 값을 조용히 남긴다. 고쳤다고 생각한 필드는 사라졌는데 사례는 여전히 검증을 통과하고, 평가는 아무 말 없이 엉뚱한 구간을 기준으로 채점한다.

정답 파일에서 이 침묵은 치명적이다. **필드나 케이스를 조용히 잃은 파일이 오류 없이 로드되고, 평가는 그럴듯한 숫자를 그대로 출력하며, 그 숫자가 의도한 스위트 전체를 잰 것이 아니라는 표시는 어디에도 남지 않는다.**

#### `app/evals/loader.py` 확장 — JSON 읽기 가드

**학습 행동 — 파싱 가드 구현:** `object_pairs_hook`이 어떤 형태의 인자를 받는지 확인한 뒤 직접 구현한다.

<!-- src: app/evals/loader.py::_reject_duplicate_keys,_golden_files -->
```python
def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GoldenDataError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except GoldenDataError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoldenDataError(f"cannot read valid UTF-8 JSON from {path}: {exc}") from exc


def _golden_files(path: Path) -> list[Path]:
    if path.is_dir():
        files = sorted(path.glob("*.json"))
        if not files:
            raise GoldenDataError(f"no golden JSON files found in {path}")
        return files
    return [path]
```

**코드에서 꼭 볼 것**

- `object_pairs_hook=_reject_duplicate_keys`는 딕셔너리로 합치기 **전의** 키·값 쌍 목록을 받는다. 중복 키를 확인할 수 있는 시점은 이때뿐이고, 파싱이 끝난 딕셔너리에는 중복의 흔적이 남지 않는다.
- `except GoldenDataError: raise`가 다른 예외 절보다 먼저 온다. 이 절이 없으면 훅이 던진 데이터 오류가 아래 예외 절에 잡혀 JSON을 읽을 수 없다는 다른 원인의 메시지로 바뀐다.
- `_golden_files`는 디렉터리도 받는다. 정답을 여러 파일로 나눌 수 있지만 빈 디렉터리는 거부한다. 사례 0건으로 평가가 통과하는 상태를 막기 위해서다. 파일 목록을 정렬하는 것도 의도된 결정이다. glob의 순서는 파일시스템에 따라 달라지므로, 정렬해야 사례 순서가 — 그리고 깨진 디렉터리가 처음 내는 오류가 — 어느 기계에서나 같아진다.

### 3. 파일 하나만 봐서는 볼 수 없는 오류

#### `app/evals/loader.py` 확장 — 사례 간 유일성

**학습 행동 — 배치 불변조건 구현:** 세 개의 집합을 각각 왜 추적하는지 확인하며 구현한다.

<!-- src: app/evals/loader.py::_validate_unique_cases -->
```python
def _validate_unique_cases(cases: Iterable[GoldenCase]) -> None:
    ids: set[str] = set()
    questions: set[str] = set()
    answer_identities: set[tuple[str, str, int, int]] = set()
    for case in cases:
        if case.id in ids:
            raise GoldenDataError(f"duplicate golden case id: {case.id}")
        ids.add(case.id)

        normalized = " ".join(case.question.casefold().split())
        if normalized in questions:
            raise GoldenDataError(f"duplicate normalized question: {case.question}")
        questions.add(normalized)

        for answer in case.answers:
            identity = (
                answer.doc_id,
                answer.source_sha256,
                answer.start_char,
                answer.end_char,
            )
            if identity in answer_identities:
                raise GoldenDataError(f"duplicate answer span identity in {case.id}")
            answer_identities.add(identity)
```

**코드에서 꼭 볼 것**

- 질문을 원문 그대로 비교하지 않고 `" ".join(case.question.casefold().split())`로 정규화해 비교한다. **대소문자와 공백만 다른 두 질문은 같은 질문이므로, 둘 다 집계하면 그 주제 하나가 평가 점수에 두 번 반영된다.**
- 정답 구간의 유일성은 **사례를 가로질러** 확인한다. `GoldenCase` 안의 검증기는 한 사례 내부의 중복만 본다. 서로 다른 두 사례가 같은 구간을 정답으로 쓰면, 그 구간을 찾기 쉬울 때 점수가 두 사례에서 함께 올라간다.
- 예외 메시지에 어느 사례에서 문제가 생겼는지가 들어 있다. 스물여덟 개 사례 중 하나를 찾아야 하는 상황에서 이 정보가 수정 지점을 결정한다.

> **개념 — 준중복 질문이 평균에 하는 일**
>
> 이 스위트가 나중에 보고하는 지표는 매크로 평균이다. 사례마다 동등한 한 표를 행사하고, 스위트의 결론은 그 표들의 평균이다. 대소문자나 공백만 다른 두 질문은 하나의 사실이 ID 두 개를 달고 있는 것이다. 둘 다 남겨 두면 그 사실 하나가 두 표를 행사한다. 검색기가 거기서 성공하든 실패하든 두 배로 집계되고, 다른 모든 사실은 한 번씩만 집계된다. 평균은 코퍼스를 설명하기를 멈추고 중복이라는 사고를 설명하기 시작한다.
>
> casefold와 공백 축약이 정규화의 전부인 것은 의도적이다. 단순 문자열 비교가 놓치는 중복 — 대문자 하나 바뀐 재입력, 두 번 친 공백 — 은 잡아내면서, 진짜로 다른 두 질문을 하나로 합치는 일은 없다. 어간 추출이나 문장부호 제거까지 가면 오합병이 생길 수 있고, 오합병은 실제 사례 하나를 조용히 지운다.
>
> 매크로 평균 자체의 정의와 그것이 지표 분해능에 갖는 함의는 채점 튜토리얼의 몫이다.

### 4. 정답이 실제 코퍼스와 이어지는 지점

결합의 반대편 끝은 `data/corpus/manifest.json`이다. 이 파일은 M1의 EDGAR 다운로드 단계가 공시 자료 20건을 내려받던 그 시점에 한 번 기록했다 — filing마다 한 항목씩, 티커·날짜·접수 번호·로컬 파일 경로·원본 URL이 담긴다. 코퍼스의 출생 기록인 셈이다. 아무것도 이 파일을 다시 생성하지 않고, 여기 적힌 filing들은 그 시점부터 불변으로 취급된다. 로더가 이 파일을 읽는 목적은 하나다. 골든 사례에 적힌 `doc_id`를, 그 좌표를 잰 바로 그 파일의 경로로 바꾸는 것이다.

#### `app/evals/loader.py` 확장 — 매니페스트 조회

**학습 행동 — 필드 매핑 작성 후 경계 변환 검토:** `_resolve_source_path`의 탐색 순서와 `doc_id` 조립 규칙을 확인하며 작성한다.

<!-- src: app/evals/loader.py::_resolve_source_path,_manifest_sources -->
```python
def _resolve_source_path(file_name: str, manifest_path: Path) -> Path:
    source = Path(file_name)
    if source.is_absolute() and source.is_file():
        return source

    bases = [Path.cwd(), REPO_ROOT, manifest_path.resolve().parent]
    bases.extend(manifest_path.resolve().parents)
    for base in bases:
        candidate = (base / source).resolve()
        if candidate.is_file():
            return candidate
    raise GoldenDataError(f"manifest source file does not exist: {file_name}")


def _manifest_sources(manifest_path: Path) -> dict[str, Path]:
    payload = _read_json(manifest_path)
    if not isinstance(payload, list):
        raise GoldenDataError("corpus manifest root must be a JSON array")

    sources: dict[str, Path] = {}
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise GoldenDataError(f"manifest entry {index} must be an object")
        try:
            ticker = entry["ticker"]
            report_date = entry["report_date"]
            file_name = entry["file"]
        except KeyError as exc:
            raise GoldenDataError(f"manifest entry {index} is missing {exc.args[0]}") from exc
        if not all(isinstance(value, str) and value for value in (ticker, report_date, file_name)):
            raise GoldenDataError(f"manifest entry {index} has invalid identity fields")
        if len(report_date) < 4 or not report_date[:4].isdigit():
            raise GoldenDataError(f"manifest entry {index} has an invalid report_date")

        doc_id = f"{ticker}-FY{report_date[:4]}"
        if doc_id in sources:
            raise GoldenDataError(f"duplicate manifest document id: {doc_id}")
        sources[doc_id] = _resolve_source_path(file_name, manifest_path)
    return sources
```

**코드에서 꼭 볼 것**

- `doc_id`를 `f"{ticker}-FY{report_date[:4]}"`로 **조립한다.** 매니페스트에 `doc_id` 필드가 없기 때문이다. 이 조립 규칙이 M1.4의 규칙과 어긋나면 정답이 대조할 문서를 찾지 못한다. 매니페스트에 `doc_id` 필드를 저장하는 편이 더 단순해 보이지만, 그것은 파생 가능한 정체성의 두 번째 사본이다. 두 사본이 어긋나는 순간 모든 해시 검사가 엉뚱한 파일을 쫓는다. 조립 규칙 하나를 모든 곳에서 쓰면 규칙이 자기 자신과 어긋날 수 없다.
- `_resolve_source_path`는 여러 기준 디렉터리를 순서대로 시도한다. 매니페스트의 경로가 상대 경로여서 실행 위치에 따라 해석이 달라지므로, 후보를 모두 확인하고 없으면 거부한다.
- 매니페스트에 같은 `doc_id`가 두 번 나오면 거부한다. 이 검사가 없으면 뒤의 항목이 앞의 항목을 덮어써서 정답이 다른 파일과 대조된다.

### 5. 해시·범위·가시성 세 관문

문서 첫머리의 불변조건이 실제로 집행되는 곳이 여기다. 양성 정답마다 문서 하나, 스냅샷 해시 하나, 문자 오프셋 두 개가 적혀 있고, 세 관문은 이 기록이 여전히 현실과 일치하는지를 순서대로 검사한다.

> **개념 — doc id에서 바이트까지, 출처 사슬**
>
> 해시 관문은 네 개의 고리로 읽어야 한다. doc id가 매니페스트 항목을 지목하고, 매니페스트 항목이 디스크의 파일을 지목하고, 파일이 바이트를 내놓고, 그 바이트의 SHA-256이 골든 사례에 기록된 해시와 일치해야 한다. 네 고리 전부를 로드할 때마다 검사한다. 어느 고리든 끊기면 — 항목이 없든, 파일이 없든, 바이트가 바뀌었든 — 로드는 계속 진행하는 대신 소리 내어 거부한다.
>
> 이 사슬이 막는 실패는 코퍼스 표류다. filing 하나를 다시 받아 한 바이트라도 달라지면 — 헤더 하나, 새로 서빙된 템플릿 하나 — 그 filing을 인용하는 모든 구간이 더는 존재하지 않는 좌표계 위에서 잰 값이 된다. 해시 관문이 없으면 아무것도 실패하지 않는다. 오프셋은 새 텍스트 안 어딘가를 여전히 가리키고, 구간은 조용히 엉뚱한 문자들을 지목하며, 검색은 그것을 영영 맞힐 수 없고, 그 사례들은 영원히 못 찾는 것으로 채점된다. 성적표는 검색 회귀를 보고하지만 진실은 낡은 인용이다.
>
> 관문이 있으면 같은 표류가 사례와 문서를 지목하는 로드 시점의 요란한 오류 하나가 된다. 차이는 문제의 존재 여부가 아니다. 문제가 눈에 보이는 데이터 오류로 드러나느냐, 영구적인 지표 거짓말로 숨느냐다.

#### `app/evals/loader.py` 확장 — 원문 대조

**학습 행동 — 검증 로직 구현:** 세 관문을 순서대로 직접 구현한다. 각 관문이 없을 때 평가 결과가 어떻게 잘못되는지 설명할 수 있어야 한다.

<!-- src: app/evals/loader.py::validate_golden_sources -->
```python
def validate_golden_sources(
    cases: Iterable[GoldenCase],
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> None:
    """Verify each positive span against its exact UTF-8 source and SHA-256."""
    sources = _manifest_sources(Path(manifest_path))
    cache: dict[str, tuple[str, str]] = {}

    for case in cases:
        for answer in case.answers:
            source_path = sources.get(answer.doc_id)
            if source_path is None:
                raise GoldenDataError(f"{case.id} cites unknown corpus document {answer.doc_id}")
            if answer.doc_id not in cache:
                try:
                    source_bytes = source_path.read_bytes()
                    raw_source = source_bytes.decode("utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    raise GoldenDataError(
                        f"cannot read UTF-8 source for {answer.doc_id}: {exc}"
                    ) from exc
                cache[answer.doc_id] = (
                    raw_source,
                    hashlib.sha256(source_bytes).hexdigest(),
                )

            raw_source, source_sha256 = cache[answer.doc_id]
            if answer.source_sha256 != source_sha256:
                raise GoldenDataError(f"{case.id} source hash does not match {answer.doc_id}")
            if answer.end_char > len(raw_source):
                raise GoldenDataError(
                    f"{case.id} span ends beyond {answer.doc_id}: "
                    f"{answer.end_char} > {len(raw_source)}"
                )
            evidence = BeautifulSoup(
                raw_source[answer.start_char : answer.end_char],
                "html.parser",
            ).get_text(" ", strip=True)
            if not evidence:
                raise GoldenDataError(
                    f"{case.id} span has no visible source evidence in {answer.doc_id}"
                )
```

**코드에서 꼭 볼 것**

- `cache`는 문서별로 원문과 해시를 한 번만 계산한다. 커밋된 집합의 양성 사례 24개가 20개 filing에 걸쳐 34개 구간을 인용하고 filing 하나가 원문 HTML 2~5 MB이므로, 캐시는 34번이 될 읽기·해시 작업을 filing당 한 번, 정확히 20번으로 줄인다.
- 해시는 `source_bytes`에서 계산하고, 길이 검사는 디코딩된 `raw_source`에서 수행한다. **좌표가 문자 단위이므로 길이는 문자로 재고, 파일의 신원은 바이트로 재야 한다. 두 기준을 섞으면 멀티바이트 문자가 있는 문서에서 경계 검사와 실제 좌표가 어긋난다.**
- 마지막 관문은 `BeautifulSoup`으로 태그를 제거한 뒤 남는 텍스트가 비어 있으면 거부한다. 좌표가 HTML 태그 사이의 공백만 가리키는 경우가 여기에 해당한다. **이 구간은 형식적으로 유효해서 앞의 두 관문을 통과하지만, 검색이 반환할 수 있는 텍스트가 없으므로 어떤 구현으로도 맞힐 수 없는 정답이 된다.**

> **개념 — 보이는 증거, 사람이 따라갈 수 있는 인용**
>
> 원문은 HTML이고 골든 오프셋은 그 원문 문자열 위에서 잰 값이다. 그래서 문자 구간은 형식적으로 완벽하면서도 통째로 마크업 안에 떨어질 수 있다. 태그 안쪽, style 속성이 이어지는 구간, 요소 사이의 공백 같은 자리다. 그런 구간을 독자가 보는 방식으로 렌더링하면 아무것도 남지 않는다.
>
> 이런 사례는 틀린 정답보다 나쁘다. 인용을 따라간 검토자는 filing을 열고 읽을 것이 글자 그대로 아무것도 없음을 발견하므로, 그 사례는 정직하게는 승인될 수 없다. 그리고 보이는 텍스트를 색인하는 검색기는 그 구간의 증거를 반환할 방법이 없으므로, 사례는 구조적으로 이길 수 없는 문제가 된다. 앞으로의 모든 평가에서 설명되지 않는 영구 0점이다.
>
> 구간의 태그를 벗겨 내고 텍스트가 남는지 묻는 것은 진짜 질문의 가장 값싼 형태다. 이 인용을 따라간 사람 눈에 무엇이라도 보이는가. 답이 비어 있으면 좌표가 가리키는 것은 증거가 아니라 마크업이고, 잘못된 쪽은 검색기가 아니라 데이터다.

### 6. 진입점과 공개 표면

#### `app/evals/loader.py` 완성 — 로드 진입점

**학습 행동 — 구조 작성 후 호출 순서 검토:** 세 단계를 이 순서로 호출해야 하는 이유를 설명할 수 있어야 한다.

<!-- src: app/evals/loader.py::load_golden_cases -->
```python
def load_golden_cases(
    path: str | Path = DEFAULT_GOLDEN_PATH,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> list[GoldenCase]:
    """Load one file or a directory of files and validate all source citations."""
    cases: list[GoldenCase] = []
    for golden_path in _golden_files(Path(path)):
        payload = _read_json(golden_path)
        if not isinstance(payload, list):
            raise GoldenDataError(f"golden file root must be a JSON array: {golden_path}")
        try:
            cases.extend(GOLDEN_CASES.validate_python(payload))
        except ValidationError as exc:
            raise GoldenDataError(f"invalid golden cases in {golden_path}: {exc}") from exc

    _validate_unique_cases(cases)
    validate_golden_sources(cases, manifest_path)
    return cases
```

**코드에서 꼭 볼 것**

- 호출 순서는 파싱, 사례 간 유일성, 원문 대조다. **원문 대조는 파일 I/O와 해시 계산을 포함해 가장 비싸므로, 비용이 낮은 검사로 먼저 거부할 수 있는 데이터를 걸러낸다.**
- 모든 파일을 읽어 `cases`에 모은 **뒤에** 유일성을 검사한다. 파일별로 검사하면 파일을 가로지르는 중복을 놓친다. 사례를 두 번째 파일로 복사하고 원본을 지우지 않았을 때, 나뉜 정답 집합이 만들어 내는 바로 그 중복이다.

이 함수가 하지 않는 일도 봐야 한다. 판정 결과를 캐시하지 않는다. 마커 파일도, 검증 시각 기록도, 지난 실행을 신뢰하는 지름길도 없다. 호출할 때마다 20개 filing 전체, 합쳐서 약 58.5 MB를 다시 읽고 다시 해시한다. 이 비용은 의도된 것이다. 캐시된 판정은 그 뒤로 아무것도 안 바뀌었다는 가정만큼만 유효한데, 바로 그 명제가 이 로더가 가정하는 대신 증명하려고 존재하는 것이다. 평가 실행은 스위트를 한 번 로드하므로 비용도 실행당 한 번만 낸다.

#### `app/evals/__init__.py` 생성 — M3 공개 API

**학습 행동 — 구조 작성:** 공개하는 이름과 공개하지 않는 이름을 구분해 확인한다.

```python
"""Public contracts and loader for the M3 evaluation milestone."""

from app.evals.loader import (
    DEFAULT_GOLDEN_PATH,
    DEFAULT_MANIFEST_PATH,
    GoldenDataError,
    load_golden_cases,
    validate_golden_sources,
)
from app.evals.types import (
    ExpectedLabel,
    GoldenCase,
    GoldenCategory,
    GoldenFacet,
    GoldenSpan,
    GoldenTag,
)

__all__ = [
    "DEFAULT_GOLDEN_PATH",
    "DEFAULT_MANIFEST_PATH",
    "ExpectedLabel",
    "GoldenCase",
    "GoldenCategory",
    "GoldenDataError",
    "GoldenFacet",
    "GoldenSpan",
    "GoldenTag",
    "load_golden_cases",
    "validate_golden_sources",
]
```

밑줄로 시작하는 헬퍼는 하나도 공개하지 않는다. 이후 모듈이 의존해도 되는 표면은 이 목록으로 한정된다.

### 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/evals/test_01_contract.py tests/evals/test_02_loader.py -q
```

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 중복된 JSON 키 | 손으로 편집하다 생긴 덮어쓰기가 조용히 통과하지 않는다. |
| 대소문자만 다른 같은 질문 | 한 주제가 평가에서 이중으로 가중되지 않는다. |
| 사례를 가로지르는 같은 정답 구간 | 쉬운 구간 하나가 점수를 부풀리지 않는다. |
| 바뀐 원문 바이트 | 좌표가 다른 스냅샷을 가리킨 채 평가가 돌지 않는다. |
| 문서 끝을 넘는 구간 | 정답이 존재하지 않는 위치를 가리키지 않는다. |
| 태그만 있고 텍스트가 없는 구간 | 검색이 맞힐 수 없는 정답이 데이터에 남지 않는다. |

구현이 끝나면 선택한 테스트가 모두 통과해야 한다. 데이터셋은 전체 28개 사례이고 그중 양성이 24개, 부재가 4개다. 양성 사례들이 합쳐서 34개의 정답 구간을 인용하고, 공시 자료 20개가 모두 양성 근거에 등장하며, 티커 균형도 정확하다 — AMD, INTC, MU, NVDA 각각 양성 6개씩이다. 커밋된 파일에서 직접 세어 볼 수 있다.

```bash
python3 -c "import json; g = json.load(open('data/golden/retrieval.json')); pos = [c for c in g if c['answers']]; spans = [a for c in pos for a in c['answers']]; print(len(g), len(pos), len(g) - len(pos), len({a['doc_id'] for a in spans}), len(spans))"
```

출력은 `28 24 4 20 34`다. 테스트는 같은 수치를 `tests/evals/golden.py`의 상수로 고정해 두므로, 골든 파일을 슬쩍 고치면 지표가 왜곡되기 전에 스위트가 먼저 실패한다. 모든 사례는 여전히 에이전트 큐레이션 상태로 작성자 승인을 기다린다 — 사례별 큐는 `data/golden/REVIEW.md`에 기록되어 있다 — 그리고 커밋된 구간 중 가장 넓은 것이 2,280자로, 그 기록이 약속하는 2,500자 상한 안에 있다.

스키마, 원문 해시, 범위, 분포, 검토 출처 단언이 실패하거나 필수 심볼 누락으로 건너뛰면 M3.1을 완료로 판단하지 않는다.

해시나 경계 검사가 실패하면 데이터를 수정하기 전에 매니페스트의 경로 해석부터 확인한다. 원문 바이트를 UTF-8 디코딩 전에 해시하는지, 오프셋이 반열린 구간으로 유지되는지를 함께 본다. 현재 청커의 경계에 맞추려고 골든 구간을 옮기지 않는다.

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 검증 단계와 연결해 설명해 본다.

- **`object_pairs_hook` 없이 정답 파일을 읽으면 무엇을 놓치는가?**
  - **답:** 표준 JSON 파서는 중복 키의 마지막 값만 조용히 남기므로 중복을 놓친다. 훅은 딕셔너리로 합치기 전의 키 쌍을 보여 준다.
- **질문을 정규화해서 비교하는 이유는 무엇인가?**
  - **답:** 대소문자나 공백만 다른 질문은 논리적으로 중복이며, 그대로 두면 한 주제가 평가에서 두 배의 가중치를 받는다.
- **해시는 바이트로, 길이 검사는 문자로 하는 이유는 무엇인가?**
  - **답:** 파일 정체성은 정확한 바이트를 대상으로 해야 하지만 저장된 좌표는 디코딩된 문자 수를 센다. 한 단위를 둘 다에 쓰면 멀티바이트 텍스트에서 어긋난다.
- **태그만 있는 구간을 거부하지 않으면 어떤 사례가 데이터에 남는가?**
  - **답:** 좌표 형식은 유효하지만 HTML 태그나 공백만 담아, 검색이 눈에 보이는 증거로 반환할 수 없는 사례가 남는다.
- **원문 대조를 유일성 검사보다 뒤에 두는 이유는 무엇인가?**
  - **답:** 유일성 검사는 비용이 작은 파일 간 검사이므로, 중복된 잘못된 데이터를 먼저 거부한 뒤에 비싼 원문 읽기와 해시 계산을 해야 한다.

---

[← 이전: 골든 타입](01-golden-types.md) · [모듈 개요](../03-build.md) · [다음: 채점 →](03-scoring.md)
