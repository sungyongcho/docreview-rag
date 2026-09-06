# M3 검증

의존성 순서대로 인수를 실행하세요. 첫 실패에서 중단해야 합니다. 이후 계층의 출력으로 하위 계층 계약을 복구할 수 없습니다.

## 1. 누적 계층 테스트

```bash
uv run pytest -o addopts="" tests/evals/test_01_contract.py tests/evals/test_02_loader.py -q
uv run pytest -o addopts="" tests/evals/test_01_contract.py tests/evals/test_02_loader.py tests/evals/test_02_scoring.py -q
uv run pytest -o addopts="" tests/evals/test_01_contract.py tests/evals/test_02_loader.py tests/evals/test_02_scoring.py tests/evals/test_03_regression.py -q
uv run pytest -o addopts="" tests/evals/test_01_contract.py tests/evals/test_02_loader.py tests/evals/test_02_scoring.py tests/evals/test_03_regression.py tests/evals/test_04_ablation.py tests/evals/test_05_runner.py tests/evals/test_06_postgres.py -q
uv run pytest -o addopts="" tests/evals -q
```

예상 누적 결과:

| 계층 | 예상 결과 |
|---|---:|
| M3.1 골든 | 29개 통과 |
| M3.2 채점 | 55개 통과 |
| M3.3 회귀 | 74개 통과 |
| M3.4 어블레이션 실험/러너 | 100개 통과 |
| M3.5 큐레이션/분해 | 113개 통과 |

라이브 테스트에는 루프백 데이터베이스가 필요합니다. PostgreSQL을 사용할 수 없거나 구성된 호스트가 루프백이 아니면 안전하게 건너뜁니다. 릴리스 품질의 로컬 인수 실행에서는 PostgreSQL을 사용할 수 있어야 하며 건너뛴 테스트가 없어야 합니다.

## 2. 정규 증분 게이트

구현하는 동안 각 정규 계층 테스트를 실행합니다.

```bash
uv run pytest -o addopts="" tests/evals/test_01_contract.py tests/evals/test_02_loader.py -q
uv run pytest -o addopts="" tests/evals/test_02_scoring.py -q
uv run pytest -o addopts="" tests/evals/test_03_regression.py -q
uv run pytest -o addopts="" tests/evals/test_04_ablation.py -q
uv run pytest -o addopts="" tests/evals/test_05_runner.py -q
```

누락된 심벌로 건너뛴 테스트는 진행 상황 표시일 뿐 인수 증거가 아닙니다. 위 명령은 미구현으로 인한 건너뛰기 없이 모두 통과해야 합니다.

## 3. 결정론적 오프라인 실험

```bash
docker compose up -d db
uv run python -m app.evals --provider deterministic --target-text-chars 500 1200 --strategies lexical vector hybrid -k 5 --candidate-k 20 --rrf-k 60 --budget-queries 200 --artifact-dir data/eval_runs
```

예상 동작:

- 격리된 임시 코퍼스 두 개를 구축하고 폐기합니다.
- 각 청크 목표에서 어휘, 벡터, 하이브리드 검색을 평가합니다.
- 전체 28개 사례를 기록하고 양성 사례 24개만 채점합니다.
- 타임스탬프가 있는 원시 JSON 산출물 여섯 개와 예산 JSON 산출물 하나를 작성합니다.
- 임베딩 공급자를 `deterministic`, 유료 API 호출을 `false`로 표시합니다.
- 채워진 코퍼스 임베딩을 변경하지 않습니다.

커밋된 수정 세트는 다음과 같습니다.

```text
data/eval_runs/20260812T200916Z-structure-500-lexical.json
data/eval_runs/20260812T200916Z-structure-500-vector.json
data/eval_runs/20260812T200916Z-structure-500-hybrid.json
data/eval_runs/20260812T200916Z-structure-1200-lexical.json
data/eval_runs/20260812T200916Z-structure-1200-vector.json
data/eval_runs/20260812T200916Z-structure-1200-hybrid.json
data/eval_runs/20260812T200916Z-budgets.json
```

대체된 부분 타이밍 세트의 색인 타이머에는 파싱/청킹 작업이 빠져 있으므로 해당 세트가 남아 있어서는 안 됩니다.

## 4. 원시 산출물 검사

```bash
test "$(find data/eval_runs -maxdepth 1 -type f -name '20260812T200916Z-*.json' | wc -l)" -eq 7
uv run python - <<'PY'
import json
from pathlib import Path

root = Path("data/eval_runs")
arms = sorted(root.glob("20260812T200916Z-structure-*.json"))
assert len(arms) == 6
for path in arms:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert len(payload["cases"]) == 28
    assert payload["config"]["embedding"]["provider"] == "deterministic"
    assert payload["config"]["measurement"]["paid_api_calls"] is False
    assert payload["config"]["measurement"]["populated_corpus_embeddings_modified"] is False
    assert payload["golden_provenance"]["human_verified"] is False
    assert payload["golden_provenance"]["approval_status"] == "pending-author-approval"

budget = json.loads((root / "20260812T200916Z-budgets.json").read_text(encoding="utf-8"))
assert all(item["passed"] for item in budget["indexing"])
assert budget["query_budget"]["query_count"] == 200
assert budget["query_budget"]["passed"] is True
print("validated six raw arms and one budget artifact")
PY
```

커밋된 실행에서 측정한 예산 예상값:

```text
500 indexing:  75.157933840 s / 300 s, pass
1200 indexing: 63.880582629 s / 300 s, pass
200 queries:   12.993961915 s / 90 s, pass
query P95:     71.480470 ms
```

## 5. 품질, 스타일, 문서

```bash
uv run pytest -o addopts="" -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check_doc_code.py
git diff --check
```

문서 검사기는 원문에 고정된 블록, 산문 상수, 상대 링크를 검증합니다. 단위 테스트가 통과해도 원시 산출물 링크가 없으면 문서 검증은 실패합니다.

## 수동 및 유료 공급자 게이트

유료 OpenAI 호출은 하지 않았습니다. OpenAI 경로는 옵트인으로 유지됩니다.

```bash
OPENAI_API_KEY="your-key" uv run python -m app.evals --provider openai --target-text-chars 500 1200 --strategies lexical vector hybrid -k 5 --candidate-k 20 --rrf-k 60 --budget-queries 200 --artifact-dir data/eval_runs
```

실행하기 전에 작성자는 다음 조건을 충족해야 합니다.

1. 유료 사용과 별도 OpenAI 산출물 세트를 승인합니다. 2. 결제가 설정되고 `text-embedding-3-small`에 접근할 수 있는 유효한 프로젝트 자격 증명을 제공합니다. 3. 현재 가격과 충분한 속도 제한을 확인합니다. 4. 임시 테이블 격리를 유지하고 실행 후 채워진 항목 수를 확인합니다.

두 청킹 실험군에는 색인된 문자 15,392,912개가 있으며 벡터/하이브리드 쿼리 단계에서 질문 문자 28,533 개가 추가됩니다. 토큰당 문자 네 개라는 계획용 근삿값을 사용하면 입력 토큰은 약 3.855 백만 개입니다. 현재 공식 [`text-embedding-3-small` 가격 $0.02 (토큰 백만 개당)](https://developers.openai.com/api/docs/models/text-embedding-3-small)을 적용하면 예상 임베딩 비용은 약 **$0.08**이며 **$0.10** 미만으로 예산을 책정해야 합니다. 이는 측정된 청구액이 아니라 추정치입니다. 실제 토큰화, 재시도, 실행 시점의 가격에 따라 최종 금액이 결정됩니다.

골든 검토는 별도의 수동 게이트입니다. 작성자는 `approval_status`나 `human_verified`를 변경하기 전에 인용된 모든 범위와 모든 부재 주장을 검토해야 합니다.

## 실패 분류

| 증상 | 의심 경계 | 첫 조치 |
|---|---|---|
| 해시 또는 경계 오류 | M3.1 골든/소스 스냅샷 | 정확한 코퍼스 스냅샷을 복원하고 청크에 맞추려고 범위를 옮기지 않습니다 |
| 순서 변경 후 점수 차이 | M3.2 채점 | 원문 식별자, 고유 범위 대조, 안정적인 사례 정렬을 검사합니다 |
| 기준선 누락 또는 오류 | M3.3 회귀 | 스위트와 완전한 정규 구성을 함께 비교하고 타임스탬프/ID 순서를 확인합니다 |
| 빈 어휘 후보 | M3.4 검색 | 완화된 `to_tsquery` 재작성과 그 원본 `websearch_to_tsquery`를 검사하고 채점은 변경하지 않습니다 |
| 공급자 불일치 | M3.4 출처 | 중단하고 새 격리 코퍼스를 만든 뒤 공급자 하나를 명시적으로 선언합니다 |
| 색인 예산이 예상보다 낮음 | M3.4 타이밍 | 매니페스트 로드, 파싱, 청킹 전에 타이머가 시작하는지 확인합니다 |
| 공개 임베딩 수 변경 | 격리 위반 | 중단하고 변경 원인을 설명하고 복구할 때까지 실행 결과를 게시하지 않습니다 |
| 산출물/문서 불일치 | 증거 동기화 | 수정된 타임스탬프 JSON을 검증하고 문서 검사기를 다시 실행합니다 |
