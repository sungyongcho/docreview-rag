# 6. Auth0로 외부 MCP 접근 제어하기

[전체 진행표](README.md) · 이전: [웹](05-web-agent-mode.md) · 다음: [평가·면접](07-evaluation-ci-and-interview.md)

목표는 외부 클라이언트가 로그인하여 세 공시 도구를 호출하고, 부적절한 토큰은 서버에서 거부되는 것이다. 로컬 코드·검증부터 준비하고 Auth0 설정 변경과 외부 배포는 구체적인 설정안을 확인한 뒤 진행한다.

## 먼저 설명할 세 역할

| 역할 | 책임 |
|---|---|
| Auth0 | 사용자 로그인과 access token 발급 |
| MCP 서버 | token의 서명·issuer·audience·만료·scope 검증 |
| 클라이언트 | 인증 안내 발견, token 취득, MCP 요청에 전달 |

로그인·토큰 발급 서버를 직접 구현하지 않는다. JWT를 decode하여 내용을 보는 것과 서명을 검증하는 것은 다르다. SDK에 verifier를 넣는 것만으로 그 verifier의 검증이 자동 완성되지는 않는다. [공식 SDK 인증 안내](https://py.sdk.modelcontextprotocol.io/run/authorization/)에서 이 책임 경계를 확인한다.

## 구현 전에 작성할 설정표

비밀 값 없이 다음 항목의 실제 계획 값을 정한다.

- 공개 HTTPS MCP resource URL과 Auth0 API audience
- Auth0 issuer, 허용 서명 알고리즘, 공개 키 조회 위치
- `docreview:read` scope
- 사용자 클라이언트의 Authorization Code + PKCE와 정확한 callback URL
- 웹 backend용 별도 서비스 클라이언트와 필요한 최소 권한
- OAuth 메타데이터·인증 오류·MCP 스트리밍을 전달할 프록시 경로

Auth0의 resource parameter 호환 설정과 audience가 MCP 공개 URL에 맞는지 확인한다. [Auth0의 MCP audience 안내](https://support.auth0.com/center/s/article/mcp-audience-error-with-auth0)를 참고하되, 실제 tenant 설정과 발급된 access token의 대상이 일치하는지 검증한다. 외부 클라이언트의 등록 방식은 그 클라이언트 요구에 맞춰 선택한다.

## 직접 할 일

1. 공식 SDK 인증 경계에 verifier를 연결한다. 서명·issuer·audience·만료를 검증하고 `docreview:read`를 강제한다.
2. 테스트 전용 키와 토큰으로 정상·실패 사례를 로컬에서 검증한다. 이 테스트는 실제 Auth0 로그인 성공의 증거가 아니다.
3. 인증 실패 응답과 resource metadata가 올바른 외부 URL을 안내하는지 확인한다.
4. 현재 [Cloudflare](../deploy/cloudflare/README.md)와 [Oracle/Caddy](../deploy/oracle/README.md) 경로를 확인하고 필요한 경로만 변경한다. 원 계획의 경로 이름보다 실제 구성·외부 URL을 기준으로 한다.
5. `Authorization`, 인증 안내 헤더, `.well-known` 메타데이터, 스트리밍이 프록시를 통과하는지 확인한다. MCP 경로 prefix와 메타데이터 URL이 다를 수 있다.
6. 설정·게시 승인을 받은 뒤 실제 Auth0와 연결하고, 외부 MCP 클라이언트 하나 및 SDK 클라이언트로 로그인·도구 발견·호출한다.

원문 읽기 도구라도 검색 임베딩은 과금될 수 있다. 직접 MCP 호출이 웹의 요청·비용 제한을 우회하지 않도록 5단계에서 정한 집행 경계를 검증한다. token·client secret을 로그·브라우저·체크포인트에 남기지 않는다.

## 실패 매트릭스

| 요청 | 기대하는 보장 |
|---|---|
| token 없음 | 인증 필요 응답과 올바른 인증 안내 |
| 정상 token과 scope | 도구 발견·허용된 공시 호출 성공 |
| 만료 token | 도구 실행 전 거부 |
| 잘못된 서명 또는 issuer | 도구 실행 전 거부 |
| 다른 audience의 유효 token | 이 서버의 권한으로 인정하지 않음 |
| `docreview:read` 없음 | 권한 부족으로 거부 |
| 프록시 경유 동일 요청 | 직접 경로와 같은 인증 결과, 스트리밍 보존 |

거부된 요청에서 도구·DB·모델 호출이 실제로 시작되지 않았는지도 확인한다. 단순 응답 코드 검사만으로 충분하지 않다.

## 통과 기준

- [ ] 인증 서버·리소스 서버·클라이언트의 역할을 설명한다.
- [ ] 로컬 실패 매트릭스와 실제 Auth0 검증 결과를 구분한다.
- [ ] 외부 클라이언트 하나와 SDK 클라이언트의 실제 연결을 확인했다.
- [ ] 프록시 경유 인증·메타데이터·스트리밍이 동작한다.
- [ ] 검증한 클라이언트 이름·버전만 호환 범위로 주장한다.

외부 설정·배포가 진행되지 않았다면 구현 완료와 외부 운영 검증 미완료를 별도로 표시한다.
