# M1.1 개요 — 10-K HTML → Item 섹션 파서

> **`zero` 브랜치 참고:** 아래 완성 코드는 고정된 참조 목표이며 정식 파일은 직접 작성한다. 진행 상태: [모듈 플랜](../../project/module-plan.md).

> 코드: `app/ingestion/parser.py`, `app/ingestion/xref.py` 코퍼스: NVDA · AMD · INTC · MU × 5년 = 20파일 M1.1 완료 기준: **20/20 파싱 성공, 경고 0건** · 당시 309 건의 테스트 통과 현재 전체 테스트 스위트 결과는 [`docs/00-README.md`](../00-README.md)에서 관리한다.

## 한 문장

**SEC는 10-K의 "내용"(Part/Item)을 정하지만 "HTML 레이아웃"은 정하지 않는다.** 그래서 파서는 회사마다 다른 문서 구조를 **프로파일(데이터)**로 관리하고, `segmentation.type` 하나가 파싱 전략을 선택해 결정론적으로 파싱한다.

## 파이프라인

```
① 정규화       HTML → 의미 있는 트리
② 블록화       트리 → 순서 있는 블록 리스트
③ 세그멘테이션  블록 리스트 → Item 섹션들      ← 프로파일이 지배하는 유일한 단계
④ 검증         섹션들이 말이 되는가
⑤ 출력         ParsedFiling
```

---

## 읽는 순서

| | 문서 | 무엇 | 언제 |
|---|---|---|---|
| 1 | [01-findings.md](01-findings.md) | **실측 F1~F15** | 먼저. 나머지 전부가 여기를 근거로 삼는다 |
| 2 | [02-spec.md](02-spec.md) | **무엇을 만드나** — 계약·타입·스키마·검증 기준 | 설계를 알고 싶을 때 |
| 3 | [03-build.md](03-build.md) | **어떻게 짜나** — 여덟 편으로 나눈 레이어 L1~L14 | 직접 짤 때 |
| 4 | [04-bugs.md](04-bugs.md) | **디버깅 이력 B01~B18** | 뭔가 이상할 때 / 왜 이렇게 짰나 |
| 5 | [05-verify.md](05-verify.md) | **검증** — 최종확인 ①~④ + pytest 대응표 | 맞는지 확인할 때 |

### 목적별 진입점

| 하려는 것 | 어디로 |
|---|---|
| 처음부터 직접 짜본다 | [03-build.md](03-build.md)의 튜토리얼 1번부터 순서대로 |
| 왜 이런 설계인지 알고 싶다 | [02-spec.md](02-spec.md) → 근거는 [01-findings.md](01-findings.md) |
| 결과가 이상하다 | [05-verify.md](05-verify.md)의 "틀렸을 때 의심할 곳" → [04-bugs.md](04-bugs.md) |
| 코드에 뭐가 있고 없는지 | [02-spec.md의 §9 "설계됨 · 미구현"](02-spec.md#9-설계됨--미구현) |

### 문서 사이의 규칙

- **실측은 [01-findings.md](01-findings.md)에만 있다.** 다른 문서는 `[F9]`로 링크만 한다.
- **버그 이력은 [04-bugs.md](04-bugs.md)에만 있다.** 다른 문서는 `[B04]`로 링크만 한다.
- **골든값은 `tests/ingestion/golden.py`에만 있다.** 문서의 표는 읽기용 사본이다.
- **강의 코드는 고정된 완성 참조에서 가져온다.** `zero`에서는 [03-build.md](03-build.md)의 코드 블록을 `scripts/check_doc_code.py`가 그 참조에서 채우고 대조한다. 로컬 재구현은 집중 테스트가 채점한다.
- **임계값은 참조 구현의 상수 선언에만 있다.** 산문에서 언급할 땐 `` `LAYOUT_CELL_CHARS`(300자) `` 처럼 이름과 값을 같이 적는다 — 같은 검사기가 값을 대조한다.

같은 사실을 두 곳에 적으면 반드시 갈라진다. 이 문서 묶음이 그 사고에서 나왔다.

`scripts/check_doc_code.py`가 세 가지를 한꺼번에 지킨다. `tests/test_doc_sync.py`가 pytest에서 돌리므로 **문서가 갈라지면 테스트가 깨진다**:

| 검사 | 무엇 | `--fix`로 고쳐지나 |
|---|---|---|
| 코드 블록 | `<!-- src: … -->`가 가리키는 고정 참조 심볼과 일치 | ✅ |
| 산문 상수 | `` `NAME`(값) ``의 값이 고정 참조 상수와 일치 | ✗ 주변 문장을 사람이 봐야 한다 |
| 링크·앵커 | 링크한 파일과 `#앵커`가 실제로 존재 | ✗ |

```bash
uv run python scripts/check_doc_code.py         # check all three contracts
uv run python scripts/check_doc_code.py --fix   # refresh blocks from the pinned reference
```

---

## 빨리 시작하기

```bash
uv sync --group dev

# Run all checks (includes parsing 20 documents, ~50 seconds)
uv run pytest

# Run only corpus-independent checks (~0.2 seconds)
uv run pytest tests/ingestion/test_02_rules.py

# Manual inspection
uv run python -m app.ingestion.parser --sections
uv run python -m app.ingestion.parser --coverage
```

### 개발 도구

`uv sync --group dev`로 들어오는 것들:

| 도구 | 쓰는 법 | 용도 |
|---|---|---|
| `pytest` | `uv run pytest` | 테스트 |
| `pytest-cov` | `uv run pytest --cov=app.ingestion.parser --cov=app.ingestion.xref --cov-report=term-missing tests/ingestion` | 미사용 분기와 CLI 경계 확인 ([왜 100%가 아닌가](02-spec.md#9-설계됨--미구현)) |
| `ruff` | `uv run ruff check .` / `uv run ruff format .` | 린트 + 포맷 |
| `ipython` | `uv run ipython` | 탐색용 REPL |

```bash
# Verify lecture code against the pinned reference
uv run python scripts/check_doc_code.py
uv run python scripts/check_doc_code.py --fix    # refresh blocks from the pinned reference
```

> **ruff 설정은 `pyproject.toml`의 `[tool.ruff]`에 있고 사용자 전역 설정을 대체한다**(병합 아님). 전역 프로파일(ANN + pydocstyle)을 이 코드베이스에 걸면 376건이 나오는데 거의 전부 노이즈라(테스트 함수 어노테이션 226건, `P` 픽스처 이름 48건) 실제로 고칠 것만 켜뒀다. 그리고 전역 설정에 `fix = true`가 있어서 **`ruff check`는 기본으로 파일을 고친다** — 확인만 하려면 `--no-fix`를 붙인다.

### 정규 파일 직접 구현하기

`app/ingestion/parser.py`를 직접 생성하고 수정합니다. 기본 테스트 대상은 이미 이 정규 경로를 가져옵니다.

```bash
uv run pytest
```

아직 만들지 않은 함수를 쓰는 테스트는 **실패가 아니라 건너뜀**이라 `pytest` 출력이 그대로 진행 상황판이 된다.

---

## 왜 기성 라이브러리를 안 썼나

sec-parser · edgartools 대신 BeautifulSoup으로 직접 구현 — ***교육·연습 목적***.

이 프로젝트가 보여주려는 핵심 난이도가 바로 수집과 표 처리이기 때문이다. 결과적으로 다룬 것:

- 문서 유형 분류와 전략 선택의 데이터화
- **문서 자체의 메타데이터**(Cross-Reference Index) 활용
- 검증 주도 폴백(점진적 기능 저하)
- 태그 유니온으로 잘못된 상태를 표현 불가능하게 만들기
- **실패를 감지하는 지표 설계** — 이게 제일 어려웠다

"RAG는 검색보다 적재가 어렵다"의 실증이다.

---

## 설계 원칙 요약

| 원칙 | 구현 |
|---|---|
| 규칙을 코드가 아니라 데이터로 | `rules`는 프로파일 JSON |
| 전략 선택도 데이터로 | `segmentation.type` 하나가 파싱 경로를 결정 |
| 싼 것부터, 실패가 감지될 때만 비싼 것으로 | 측정(0.1초) 우선. 점진적 기능 저하 |
| 상태를 잃지 않는다 | 판별 실패(`undefined`)도 저장 |
| 나쁜 규칙은 저장하지 않는다 | 재학습은 **검증을 통과했을 때만** 저장 |
| 연도 변경은 예외가 아니라 사실 | `profiles`의 독립 항목. 병합 규칙 없음 |
| 종속 관계는 태그 유니온으로 | `type`이 페이로드를 결정 |
| **실패를 감지할 수 있어야 폴백이 성립한다** | 검증 지표 4종 ([F14](01-findings.md#f14)) |

---

## 다음 (M1.2~)

모듈별 계약·레이어·완료기준은 [`docs/project/planning/04-build-plan.md`](../../project/planning/04-build-plan.md)에 있다.

**M1.2 — 표 → 마크다운** (`app/ingestion/tables.py`, 풀세트 6문서) L1 표 구조 감지 → L2 셀 정규화 → L3 마크다운 직렬화. [B04](04-bugs.md#b04) 수정으로 구식 3파일 포함 전부 표가 통짜로 보존돼 있어서, 재료는 이미 `Block.html`에 있다.

**M1.3 — 구조 기반 청킹 ★** (`app/ingestion/chunk.py`, 풀세트 6문서) L1 청크 유형(+스팬) → L2 텍스트 청커 → L3 **표 청커** → L4 문맥 헤더(서사 제목) → **L5 스팬 부여**. L5가 이번에 새로 들어온 것이다 — `Block`에 `source_pos`/`end_pos`를 얹어 청크가 **원문 문자 오프셋**을 갖게 한다. 이유는 [02-spec의 §7](02-spec.md#source_pos가-왜-중요해졌나--스팬-인용). 완료 기준에 **스팬 왕복 테스트**가 붙는다(원문 슬라이스가 청크 본문을 포함하는가).

**M1.4 — DB 적재** (`app/ingestion/seed.py`, 풀세트 6문서) `Chunk.source_sha256`/`start_char`/`end_char` 포함. `item_index`·`status`도 메타데이터로 ("Not applicable"을 근거 있게 답하기 위해). 재실행 안전.

미구현으로 남긴 파싱 경로(`sec_canonical`·`custom_title` 판별, LLM 캐스케이드)와 **위 마일스톤에서 추가될 필드**는 [02-spec.md의 §9](02-spec.md#9-설계됨--미구현)에 정리돼 있다. **도달하지 않는 코드를 먼저 짜면 검증할 방법이 없어서** 미룬 것이다.

---

## 이 문서 묶음은 템플릿이다

M1.2 이후 모든 마일스톤이 **이 6문서 구조와 테스트 하네스를 그대로 반복한다** ([`docs/project/planning/00-plan.md` §4](../../project/planning/00-plan.md)).

| 여기서 만든 것 | 다음 마일스톤에서 |
|---|---|
| 정식 `parser.py` 경로 | 정식 `chunk.py`, 검색, 평가 및 이후 모듈 경로 |
| 완료된 M1.1 구현 | 이후 모듈은 파일이 없는 상태에서 시작해 튜토리얼을 따라 직접 만든다 |
| `tests/support.py`의 `need()` | 그대로 재사용 — 미구현은 실패가 아니라 건너뜀 |
| `tests/ingestion/golden.py` | 영역마다 `tests/<area>/golden.py` |
| `scripts/check_doc_code.py` | 새 문서 디렉터리로 확장 |
| 6문서 세트 | M1.1~M1.4는 책임별 풀세트, 이후는 난도에 따라 풀세트 또는 축약형 |

**"같은 사실을 두 곳에 적으면 반드시 갈라진다"**는 규칙도 그대로 간다 — 실측은 `01-findings`에만, 버그는 `04-bugs`에만, 골든값은 `golden.py`에만, 코드는 소스에만.
