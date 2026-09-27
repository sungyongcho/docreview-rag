# 0. 질문 하나가 코드를 통과하는 경로

[전체 진행표](README.md) · 다음: [작은 MCP 서버](01-small-mcp-server.md)

목표는 현재 웹 리뷰·CLI 에이전트의 경계와 앞으로 MCP를 연결할 위치를 찾는 것이다. 기존 MCP는 제거한 상태다. 이 단계에서는 제품 코드를 수정하지 않는다.

## 첫 과제

공시 질문 하나를 고른다. 예를 들어 “선택한 회사의 두 회계연도 매출은 어떻게 달라졌는가?”다. 정답을 추측하지 말고, 다음 세 질문에 먼저 답한다.

1. 웹에서 보내면 처음 어떤 Python 함수가 받는가?
2. 현재 웹 질문이 `app/agent/loop.py`를 지나는가?
3. 모델이 호출을 제안하는 것과 검색 함수가 실행되는 것은 어디서 나뉘는가?

먼저 예상 경로를 적고, 아래 파일을 필요한 부분만 읽어 수정한다. 파일 전체를 외울 필요는 없다.

## 읽을 코드

| 순서 | 파일 / 찾을 심볼 | 확인할 것 |
|---|---|---|
| 1 | [use-review-requests.ts](../web/components/use-review-requests.ts), `submit`, `streamReview` 호출 | 질문·프로필·취소 신호를 넘기는 곳 |
| 2 | [api.ts](../web/lib/api.ts), `streamReview` | 요청 주소, SSE 수신, HTTP 오류 처리 |
| 3 | [streaming.py](../app/api/review/streaming.py), `review_stream` | 생산 작업, 진행 이벤트, 연결 종료 시 취소 |
| 4 | [routes.py](../app/api/review/routes.py), `review_query` | 일반 JSON 응답 경로 |
| 5 | [runtime.py](../app/api/review/runtime.py), `RuntimeApiServices.review`, `_review` | 대화 경로·검색 범위·모델·workflow 조립 |
| 6 | [runner.py](../app/workflow/runner.py), `run_workflow`; [nodes.py](../app/workflow/nodes.py) | 단계 실행·검증·예산·종료 |
| 7 | [agent CLI](../app/agent/__main__.py), `_run` | 기존 에이전트 실행의 진입점 |
| 8 | [loop.py](../app/agent/loop.py), `run_agent`, `_dispatch`, `_final_answer` | 도구 호출과 관찰, 최종 인용 검증 |
| 9 | [registry.py](../app/agent/tools/registry.py) | 도구 실행 경계; 새 MCP가 재사용할 책임 |
| 10 | [filings.py](../app/agent/tools/filings.py), [service.py](../app/retrieval/search/service.py) | 실제 검색·청크 조회·연도 비교 |

서버 조립은 [app/release/space.py](../app/release/space.py), [app/release/app.py](../app/release/app.py)에서 확인한다. 폐기된 `app.main`을 새 실행 진입점으로 사용하지 않는다.

## 직접 할 일

1. 현재 웹과 CLI 에이전트 경로를 각각 5~8개 상자로 그린다. 상자에 실제 파일·함수 이름을 붙인다. 앞으로 추가할 MCP 경로는 미구현으로 표시한다.
2. 같은 도구를 사용해도 웹과 CLI의 실행 제어가 다른 이유를 설명한다.
3. [EvidenceCitation](../app/contracts/evidence.py)에서 `chunk_id`, `doc_id`, `source_sha256`, 원문 구간의 역할을 찾는다.
4. `_final_answer`가 인용 식별자를 검사하는 것과 답변 내용의 진실성을 평가하는 것이 왜 다른지 설명한다.
5. [요청 제한](../app/release/middleware.py)의 `AI_ROUTES`와 [비용 제한](../app/release/ai_allowance.py)을 찾아 요청 횟수와 모델 비용이 각각 어디에서 제한되는지 표시한다.

코드 확인용 명령:

```bash
rg -n 'streamReview|review/stream' web/components/use-review-requests.ts web/lib/api.ts
rg -n 'def review|def _review|run_workflow' app/api/review/runtime.py
rg -n 'run_agent|build_default_registry|execute_tool' app/agent
.venv/bin/python -m app.agent --help
```

## 실행 전에 예측할 것

- `--help`가 DB나 모델 키 없이 동작해야 하는 이유는 무엇인가?
- 새 MCP 서버에서 도구를 제공하는 것과 모델을 호출하는 것은 어떤 관계인가?
- `--provider deterministic`이면 모든 실행 비용이 반드시 0인가?

마지막 질문은 [_demo_provider와 _run](../app/agent/__main__.py)을 확인한다. 모델 응답은 정해져 있어도 도구는 실제 검색을 수행하고, 검색 설정에 따라 임베딩 호출이 생길 수 있다. 이 데모의 `NOT_IN_DOCS`를 실제 질문의 정답 판정으로 사용하지 않는다.

## 확인할 기존 테스트

[test_loop.py](../tests/agent/test_loop.py)의 인용·예산 검사와 [test_streaming.py](../tests/api/review/test_streaming.py)의 취소 검사를 한 개씩 골라, 무엇을 가짜로 대체하는지 먼저 읽는다.

환경 준비 후 선택적으로 실행할 로컬 회귀 확인:

```bash
.venv/bin/pytest tests/agent/test_loop.py tests/api/review/test_streaming.py -q
```

이 결과는 실제 DB·모델·브라우저의 연결 성공과 별개다.

## 통과 기준

- [ ] 코드 위치를 짚으며 웹 경로와 CLI 경로를 설명한다.
- [ ] “모델이 제안 → 프로그램이 검증·실행 → 관찰을 모델에 전달”을 설명한다.
- [ ] MCP 없이도 기존 루프가 동작하는 이유를 설명한다.
- [ ] 출처 식별자 검증과 답변 정확성의 차이를 설명한다.
- [ ] 새 경로에 반드시 연결해야 할 범위·취소·비용 경계를 찾았다.

학습 코치에게 보여줄 것은 경로 그림과 위 다섯 항목의 자기 설명이다. 설명이 맞으면 1단계로 간다.
