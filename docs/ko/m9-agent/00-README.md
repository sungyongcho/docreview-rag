# M9 — 툴 호출 에이전트

> **`zero` 브랜치 참고:** 아래 완성 코드는 고정된 참조 목표이며 정식 파일은 직접 작성한다. 진행 상태: [모듈 플랜](../../project/module-plan.md).

M8까지는 시스템이 경로를 결정한다. 검색이 실행되고, 고정된 워크플로가 채점과 검증을 수행하고, 호출자는 하나의 리포트를 받는다. M9는 그 경로를 모델에게 넘긴다 — 단, 계약 아래에서. 에이전트는 어떤 도구를 호출할지 스스로 고르고, 명시적 관찰을 읽고, 자신의 실행이 실제로 검색한 근거를 인용한 답으로만 끝낼 수 있다.

| 레이어 | 목표 | 핵심 파일 | 중단 조건 |
|---|---|---|---|
| M9.1 | 엄격한 계약과 단일 도구 레지스트리 | `types.py`, `tools.py`, `registry.py` | 하나의 스키마가 LLM·MCP·프롬프트를 모두 먹여 살린다 |
| M9.2 | 사용량이 기록되는 provider 턴 | `provider.py` | 모든 턴이 토큰·지연·재시도를 갖고 돌아온다 |
| M9.3 | 자작 에이전트 루프 | `loop.py` | 인용 없는 답은 루프를 벗어날 수 없다 |
| M9.4 | 내장 공시 도구 | `builtin_tools.py` | 도구는 M2의 얇은 래퍼에 머문다 |
| M9.5 | 질의 분해와 그 측정 | `decompose.py`, `eval.py` | 주장은 산문이 아니라 카테고리별 비교다 |
| M9.6 | MCP 서버와 CLI | `mcp_server.py`, `__main__.py` | 외부 클라이언트는 레지스트리의 스키마를 그대로 본다 |

## 순서대로 진행하는 체크포인트 경로

### M9.1 — 계약과 레지스트리

- 선행 조건: M1–M8 완료; `uv run pytest tests/workflow -q` 통과.
- 파일: `app/agent/types.py`, `tools.py`, `registry.py`, `__init__.py`.
- 표준 명령:

  ```bash
  uv run pytest -o addopts="" tests/agent/test_01_contracts.py tests/agent/test_02_registry.py -q
  ```

- 기대 결과: 네트워크 호출 없이 `9 passed`.
- 중단 조건: 답·관찰·결과가 구성 자체로 상호 배타적이고, 레지스트리는 엄격하게 닫힌 스키마만 발행한다.

### M9.2 — 툴 호출 provider

- 선행 조건: M9.1 완료.
- 파일: `app/agent/provider.py`.
- 표준 명령:

  ```bash
  uv run pytest -o addopts="" tests/agent/test_03_provider.py -q
  ```

- 기대 결과: 네트워크 호출 없이 `3 passed`.
- 중단 조건: 결정론적 큐와 OpenAI 어댑터가 사용량이 붙은 동일한 중립 턴 형태를 돌려준다.

### M9.3 — 에이전트 루프

- 선행 조건: M9.2 완료.
- 파일: `app/agent/loop.py`.
- 표준 명령:

  ```bash
  uv run pytest -o addopts="" tests/agent/test_04_loop.py -q
  ```

- 기대 결과: 네트워크 호출 없이 `8 passed`.
- 중단 조건: 모든 도구 실패가 명시적 관찰이 되고, 예산은 fail-closed로 작동하며, 최종 답은 검색된 chunk id만 인용할 수 있다.

### M9.4 — 내장 공시 도구

- 선행 조건: M9.3 완료.
- 파일: `app/agent/builtin_tools.py`.
- 표준 명령:

  ```bash
  uv run pytest -o addopts="" tests/agent/test_05_builtin_tools.py -q
  ```

- 기대 결과: 네트워크 호출 없이 `3 passed`.
- 중단 조건: 검색·청크 열람·연도 비교가 새 검색 로직 없이 M2 검색을 노출한다.

### M9.5 — 분해와 그 측정

- 선행 조건: M9.4 완료.
- 파일: `app/agent/decompose.py`, `app/agent/eval.py`.
- 표준 명령:

  ```bash
  uv run pytest -o addopts="" tests/agent/test_06_decompose.py -q
  ```

- 기대 결과: 네트워크 호출 없이 `5 passed`.
- 중단 조건: 분해 리트리버가 무수정 M3 하니스에 그대로 꽂히고, 비교는 카테고리별 델타를 보고한다.

### M9.6 — MCP 서버와 CLI

- 선행 조건: M9.5 완료.
- 파일: `app/agent/mcp_server.py`, `app/agent/__main__.py`.
- 표준 명령:

  ```bash
  uv run pytest -o addopts="" tests/agent/test_07_mcp_cli.py -q
  ```

- 기대 결과: 네트워크 호출 없이 `4 passed`.
- 중단 조건: MCP 클라이언트는 레지스트리의 엄격한 스키마를 그대로 받고, 도구 실패는 타입이 있는 에러 결과로 돌아온다.

## 오프라인 퀵스타트

```bash
uv run pytest -o addopts="" tests/agent -q
uv run ruff check app/agent tests/agent
uv run python -m app.agent --question "How did NVIDIA's revenue change?" --provider deterministic
```

결정론적 CLI 실행에는 M2에서 시드한 로컬 PostgreSQL 코퍼스가 필요하다. 실제 하이브리드 검색을 한 번 수행한 뒤 정직하게 `NOT_IN_DOCS`로 답하며, API 키 없이 루프를 증명한다.
