# M9 명세 — 예산이 걸린 툴 호출 에이전트

## 범위

타입이 있는 도구들 위에서 도는 자작 에이전트 루프 하나. 엔드투엔드로 오프라인 테스트가 가능하며, 루프·레지스트리·모든 계약을 이 저장소가 소유한다. 에이전트 프레임워크는 쓰지 않는다. 오케스트레이션 라이브러리는 설계상 범위 밖이다.

## 계약

- `AgentAnswer`는 M4의 라벨 계약을 그대로 진다: `SUPPORTED`는 인용을 요구하고, `NOT_IN_DOCS`는 인용을 금지하며, 두 상태는 상호 배타적이다.
- 최종 답은 같은 실행에서 도구가 먼저 돌려준 chunk id만 인용할 수 있다. 루프는 각 도구의 `evidence_ids` 추출기로 근거를 추적하고, 그 밖의 인용은 명시적 관찰과 함께 거부한다.
- `AgentResult`는 종결적이고 배타적이다: `ok` 실행은 답을 갖고 실패를 갖지 않으며, 그 외 모든 상태는 실패를 갖고 답을 갖지 않는다.
- 모든 반복은 `AgentStep`으로 기록되며, 그 안에 도구 호출·관찰·`StepUsage`(모델, 엔드포인트, 토큰, 지연, 재시도)가 담긴다.

## 루프

- 한 반복은 provider 턴 하나와, 요청된 모든 도구 호출에 대한 명시적 관찰로 구성된다.
- 도구 실패 — 알 수 없는 이름, 잘못된 인자, 발생한 예외, JSON이 아닌 페이로드 — 는 모델이 읽을 수 있는 관찰이 된다. 조용한 실패는 금지다.
- 도구 호출이 없는 턴은 명시적 넛지를 받고 반복 하나를 소모한다.
- `AgentBudget`은 반복 수와 누적 토큰을 제한한다. 예산은 fail-closed다: 소진된 실행은 전체 스텝 이력과 함께 `budget_exceeded`를 반환하며, 절대 부분 답을 내지 않는다.
- provider 예외는 그때까지 완료된 스텝과 함께 `provider_error`를 반환한다.

## 도구

- `Tool`은 이름, 설명, Pydantic 파라미터 모델, async 실행 함수, 선택적 근거 추출기다.
- 레지스트리는 중복 이름과 예약된 `final_answer`를 거부하고, 동기화된 세 표면을 생성한다: LLM용 엄격 function spec, MCP용 input schema, 프롬프트 매뉴얼.
- 내장 도구는 M2 검색만 감싼다: `search_filings`, `fetch_chunk`, `compare_years`. 검색 시맨틱은 `app/retrieval`에 남는다.

## 분해

- `decompose_query`는 M4 provider에게 1~4개의 유일한 하위 질문을 요청하고, provider가 어떤 식으로든 실패하면 원래 질문으로 폴백한다.
- `make_decomposed_retriever`는 M3의 `Retriever` 계약에 맞는 콜러블을 반환한다. 하위 질문 랭킹은 n개 리스트로 일반화한 reciprocal-rank fusion으로 병합한다.
- `run_decomposition_comparison`은 baseline과 분해 리트리버를 무수정 M3 하니스로 평가하고 카테고리별 지표와 델타를 보고한다.

## 인터페이스

- `python -m app.agent --question ...`은 에이전트 요청 하나를 실행하고 JSON `AgentResult`를 출력한다. `--provider deterministic`은 오프라인 데모, `--provider openai`가 실제 루프다.
- `python -m app.agent --mcp`는 레지스트리를 MCP stdio로 서빙한다. 발행되는 스키마는 레지스트리의 엄격 spec과 바이트 단위로 같다.

## 범위 밖

- 코드 생성 에이전트와 샌드박스 실행. 모델이 쓴 코드를 실행하는 것은 고유한 격리 요구사항을 가진 별도의 안전 프로젝트다. 이 모듈의 에이전트는 타입이 있는 도구만 호출한다.
- 멀티 provider 벤치마킹. 스텝별 사용량 기록은 존재하지만, 모델 비교 리포트는 이후 과제다.
