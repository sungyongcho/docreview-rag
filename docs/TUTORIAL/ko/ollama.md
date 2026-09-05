# macOS와 Linux에서 Ollama 준비하기

> [!DEV]
> DocReview에서 로컬 답변 서버를 연결·설정하는 기능은 개발 모드 전용입니다. 설치·서비스 명령은 해당 컴퓨터의 관리자가 실행합니다.

**설정 → 로컬 LLM**에서 답변 모델을 찾지 못하거나, 별도로 설치한 Ollama 서버를 연결할 때 읽는 안내입니다. 먼저 [환경 준비](environment.md#step-1)를 마칩니다. 준비된 DocReview 코퍼스는 그대로 사용하며, Ollama 설치 때문에 문서나 임베딩을 다시 만들 필요는 없습니다.

아래 명령은 필요한 작업을 확인한 뒤 직접 실행합니다. 안내를 열거나 읽는 동작만으로 소프트웨어 설치, 모델 다운로드, 서비스 변경, 모델 질문 전송이 실행되지는 않습니다.

## 기존 설치부터 확인하기 {#check}

Ollama를 실행할 컴퓨터의 터미널에서 확인합니다.

```bash
command -v ollama
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:11434/api/tags
```

`models` 배열이 포함된 HTTP 응답을 받으면 로컬 API가 응답한 것입니다. 빈 배열은 목록에 모델이 없다는 뜻이며 서버 중단과 다릅니다. 응답하면 설치를 건너뛰고 [모델 선택](#models)으로 이동합니다. 기본 API 포트는 **11434**입니다. [Ollama API 안내](https://docs.ollama.com/api/introduction), [모델 목록 API](https://docs.ollama.com/api/tags).

## macOS 설치와 실행 {#macos}

현재 공식 요구 사항은 macOS 14 이상입니다. [공식 macOS 설치 안내](https://docs.ollama.com/macos)에서 설치 파일을 받고 DMG를 연 뒤, Ollama를 응용 프로그램 폴더로 옮겨 실행합니다. CLI 경로를 등록하는 안내가 나오면 내용을 확인하고 진행합니다.

```bash
open -a Ollama
ollama --version
```

[API 확인](#check)을 다시 실행합니다. 앱이 이미 11434 포트에서 동작한다면 `ollama serve`를 추가 실행하지 않습니다. 같은 주소를 두 프로세스가 동시에 사용할 수 없습니다. 앱이 시작되지 않으면 최근 서버 로그를 확인합니다.

```bash
tail -n 80 ~/.ollama/logs/server.log
```

로그 위치는 [공식 문제 해결 안내](https://docs.ollama.com/troubleshooting)에 있습니다. Mac의 모델명이나 프로세서 종류만으로 특정 실행이 CPU·GPU 중 어디에서 수행됐는지 단정하지 않습니다.

## Linux 설치와 실행 {#linux}

`ollama`가 없다면 [공식 Linux 설치 안내](https://docs.ollama.com/linux)의 설치 명령을 사용합니다. 이 명령은 소프트웨어를 설치하며 관리자 권한을 요청할 수 있습니다.

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

systemd로 설치된 환경은 먼저 상태를 읽습니다.

```bash
systemctl status ollama --no-pager
```

설치된 서비스가 멈춰 있고 실행하려는 경우에만 시작합니다.

```bash
sudo systemctl start ollama
```

systemd 서비스 없이 설치했다면 터미널에서 `ollama serve`를 실행하고 그 터미널을 열어 둡니다. 서버 프로세스는 하나만 사용합니다. 다른 터미널에서 [API 확인](#check)을 반복합니다. 설치 스크립트가 맞지 않는 환경은 공식 문서의 수동 설치 절차를 참고합니다.

```bash
ollama serve
```

최근 서비스 로그는 설정을 바꾸지 않고 읽을 수 있습니다.

```bash
journalctl -u ollama -n 80 --no-pager
```

직접 실행한 서버의 로그는 해당 터미널에서 읽습니다. [Ollama 문제 해결](https://docs.ollama.com/troubleshooting).

## DocReview 백엔드에서 서버에 접근하기 {#network}

브라우저는 DocReview 백엔드에 요청하고, 백엔드가 Ollama에 연결합니다. 따라서 호스트 터미널의 확인만 성공했다고 백엔드 컨테이너 연결까지 확인된 것은 아닙니다.

| DocReview 백엔드 위치 | DocReview에서 사용하는 기본 서버 주소 |
| --- | --- |
| Ollama와 같은 컴퓨터의 직접 실행 프로세스 | `http://127.0.0.1:11434` |
| 저장소의 Docker 개발 스택, Ollama는 호스트에서 실행 | `http://host.docker.internal:11434` |
| 다른 컴퓨터 또는 별도 서버 | **서버 추가…**에서 백엔드가 접근할 주소 입력 |

**Default**를 그대로 선택하면 DocReview가 현재 환경의 주소를 결정합니다. 주소는 진단이 필요할 때 **연결 상세**에서만 확인합니다. 저장소의 Docker 설정에는 호스트 게이트웨이 매핑이 포함되며 컨테이너 안의 `127.0.0.1`은 그 컨테이너 자신입니다. 다른 서버를 의도적으로 연결할 때만 서버를 추가하며, Ollama 자동 감지에서는 `/api`나 `/v1`을 붙이지 않은 기본 주소를 입력합니다.

Ollama는 기본적으로 호스트의 루프백 주소에서만 요청을 받습니다. 백엔드 진단에서 컨테이너 접근 실패가 확인되면 수신 주소 변경이 필요할 수 있습니다. 아래 예제는 **모든 인터페이스**에서 수신하므로 허용할 클라이언트를 제한하는 신뢰된 네트워크에서만 사용합니다. 인증 없는 로컬 API를 인터넷에 직접 공개하지 않습니다. [Ollama 서버 설정](https://docs.ollama.com/faq), [API 인증 범위](https://docs.ollama.com/api/authentication).

### macOS 앱의 수신 주소 {#macos-bind}

실행 중인 Ollama 작업이 없는지 확인하고 앱 환경변수를 지정한 뒤, Ollama 앱을 종료하고 다시 엽니다.

```bash
launchctl setenv OLLAMA_HOST 0.0.0.0:11434
```

다른 터미널에서 환경변수만 바꿔도 이미 실행 중인 macOS 앱에 반영되지는 않습니다. [공식 macOS 환경변수 절차](https://docs.ollama.com/faq#setting-environment-variables-on-mac).

### Linux systemd의 수신 주소 {#linux-bind}

서비스 override를 열어 `[Service]` 아래에 설정을 추가합니다. 기존 항목은 보존합니다.

```bash
sudo systemctl edit ollama.service
```

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```

실행 중인 Ollama 작업이 없는지 확인한 뒤 변경을 적용합니다.

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama.service
```

직접 실행한 서버는 해당 프로세스를 종료한 뒤 `OLLAMA_HOST=0.0.0.0:11434 ollama serve`로 시작합니다. 이후 호스트 API 확인과 DocReview 진단을 모두 반복합니다. [공식 Linux 환경변수 절차](https://docs.ollama.com/faq#setting-environment-variables-on-linux).

## 답변 모델 준비와 정보 확인 {#models}

설치된 모델을 먼저 확인합니다.

```bash
ollama ls
```

적합한 답변 모델이 이미 있다면 재사용합니다. 없다면 [공식 모델 목록](https://ollama.com/library)에서 로컬 채팅·텍스트 생성 모델의 정확한 태그를 선택하고 라이선스와 저장 공간을 확인합니다. 선택을 마친 경우에만 다운로드합니다.

```bash
# Replace this with the exact model tag you chose.
ollama pull 'MODEL_TAG_FROM_LIBRARY'
```

`pull`은 모델 파일을 내려받으며 시험 질문을 실행하지 않습니다. 네트워크와 저장 공간을 많이 사용할 수 있습니다. 클라우드 모델 항목이 보인다고 해당 모델 파일이 로컬에 설치된 것은 아닙니다. [Ollama CLI 안내](https://docs.ollama.com/cli).

텍스트 생성 없이 설치된 모델 정보를 확인합니다.

```bash
# Replace this with an exact name from ollama ls.
ollama show 'MODEL_NAME_FROM_LIST'
ollama ps
```

| 정보 | 의미 |
| --- | --- |
| 설치 크기 | 서버가 보고한 모델 파일 크기이며 실행 RAM 요구량과 다름 |
| 파라미터 수·양자화 | 서버가 제공하는 경우 표시하는 모델 메타데이터 |
| 최대 컨텍스트 | 모델 메타데이터의 한도이며 현재 실행의 할당 크기와 다름 |
| 로드된 컨텍스트 | 로드된 모델 API가 제공할 때만 확인할 수 있는 현재 할당 크기 |
| 답변 기능 | 서버가 DocReview에서 사용하는 답변 기능을 제공하는지 여부 |
| 로드되지 않음 | 설치된 모델의 정상 대기 상태이며 실패를 뜻하지 않음 |

`/api/show`는 모델 상세 정보, `/api/ps`는 현재 로드된 모델 정보를 제공합니다. 현재 DocReview 모델 목록은 최대·로드 컨텍스트 값을 수집하지 않으므로 Ollama 도구에서 확인합니다. 누락된 필드는 미확인으로 구분합니다. 컨텍스트 할당을 늘리면 일반적으로 메모리가 더 필요합니다. 이 안내는 선택한 모델·컨텍스트·예산을 바꾸지 않습니다. [모델 상세](https://docs.ollama.com/api-reference/show-model-details), [로드된 모델](https://docs.ollama.com/api/ps), [컨텍스트 길이](https://docs.ollama.com/context-length).

## DocReview에서 연결하기 {#connect}

**설정 → 로컬 LLM**의 서버 선택기를 엽니다. **Default**는 현재 DocReview 환경에서 주소를 가져옵니다. **서버 추가…**를 선택하면 서버 이름·별도 주소·프로토콜 입력이 나타납니다. 이름은 나중에 연결 대상을 구분하기 위한 표시명입니다.

<!-- capture:13-local-model -->

![설정 → 로컬 LLM.](../assets/13-local-model.ko.jpg)

*설정 → 로컬 LLM. Default가 주소를 자동 처리하고 실제 설치 모델 3개와 답변용 모델 1개를 구분합니다. 연결 상세에서만 주소를 확인할 수 있습니다.*

**연결 진단 실행**을 먼저 선택합니다. 진단 제목에 검사한 대상이 표시되며 사용 중인 연결은 바뀌지 않습니다. 백엔드 연결 결과와 답변 모델 상태를 확인하고 **연결 상세**에서 사용 중인 주소·기본 주소를 읽습니다. 선택한 서버를 적용하려는 경우에만 기존 항목은 **연결**, 새 서버는 **추가하고 연결**을 실행합니다. 탐색이나 저장이 실패하면 이전에 동작하던 설정을 보존합니다. 답변 서버 연결은 임베딩 공급자를 변경하지 않습니다.

<!-- capture:25-add-server -->

![서버 추가에서 이름·주소·프로토콜 입력을 엽니다.](../assets/25-add-server.ko.jpg)

*서버 추가에서 이름·주소·프로토콜 입력을 엽니다. 제출하지 않은 초안이므로 추가하고 연결 버튼은 비활성화돼 있고 기존 Default 연결은 유지됩니다.*

**연결 해제**는 로컬 답변을 비활성화합니다. **Default로 복귀**는 기본 서버를 검사한 뒤 전환하며 추가한 서버 목록을 유지합니다. 검사·저장에 실패하면 현재 동작하던 연결을 보존합니다.

대화창으로 돌아가 답변 엔진 선택기에서 설치된 모델을 선택합니다. 연결 확인은 작성 중인 질문을 전송하지 않습니다. 질문할 준비가 되면 [답변](answers.md#engines)과 [요청 설정](settings.md#step-10)을 이어갑니다.

## 읽기 전용 진단 실행하기 {#diagnostics}

[프로젝트 명령 등록](cli.md#명령-등록과-도움말)을 마친 뒤 실행합니다.

```bash
rag-ollama-check
rag-ollama-check --web-url http://localhost:8000
rag-ollama-check --details
rag-ollama-check --setup
```

첫 명령은 설정된 웹 주소를 사용합니다. 다른 프런트엔드 주소를 쓰는 경우에만 `--web-url`을 지정하며 여기에 Ollama 주소를 넣지 않습니다. `--details`는 호스트·컨테이너·수신 주소의 추가 근거를 보여 줍니다. `--setup`은 수동 설치 안내만 출력합니다. 진단은 Ollama 설치, 설정 변경, 모델 다운로드·로드, 답변 생성을 실행하지 않습니다.

설치를 반복하기보다 실패한 구간을 구분합니다.

| 증상 | 확인할 근거 | 복구와 재확인 |
| --- | --- | --- |
| 호스트 API가 응답하지 않음 | 앱·서비스 상태와 서버 로그 | 의도한 서버를 시작하고 `/api/tags` 재확인 |
| 호스트는 성공하고 백엔드는 실패 | 백엔드 결과·수신 주소·호스트 게이트웨이·방화벽 | 접근 가능한 주소나 승인한 수신 설정을 교정한 뒤 재진단 |
| 백엔드는 연결됐지만 답변 모델 없음 | 설치 목록과 보고된 기능 | 적합한 모델을 선택·설치한 뒤 다시 탐색 |
| 설치됐지만 로드되지 않음 | 설치 목록에는 있고 로드 목록은 비어 있음 | 정상 대기이며 별도 예열은 필요하지 않음 |
| 운영 모드에서 로컬 연결 차단 | 실행 모드와 권한 진단 | 개발 환경에서 사용하며 공개 권한을 우회하지 않음 |
| 연결 저장 실패 | 저장 오류와 이전 활성 설정 | 동작하던 설정을 유지하고 보고된 원인 해결 후 명시적으로 재시도 |
| 연결 후 답변 실행 실패 | Run trace와 기록된 실패 유형 | [실행 문제 해결](troubleshooting.md#execution) 확인. 연결 성공은 답변 품질 검증이 아님 |

로그와 실제 실행 측정은 [실행과 측정](runtime.md#local-models)에서 이어갑니다. 진단 명령의 상세 정의는 [CLI 안내](cli.md#로컬-모델-연결-진단)에 있습니다.

<!-- capture:24-connection-diagnostics -->

![Default의 실제 읽기 전용 진단입니다.](../assets/24-connection-diagnostics.ko.jpg)

*Default의 실제 읽기 전용 진단입니다. 서버 선택·접속·답변용 모델 확인이 통과했으며 설정이나 모델 상태를 바꾸지 않았습니다.*
