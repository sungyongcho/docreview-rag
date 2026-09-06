# M3 개요 — 원문 근거 기반 검색 평가

> **`zero` 브랜치 참고:** 아래 완성 코드는 고정된 참조 목표이며 정식 파일은 직접 작성한다. 진행 상태: [모듈 플랜](../../project/module-plan.md).

M3는 M2의 인용 가능한 검색 표면을 재현 가능한 평가 시스템으로 전환합니다. 이 마일스톤은 **M3.1 골든 → M3.2 채점 → M3.3 회귀 → M3.4 어블레이션 실험/러너 → M3.5 큐레이션**이라는 하나의 정렬 가능한 경로로 진행됩니다. 각 계층은 정규 경로에 직접 작성하며 누적 테스트 게이트를 사용합니다.

## 마일스톤 계약

`raw-source golden spans -> deterministic metrics -> comparable baselines -> measured experiments`

커밋된 골든 세트는 에이전트가 선별했으며 작성자 승인을 기다리고 있습니다. 기계 검증을 통과해도 사람이 검증한 것으로 간주되지 않습니다. 커밋된 실험 증거는 격리된 임시 PostgreSQL 테이블에서 결정론적 임베딩 공급자를 사용했습니다. 유료 API 호출을 하지 않았으며 채워진 코퍼스의 임베딩을 교체하지도 않았습니다.

## 문서 6개 읽는 순서

1. [개요](00-README.md)는 정렬 가능한 경로와 중단 게이트를 설명합니다. 2. [측정 결과](01-findings.md)는 커밋된 산출물로 뒷받침되는 결과만 기록합니다. 3. [규범 명세](02-spec.md)는 안정적인 계약을 정의합니다. 4. [빌드 가이드](03-build.md)는 개념에서 코드와 누적 테스트 순서로 진행합니다. 5. [버그와 설계 함정](04-bugs.md)은 증상, 원인, 회귀 방지책을 기록합니다. 6. [검증](05-verify.md)은 인수 명령과 실패 분류 방법을 제공합니다.

포트폴리오에 제시할 비교 내용은 [평가 보고서](../../en/eval-report.md)에 있습니다. 원시 증거는 `data/eval_runs/` 아래에 있습니다.

## 정렬 가능한 M3 경로

### M3.1 — 골든 데이터

- **선행 조건:** 변경 불가능한 문서 20개 코퍼스와 그 매니페스트가 있어야 합니다.
- **파일:** `app/evals/types.py`, `app/evals/loader.py`, `app/evals/__init__.py`, `data/golden/retrieval.json`, `tests/evals/test_01_contract.py`, 그리고 `tests/evals/test_02_loader.py`.
- **정확한 명령:**

```bash
uv run pytest -o addopts="" tests/evals/test_01_contract.py tests/evals/test_02_loader.py -q
```

- **예상 결과:** `29 passed`. 28개 사례는 원문 근거가 있는 양성 사례 24개와 부재 사례 네 개로 로드됩니다.
- **중단 조건:** 원문 해시, 반개구간, 고유성, 분포 또는 검토 출처 확인 중 하나라도 실패하면 다음 단계로 진행하지 마세요.

### M3.2 — 결정론적 채점

- **선행 조건:** M3.1 단계가 통과하고 골든 범위가 원시 원문의 좌표로 유지되어야 합니다.
- **파일:** `app/evals/scoring.py`, 그리고 `tests/evals/test_02_scoring.py`.
- **정확한 명령:**

```bash
uv run pytest -o addopts="" tests/evals/test_01_contract.py tests/evals/test_02_loader.py tests/evals/test_02_scoring.py -q
```

- **예상 결과:** `55 passed`. Recall@k, Hit Rate@k, MRR은 결정론적인 상위 k개 원문 범위 관련성을 사용합니다.
- **중단 조건:** 청크 ID 순서를 바꾸었을 때 점수가 달라지거나, 반복 검색 결과가 골든 범위를 중복 집계하거나, 부재 사례가 검색 품질 지표에 포함되면 진행하지 마세요.

### M3.3 — 회귀 기준선

- **선행 조건:** M3.2 단계가 통과하고 게이트가 적용되는 모든 지표에 명시적인 방향과 허용 오차가 있어야 합니다.
- **파일:** `app/db/models.py`, `app/evals/regression.py`, 그리고 `tests/evals/test_03_regression.py`.
- **정확한 명령:**

```bash
uv run pytest -o addopts="" tests/evals/test_01_contract.py tests/evals/test_02_loader.py tests/evals/test_02_scoring.py tests/evals/test_03_regression.py -q
```

- **예상 결과:** `74 passed`. 구성은 정규 형태로 직렬화되며, 동일한 스위트와 구성을 가진 가장 최신 행만 비교 가능한 기준선이 됩니다.
- **중단 조건:** 지연 시간이 암묵적으로 클수록 좋은 값으로 취급되거나, 허용 오차 경계에서 실패하거나, 다른 구성이 기준선이 될 수 있다면 진행하지 마세요.

### M3.4 — 어블레이션 실험과 러너

- **선행 조건:** M3.3 단계가 통과하고, 루프백 PostgreSQL에 pgvector가 있으며, 공급자 선택이 명시적이어야 합니다. 기본 명령은 오프라인에서 결정론적으로 실행됩니다.
- **파일:** `app/evals/ablation.py`, `app/evals/retrieval_eval.py`, `app/evals/__main__.py`, 그리고 `tests/evals/test_04_ablation.py`부터 `tests/evals/test_06_postgres.py`.
- **정확한 명령:**

```bash
uv run pytest -o addopts="" tests/evals/test_01_contract.py tests/evals/test_02_loader.py tests/evals/test_02_scoring.py tests/evals/test_03_regression.py tests/evals/test_04_ablation.py tests/evals/test_05_runner.py tests/evals/test_06_postgres.py -q
uv run python -m app.evals --provider deterministic --target-text-chars 500 1200 --strategies lexical vector hybrid -k 5 --candidate-k 20 --rrf-k 60 --budget-queries 200 --artifact-dir data/eval_runs
```

- **예상 결과:** `100 passed`. 러너는 실험군별 산출물 열 개와 예산 산출물 하나를 작성하고, 공급자와 검토 출처를 표시하며, 두 청킹 실험군을 모두 측정합니다. 각 색인 실험군은 300초 미만이어야 하고, 90초 안에 순차 쿼리 200개를 처리해야 합니다.
- **중단 조건:** PostgreSQL이 임시 실험 테이블로 격리되지 않았거나, 공급자 식별 정보가 불명확하거나, 채워진 임베딩이 변경될 수 있거나, 출처 필드가 하나라도 없거나, 예산이 하나라도 실패하거나, 지표에 원시 산출물이 없으면 중단하세요.

### M3.5 — 골든 큐레이션

- **선행 조건:** M3.4 단계가 통과해야 합니다. 큐레이션과 분해는 오프라인으로 실행되며, 누적 명령의 라이브 테스트만 여전히 루프백 PostgreSQL이 필요합니다.
- **파일:** `app/evals/curation.py`, `app/evals/breakdown.py`, `data/golden/candidates/r1.json`, 그리고 `tests/evals/test_07_curation.py`.
- **정확한 명령:**

```bash
uv run pytest -o addopts="" tests/evals -q
```

- **예상 결과:** `113 passed`. 커밋된 후보는 모든 기계 게이트를 통과한 채 pending에 머물고, 승격은 명시적 승인에서만 `m3c` id를 발급하면서 승인 대기 출처를 보존하며, 분류 체계 분해는 케이스-점수의 엄격한 전단사를 강제합니다.
- **중단 조건:** 후보가 기계 게이트를 우회하거나, 결정 없는 후보가 승격될 수 있거나, 승격된 사례가 인증을 주장하거나, 분해가 부분 채점을 받아들이면 진행하지 마세요.

## 오프라인 빠른 시작

```bash
docker compose up -d db
uv run python -m app.evals --provider deterministic --target-text-chars 500 1200 --strategies lexical vector hybrid -k 5 --candidate-k 20 --rrf-k 60 --budget-queries 200 --artifact-dir data/eval_runs
```

체크인된 증거 세트의 타임스탬프는 `20260812T200916Z`와 `20260824T203336Z`이고, 평가 리포트는 더 새로운 세트를 읽습니다. 이 세트들의 결정론적 벡터는 재현성 기준선일 뿐 의미 품질의 대용 지표가 아니며, 채워진 코퍼스가 동일한 공급자를 사용한다는 증거도 아닙니다.

## 유료 공급자 게이트

커밋된 실행에서는 OpenAI를 호출하지 않았습니다. 작성자가 비용을 명시적으로 승인하고, 유효한 키와 모델 접근 권한을 확인하고, 별도 산출물 세트 생성을 수락한 뒤 사용할 수 있는 옵트인 명령은 다음과 같습니다.

```bash
OPENAI_API_KEY="your-key" uv run python -m app.evals --provider openai --target-text-chars 500 1200 --strategies lexical vector hybrid -k 5 --candidate-k 20 --rrf-k 60 --budget-queries 200 --artifact-dir data/eval_runs
```

이 명령도 임시 테이블을 사용하며 채워진 임베딩을 덮어쓰지 않습니다. 현재 비용 추정치와 수동으로 남아 있는 게이트는 [검증](05-verify.md#수동-및-유료-공급자-게이트)을 참고하세요.
