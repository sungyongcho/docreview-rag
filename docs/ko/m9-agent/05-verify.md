# M9 검증

## 오프라인 게이트

```bash
uv run pytest -o addopts="" tests/agent -q
uv run ruff check app/agent tests/agent
uv run ruff format --check app/agent tests/agent
```

기대: `32 passed`, ruff 두 명령 모두 깨끗함. 스위트 전체가 결정론적이다 — 네트워크도, 데이터베이스도, API 키도 없다.

## 스위트가 고정하는 것

- 계약의 배타성: 답·관찰·결과는 모순된 상태를 가질 수 없다 (`test_01`).
- 하나의 스키마, 세 소비자: 레지스트리 spec은 엄격하게 닫혀 있고, MCP 도구 목록은 스키마 대 스키마로 `registry.specs()`와 같다 (`test_02`, `test_07`).
- provider 중립성: 결정론적 큐와 OpenAI 어댑터가 사용량이 붙은 같은 턴 형태를 만든다 (`test_03`).
- 루프 규율: 모든 실패 계급에 대한 명시적 관찰, 거부-후-재시도가 가능한 근거 게이트 인용, fail-closed 반복·토큰 예산, 타입이 있는 provider 실패 (`test_04`).
- 도구의 얇음: 내장 도구는 인자를 M2 필터로, 페이로드를 근거 id로 번역할 뿐 그 이상은 없다 (`test_05`).
- 분해의 정직함: provider 실패는 단일 질의로 폴백하고, 융합은 결정론적이며, 카테고리 슬라이스는 채점되지 않은 absent 케이스를 제외한다 (`test_06`).

## 라이브 체크 (선택)

```bash
docker compose up -d db
uv run python -m app.agent --question "How did NVIDIA's revenue change?" --provider deterministic
uv run python -m app.agent --question "How did NVIDIA's revenue change?" --provider openai --model gpt-5-mini
```

결정론적 실행은 키 없이 실제 코퍼스로 루프를 증명한다: 하이브리드 검색이 한 번 실행되고 최종 답은 정직한 `NOT_IN_DOCS`다. OpenAI 실행은 `OPENAI_API_KEY`가 필요하며 인용된 `SUPPORTED` 답 또는 타입이 있는 실패를 반환한다. 어느 쪽이든 출력된 JSON은 토큰과 지연이 붙은 모든 스텝을 싣고 있다.

건너뛰었거나 없는 라이브 체크는 검증되지 않은 환경이지, 통과가 아니다.
