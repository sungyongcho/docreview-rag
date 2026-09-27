# 5. 기존 화면에 Agent 모드 연결하기

[전체 진행표](README.md) · 이전: [LangGraph](04-langgraph-state-and-resume.md) · 다음: [OAuth](06-auth0-and-external-mcp.md)

목표는 기존 기본 리뷰를 유지하면서 웹 요청이 새 그래프와 MCP를 실제로 통과하게 만드는 것이다.

## 읽을 코드

| 영역 | 시작점 |
|---|---|
| 입력·실행·취소 | [use-review-requests.ts](../web/components/use-review-requests.ts) |
| HTTP·SSE | [api.ts](../web/lib/api.ts), [streaming.py](../app/api/review/streaming.py) |
| 진행·근거 표시 | [review-progress.tsx](../web/components/review-progress.tsx), [review-stage-details.tsx](../web/components/review-stage-details.tsx) |
| 요청 계약·조립 | [schemas.py](../app/api/review/schemas.py), [app.py](../app/api/app.py) |
| 공개 요청·비용 제한 | [middleware.py](../app/release/middleware.py), [ai_allowance.py](../app/release/ai_allowance.py) |
| API schema 생성 | [api_schema.py](../scripts/release/api_schema.py), [web/package.json](../web/package.json) |

## 직접 할 일

1. Agent 모드 입력·결과·진행 이벤트 계약을 먼저 적는다. 기본 `/review` 응답에 그래프 내부 상태를 덧붙이지 않는다.
2. `POST /agent/review`, `POST /agent/review/stream`을 추가하고 동일한 그래프 실행 책임을 사용한다.
3. 기존 입력·답변·근거·진행 컴포넌트를 재사용한다. 단계, 호출 도구, 출처, 답변, token·추정 비용, 종료 사유를 표시한다.
4. 기존 `AbortController`에서 backend producer·그래프·도구 실행까지 취소가 전달되는지 연결한다. UI만 멈추고 새 모델 호출이 이어져서는 안 된다.
5. API schema와 web 타입을 기존 생성 절차로 갱신한다. 수작업으로 생성된 타입만 고치지 않는다.
6. 한국어·영어 사용법을 `docs/TUTORIAL/ko/`, `docs/TUTORIAL/en/`의 해당 문서에 반영한다.

## 자동으로 적용되지 않는 경계

현재 backend `AI_ROUTES`와 web `apiFetch`의 실행 경로 목록에는 `/retrieve`, `/review`, `/review/stream`이 들어 있다. 새 Agent URL이 여기에 자동으로 포함된다고 가정하지 않는다. 새 요청에도 기존 공개 제한이 적용되도록 책임 있는 위치를 수정한다.

MCP가 별도 프로세스나 HTTP 서버이면 backend의 프로세스 내부 비용 문맥만으로 MCP 검색 비용이 제한되지 않는다. embedding·번역·모델 호출의 예산 전달과 서버 측 집행을 확인한다. Agent 요청과 외부 직접 MCP 요청 모두 6단계 공개 전에 검증한다.

브라우저에는 서버 자격증명을 보내지 않고, 임의 MCP 주소·비밀키·서버 설정을 입력받지 않는다. 실행 사실과 도구 입출력의 필요한 요약을 보여주되 내부 추론 전문을 노출하지 않는다.

## 실패 재현

- 정상 답변과 근거 없음이 다른 상태로 보이는가?
- 도구 실패·예산 종료가 빈 답변이나 무한 로딩으로 남지 않는가?
- 취소 버튼·탭 종료·네트워크 해제 후 새 외부 호출 횟수가 늘지 않는가?
- 이미 진행 중인 외부 요청의 취소 결과가 불명확하면 성공·환불로 표시하지 않는가?
- 모드 전환 후 기본 리뷰와 기존 대화 저장 데이터가 계속 동작하는가?
- 동시에 다른 대화를 열어도 결과가 원래 요청의 메시지에 붙는가?

## 검증

영향받는 backend·web 테스트부터 실행한다. 기존 취소 테스트는 [test_streaming.py](../tests/api/review/test_streaming.py), 요청 제한은 [test_01_request_guards.py](../tests/release/test_01_request_guards.py)를 참고한다. 새 Agent 경로를 실제로 호출하는 회귀 검사가 필요하다.

기존 npm 스크립트는 `pretest`, `pretypecheck`, `prebuild`에서 튜토리얼 파일을 준비한다. 실행 후 생성물 diff를 확인한다.

```bash
npm --prefix web run test -- components/review-progress.test.tsx components/review-stage-details.test.tsx
npm --prefix web run typecheck
npm --prefix web run check:api
npm --prefix web run build
git diff --check
```

이 명령만으로 새 모드가 검증되는 것은 아니다. 새 Agent 화면·요청 테스트를 추가해 함께 실행하고, 실제 로컬 브라우저에서 새 그래프→MCP 경로와 취소를 확인한다. 캡처가 필요하면 실제 light mode 상태를 양쪽 언어로 확인한다. 과거 스크린샷을 새 기능의 증거로 쓰지 않는다.

## 통과 기준

- [ ] 기본 리뷰가 유지된다.
- [ ] Agent 요청이 실제 새 그래프·MCP 경로를 통과한다.
- [ ] 단계·도구·근거·비용·종료 사유를 확인할 수 있다.
- [ ] 취소·오류·요청 제한·비용 제한이 새 경로에도 적용된다.
- [ ] 타입·빌드·실제 브라우저 확인 결과를 구분해 기록했다.
