# 1. 모델 없이 작은 MCP 서버 호출하기

[전체 진행표](README.md) · 이전: [현재 구조](00-understand-current-flow.md) · 다음: [실제 공시 도구](02-filing-tools-and-transports.md)

목표는 도구 구현, MCP 서버, MCP 클라이언트의 책임을 분리해서 이해하는 것이다. 모델과 DB 없이 시작한다.

## 먼저 설명할 개념

- 서버는 도구 이름·설명·입력 계약을 공개하고 호출을 실행한다.
- 클라이언트는 연결을 열고 도구 목록과 호출 결과를 받는다.
- stdio에서는 클라이언트가 자식 서버 프로세스를 시작할 수 있다. 프로토콜 출력과 일반 로그가 같은 stdout에 섞이면 안 된다.
- 함수 직접 호출 성공, 메모리 안의 MCP 연결 성공, 실제 stdio 프로세스 성공은 서로 다른 증거다.

SDK 사용법은 [공식 첫 단계](https://py.sdk.modelcontextprotocol.io/get-started/first-steps/)와 [클라이언트](https://py.sdk.modelcontextprotocol.io/client/)를 읽는다. 로컬 MCP 2.1.1에서 `from mcp.server import MCPServer`, `from mcp import Client`를 확인했다.

## 현재 시작 상태

기존 MCP 서버, 전용 테스트, CLI `--mcp`, 패키지 의존성은 제거했다. 완성 코드나 빈 구현 틀을 미리 넣지 않았다. `app/agent/mcp_server.py`와 `tests/agent/test_mcp_server.py`는 이 단계에서 직접 새로 만들 파일이다.

기존 도구 계약은 [registry.py](../app/agent/tools/registry.py), CLI 실행 구조는 [agent CLI](../app/agent/__main__.py)에 남아 있다. 둘 다 MCP 없이 사용하는 코드다.

먼저 `pyproject.toml`에 목표 SDK를 추가하고 잠금 결과를 확인한다. 다음 명령은 이 학습 단계에서 실행할 준비 절차이며, 가이드 작성 시 실행한 것이 아니다.

```bash
uv add "mcp==2.1.1"
```

Python 3.14 환경과 기존 패키지 버전을 유지한다. 새 테스트는 도구 발견·호출·오류라는 공개 동작을 검증한다.

## 직접 구현할 순서

1. 실습 도구 하나의 계약을 먼저 쓴다. 예: `echo_text(text: nonempty string)` → 입력한 문자열을 담은 객체.
2. 새 `app/agent/mcp_server.py`에 공식 `MCPServer`와 그 도구를 직접 작성한다. JSON-RPC나 프레이밍은 직접 구현하지 않는다.
3. SDK 클라이언트로 도구 목록을 읽고 정상 입력을 한 번 호출한다. 모델은 사용하지 않는다.
4. 필수 인자 누락·빈 문자열·모르는 도구 이름을 각각 호출한다. 정상 결과와 오류를 구분해서 출력한다.
5. 실제 자식 프로세스를 띄우는 stdio 테스트로 같은 호출을 반복하고, 연결 종료 후 자식 프로세스가 끝나는지 확인한다.
6. 새 서버를 시작하는 방법과 클라이언트 연결을 설명한다. 실습 도구 등록은 2단계에서 실제 세 도구로 교체하며, 과거 서버 코드를 복사해 되살리지 않는다.

실습은 이 브랜치 안에서 진행한다. 1단계의 작은 도구 성공과 2단계의 실제 공시 도구 연결 완료를 구분한다. 기존 CLI 에이전트의 직접 도구 호출은 계속 동작해야 한다.

## 결과를 먼저 예측하기

| 입력 / 상황 | 실행 전에 적을 예상 |
|---|---|
| `text="hello"` | 호출 결과의 데이터와 성공 표시는 무엇인가? |
| 인자 없음 | 도구 본문이 실행되는가, 입력 검증에서 끝나는가? |
| 빈 문자열 | 타입이 `str`인 것만으로 거부되는가? 추가 계약은 무엇인가? |
| 잘못된 도구 이름 | 도구 오류인가, 프로토콜 오류인가? SDK 실제 응답을 확인한다 |
| 서버를 종료한 뒤 호출 | 빈 성공 결과로 바뀌지 않고 연결 실패가 드러나는가? |

SDK가 제공하는 오류 표현을 관찰한 뒤 테스트에 반영한다. 예전 코드의 오류 문자열을 무조건 새 SDK에 강제하지 않는다. 반대로 테스트를 통과시키려고 오류를 빈 결과로 바꾸지도 않는다.

## 검증

새 `tests/agent/test_mcp_server.py`를 공개 동작 기준으로 작성한다. 임시 도구 fixture는 테스트 안에서 정의할 수 있다. 프로덕션에 실습 도구를 계속 노출할 이유는 없다.

```bash
.venv/bin/pytest tests/agent/test_mcp_server.py -q
.venv/bin/ruff check app/agent/mcp_server.py tests/agent/test_mcp_server.py
.venv/bin/ruff format --check app/agent/mcp_server.py tests/agent/test_mcp_server.py
git diff --check
```

stdio 클라이언트의 실행 파일·작업 디렉토리·종료 정리를 명시한다. 현재 Python 환경의 실행 파일을 사용하고, 테스트가 임의로 패키지를 설치하거나 모델을 호출하지 않게 한다.

## 통과 기준

- [ ] 모델·DB 없이 도구 목록, 정상 호출, 잘못된 입력을 확인했다.
- [ ] 실제 stdio 자식 프로세스를 통한 검증이 있다.
- [ ] 클라이언트 종료 후 프로세스·스트림이 정리된다.
- [ ] 입력 스키마가 도구를 어떻게 설명하고 제한하는지 설명한다.
- [ ] 자신이 작성한 부분과 SDK가 수행하는 부분을 구분한다.

도움이 필요하면 “클라이언트 수명 관리 힌트”, “입력 검증 테스트 한 개”처럼 막힌 경계를 좁혀 요청한다.
