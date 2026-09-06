# M8 개요 — 교차 언어 검색

> **`zero` 브랜치 참고:** 아래 완성 코드는 고정된 참조 목표이며 정식 파일은 직접 작성한다. 진행 상태: [모듈 플랜](../../project/module-plan.md).

코퍼스는 영어 SEC 10-K 공시 20건이고, 시스템의 어느 부분도 질의에 언어가 있다는 사실을 모른다. lexical 인덱스는 `english` 텍스트 검색 구성으로 만들어지므로 한국어 질문은 영어 스테머로 토큰화되고, 하이브리드 융합은 커밋된 숫자가 결정론적 토큰 해시 벡터뿐인 벡터 실험군 위에서 순위를 매기게 된다. M8은 "한국어 질문이 올바른 영어 구절을 찾아내는가"에 주장이 아니라 측정으로 답한다. 이중 언어 쌍둥이 골든 스위트, 무수정 M3 하니스를 통과하는 언어별 실행, 실험군으로 등록되는 언어 인식 질의 처리, 그리고 문서화된 개선 사이클 한 번을 이끄는 ko/en 동등성 게이트다.

## 마일스톤 계약

`twin golden suites -> language-sliced runs -> query-path arms -> a gated parity ratio`

이 모듈의 모든 숫자는 M3 평가 하니스를 수정하지 않고 만들어 낸다. 언어는 채점기 안의 새 차원이 아니다. 정답 span이 영어 스위트와 바이트 단위로 같은 스위트 위에서 같은 하니스를 한 번 더 실행하는 것일 뿐이다.

| 레이어 | 목표 | 핵심 파일 | 중단 조건 |
|---|---|---|---|
| M8.1 | 같은 불변 span 위에 놓인 한국어 쌍둥이 | `bilingual.py`, `retrieval_ko.json` | ko/en 지표 격차는 검색에 관한 사실일 수밖에 없다 |
| M8.2 | 붕괴를 숫자로 만든다 | `crosslingual.py`, `sbert.py` | 어떤 수정보다 먼저 "이전" 표가 존재한다 |
| M8.3 | 실험군으로 등록되는 언어 인식 질의 처리 | `language.py`, `translate.py`, `service.py` | 라우팅과 번역은 믿는 것이 아니라 측정되는 것이다 |
| M8.4 | 동등성 정의와 그 게이트 | `parity.py`, `crosslingual.py` | 비율에는 바닥과 허용 오차와 판정이 있다 |

## 여섯 문서 읽기 순서

1. [개요](00-README.md)는 체크포인트 경로와 그 중단 게이트를 준다. 2. [조사 결과](01-findings.md)는 이 모듈을 필요하게 만든 증거를 기록한다. 3. [명세](02-spec.md)는 쌍둥이 계약, 실험군 문법, 동등성 정의를 정의한다. 4. [빌드 가이드](03-build.md)는 M8.1 → M8.4를 따라가며 완성 참조 파일을 싣는다. 5. [버그](04-bugs.md)는 이 모듈이 실제로 밟은 함정을 기록한다. 6. [검증](05-verify.md)은 인수 명령과 측정된 표를 준다.

[`tutorial/`](tutorial/01-bilingual-golden.md) 아래의 튜토리얼 네 장은 각각 체크포인트 하나씩을 만든다.

## 정렬 가능한 체크포인트 경로

### M8.1 — 이중 언어 쌍둥이 골든 스위트

- 선행 조건: M1–M7 완료; `uv run pytest tests/evals -q` 통과, `data/golden/retrieval.json` 무변경.
- 파일: `data/golden/retrieval_ko.json`, `app/evals/bilingual.py`.
- 표준 명령:

  ```bash
  uv run pytest tests/crosslingual/test_01_bilingual.py -q
  ```

- 기대 결과: 네트워크 호출도 데이터베이스도 없이 `13 passed`.
- 중단 조건: 한국어 쌍둥이 28개가 무수정 골든 로더로 적재되고, 질문을 제외한 모든 필드에서 영어 짝과 일치한다.

### M8.2 — 어떤 수정보다 먼저 오는 측정

- 선행 조건: M8.1 완료.
- 파일: `app/evals/crosslingual.py`.
- 표준 명령:

  ```bash
  uv run pytest tests/crosslingual/test_02_crosslingual.py -q
  ```

- 기대 결과: 네트워크 호출도 데이터베이스도 없이 `23 passed`.
- 중단 조건: 실험군이 자신의 출처를 싣고, 쌍둥이 정렬 진단과 lexical 커버리지 진단이 측정된 숫자를 돌려주며, 두 언어 실행이 하나의 표로 렌더링된다.

### M8.3 — 라우팅과 번역

- 선행 조건: M8.2 완료.
- 파일: `app/retrieval/language.py`, `app/retrieval/translate.py`, `app/retrieval/service.py`, `app/config.py`, `app/evals/crosslingual.py`.
- 표준 명령:

  ```bash
  uv run pytest tests/crosslingual/test_03_language.py tests/crosslingual/test_04_translate.py -q
  ```

- 기대 결과: 네트워크 호출 없이 `22 passed`(감지와 라우팅 `15`개, 번역 `7`개).
- 중단 조건: 감지는 순수 문자 스캔이고, 라우팅은 `ComponentRankings`에서 관찰되며, 번역은 번역되지 않은 질의를 돌려주는 대신 fail-closed로 실패한다.

### M8.4 — 동등성 게이트와 개선 사이클

- 선행 조건: M8.3 완료.
- 파일: `app/evals/parity.py`, `app/evals/crosslingual.py`.
- 표준 명령:

  ```bash
  uv run pytest tests/crosslingual/test_05_parity.py -q
  ```

- 기대 결과: 네트워크 호출 없이 `11 passed`.
- 중단 조건: 비율은 지표별로 정의되고, 영어 슬라이스가 0이면 fail-closed로 실패하며, `--gate`는 무언가를 고쳤다고 주장하는 실험군만 심판한다.

## 오프라인 퀵스타트

```bash
uv run pytest tests/crosslingual -q
uv run ruff check app/evals app/retrieval tests/crosslingual
```

기대 결과: `69 passed`. 스위트 전체가 오프라인이고 결정론적이다 — PostgreSQL도, 네트워크도, API 키도 필요 없다.

## 측정 실행

```bash
docker compose up -d db
uv run python -m app.evals.crosslingual --provider deterministic --languages en ko --strategies lexical vector hybrid --handling direct
uv run python -m app.evals.crosslingual --provider sbert-multi --languages en ko --strategies vector hybrid --handling direct routed --gate
```

측정은 테스트가 아니라 언제나 커맨드라인 실행이다. M2에서 시드한 로컬 PostgreSQL이 필요하고, 자기 임시 코퍼스를 직접 만들며, 채워진 코퍼스 임베딩은 건드리지 않는다. 기록된 숫자는 [검증](05-verify.md)에 있다.
