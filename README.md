## docreview-rag-agent

### Local PostgreSQL

빠른 테스트는 데이터베이스 없이 실행하고, PostgreSQL 통합 테스트는 Compose의
`db` 서비스를 명시적으로 시작한 뒤 실행합니다.

```bash
uv run pytest -m "not live_postgres"
docker compose up -d db
uv run pytest -m live_postgres --require-live-postgres
docker compose stop db
```

포트 변경, 상태 확인, 데이터 보존 및 삭제 방법은
[Docker Compose로 로컬 PostgreSQL 실행](deploy/docker-compose.md)을 참고합니다.

### implementation order
재배치 비교표 (zero 완성본 기준)

#	모듈	zero 완성 순서	재배치 (수작업 재구현 루트)	변경
1	M1 — Ingestion	M1.1 → M1.2 → M1.3 → M1.4	동일	계약만 source-agnostic으로 설계
2	M2 — Retrieval	M2.1 → … → M2.11	동일	—
3	M3 — Evaluation	M3.1 → (M3.2+M3.3) → M3.4 → M3.5	동일	—
4	M4 — LLM Workflow	M4.1 → M4.2 → M4.3 → M4.4	M4.1 → M4.4 → M4.2 → M4.3	M4.4 전진 (기존 결론 유지)
5	M8 — Crosslingual	(M7 뒤) M8.1 → M8.2 → M8.3 → M8.4	M4 직후로 전진, 내부 동일	모듈 성격이 바뀌어서 이동
6	M10 — KR filings (신규)	없음	M10.1 → … → M10.6	DART 파서 삽입 지점
7	M5 — Serving	M5.1 → M5.2 → M5.3 → M5.4	M5.1 → M5.4 → M5.2 → M5.3	M5.4 전진 (기존 결론 유지)
8	M9 — Agent	(M8 뒤) M9.1 → … → M9.6	내부 동일, M5 직후	기존 결론 유지
9	M6 — Demo	(M5 뒤) (M6.1+M6.2) → M6.3	내부 동일, M9 뒤로	기존 결론 유지
10	M7 — Deployment	(M6 뒤) M7.1 → M7.2 → M7.3	내부 동일, 종점	localization 소멸로 자연 종점화


재배치 후 체인 한 줄씩
M1 — Ingestion: M1.1 → M1.2 → M1.3 → M1.4
M2 — Retrieval: M2.1 → M2.2 → M2.3 → M2.4 → M2.5 → M2.6 → M2.7 → M2.8 → M2.9 → M2.10 → M2.11
M3 — Evaluation: M3.1 → (M3.2 + M3.3) → M3.4 → M3.5
M4 — LLM Workflow: M4.1 → M4.4 → M4.2 → M4.3
M8 — Crosslingual: M8.1 → M8.2 → M8.3 → M8.4
M10 — KR filings (DART): M10.1 → M10.2 → M10.3 → M10.4 → M10.5 → M10.6
M5 — Serving: M5.1 → M5.4 → M5.2 → M5.3
M9 — Agent: M9.1 → M9.2 → M9.3 → M9.4 → M9.5 → M9.6
M6 — Demo: (M6.1 + M6.2) → M6.3
M7 — Deployment: M7.1 → M7.2 → M7.3

### 이식 범위 (실측)

각 행은 실제 이식 덩이 하나이며 커밋 하나에 대응합니다. `zero 범위`는 그 덩이가
`zero`에서 가져온 파일이고, `assemble 착지`는 이 브랜치에서 어디에 놓였는지입니다.
착지가 zero와 다른 행은 그 사실을 함께 적습니다.

`.dashboard/`의 대시보드가 이 표를 읽어 다음 단계를 표시하므로 마커를 지우지 마십시오.

<!-- port-map:start -->
| 단계 | zero 범위 | assemble 착지 | 커밋 | 상태 |
|---|---|---|---|---|
| init | 스캐폴드 | app/ingestion/xref.py | ab2c23b | 완료 |
| M1.1, M1.2 | app/ingestion/{parser,tables}.py | 동일 + data/profiles | a2ba790 | 완료 |
| M1.3 | app/ingestion/chunk.py | 동일 | 2b47b71 | 완료 |
| M1.4 | app/ingestion/seed.py, app/db/ | 동일 | 7fde61e | 완료 |
| M2.1~M2.4 | app/retrieval/{types,embeddings,vector,lexical}.py | 동일 + _sql.py 분리 | bc33427 | 완료 |
| M2.5~M2.8 | app/retrieval/{hybrid,rerank,service,__main__}.py | 동일 | d8c0439 | 완료 |
| M2.9~M2.11 | app/retrieval/{bm25,sbert,cross_encoder}.py | 동일 + _sentence_transformers.py | 7532b72 | 완료 |
| M3.1~M3.3 | app/evals/{types,loader,scoring,regression}.py | 동일 | dd4cc60 | 완료 |
| M3.4 | app/evals/{ablation,retrieval_eval}.py | retrieval_eval 1449줄을 arms·artifacts·corpus·measurement·run으로 분할 | c55a4ec | 완료 |
| M3.5 | app/evals/{curation,breakdown}.py | 동일 + reporting.py 공유 | 8b1e053 | 완료 |
| M4.1, M4.4 | app/llm/ | 동일 | 117bc92 | 완료 |
| M4.2 | app/observability/ | 동일 + db Run·Trace 모델 | 81b668f | 완료 |
| M4.3 | app/workflow/ | 동일 | b1475b7 | 완료 |
| M8.1~M8.4 | app/evals/{bilingual,crosslingual,parity}.py, app/retrieval/{language,translate}.py | 동일 + identity·cli 공유. tests/crosslingual은 tests/evals·tests/retrieval로 분산 | cc1957b | 완료 |
| M10.0 | zero 없음 (신규) | app/ingestion/registry.py | a370c44 | 완료 |
| M10.1~M10.3 | zero 없음 (신규) | app/ingestion/{dart,dart_api}.py | b5a3e54 | 완료 |
| M10.4~M10.6 | zero 없음 (신규) | app/retrieval/korean.py, data/golden/dart_* | 920825e | 완료 |
| M5.1, M5.4 | app/api/{schemas,errors,deps,app}.py, app/api/routes/ — 1069줄 | app/api/ | 42760b7 | 완료 |
| M5.3 | app/api/runtime.py — 522줄 | app/api/ | — | 대기 |
| M5.2 | app/cli.py, app/main.py, Dockerfile, docker-compose.yml | app/ | — | 대기 |
| M9.1~M9.6 | app/agent/ — 11파일 2145줄 | app/agent/ | — | 대기 |
| M6.1~M6.3 | app/demo.py — 595줄 | app/demo.py | — | 대기 |
| M7.1~M7.3 | app/release/ — 7파일 509줄 | app/release/ | — | 대기 |
<!-- port-map:end -->

### 리뷰 단위

코드 리뷰는 덩이 하나가 아니라 **모듈 하나가 다 들어온 뒤**에 받습니다. 덩이는 커밋을
가르는 단위이고, 리뷰는 모듈이 단위입니다 — 한 모듈의 경계가 다 서기 전에는 서로를
어떻게 쓰는지가 아직 안 보여서, 덩이 하나만 놓고 보는 리뷰는 같은 지적을 다음 덩이에서
다시 받게 됩니다. 소속 모듈은 위 표의 단계 라벨 앞자리(`M5.1` → `M5`)로 정해지므로 여기에
따로 적지 않습니다.

아래는 모듈별로 리뷰에서 특히 볼 것입니다. 대시보드의 `이식 진행`이 이 표를 읽어
모듈이 다 차면 알려주고, 상세 화면에서 해당 문단을 클립보드로 넘깁니다.

<!-- review-focus:start -->
| 모듈 | 리뷰에서 집중할 것 |
|---|---|
| M1 | 청크가 원문 오프셋과 해시로 되짚어지는가. 표 파싱이 레지스트리별 규칙에 갇혀 있는가 |
| M2 | 융합 순위가 각 경로의 점수 척도에 휘둘리지 않는가. SQL이 파이썬으로 새어나오지 않는가 |
| M3 | 측정이 설정 지문에 묶여 재현되는가. 골든 케이스가 구현을 따라 바뀌지 않았는가 |
| M4 | 모델이 증거 규칙을 스스로 정하지 못하게 막혀 있는가. 예산 초과와 스키마 거절이 서로 다른 실패로 남는가 |
| M5 | 타입 계약이 경계에서만 검증되는가. 오류 봉투가 5xx 세부나 비밀을 흘리지 않는가. 주입이 실제로 교체 가능한가. SSE가 클라이언트 이탈에 워크플로까지 취소하는가 |
| M6 | 데모가 실제 파이프라인을 쓰는가, 아니면 결과를 흉내내는가. 오프라인 기본 경로가 유료 공급자를 부르지 않는가 |
| M7 | 릴리스 가드가 게시되지 않은 것을 게시됐다고 주장하지 않는가. 아카이브가 비밀이나 코퍼스 원문을 담지 않는가 |
| M8 | 언어 라우팅이 번역 암과 분리돼 측정되는가. 패리티 게이트가 한쪽 언어에 맞춰 느슨해지지 않았는가 |
| M9 | 도구 선택을 모델에 넘기고도 중단 조건이 계약으로 남아 있는가. 인용 없는 종료가 막혀 있는가 |
| M10 | 레지스트리 어댑터가 SEC 이름을 경계 밖으로 내보내지 않는가. 한국어 lexical 통계가 언어별로 분리돼 있는가 |
<!-- review-focus:end -->

이식 덩이가 아닌 커밋: `17cad6e` `2790ece` `91b42d1` 리팩터·수정, `e130627` `afb8242` `3714d62` 문서·도구.

모듈 총량 (zero 대 현재):

| 모듈 | zero | assemble |
|---|---|---|
| M1 ingestion | 7파일 3471줄 | 10파일 4352줄 |
| M2 retrieval | 14파일 2184줄 | 17파일 2774줄 |
| M3 evals | 12파일 4901줄 | 20파일 5653줄 |
| M4 llm+observability+workflow | 14파일 3115줄 | 14파일 2999줄 |
| M5 api (대기) | 17파일 2035줄 | — |
| M9 agent (대기) | 11파일 2145줄 | — |
| M6 demo (대기) | 1파일 595줄 | — |
| M7 release (대기) | 7파일 509줄 | — |

### 대시보드

브랜치·품질·이식 진행·반복 점검을 한 화면에서 봅니다. 표시만 하고 아무것도 고치지
않습니다. `space`는 즉시 갱신, `1`~`6`은 섹션 접기, `m`은 증거 창 전환, `q`는 종료이고,
마우스가 되는 터미널이면 줄을 눌러 상세 화면으로 들어갑니다(`esc`로 복귀).

```bash
.dashboard/dashboard.sh            # 1초마다 제자리 갱신
.dashboard/dashboard.sh --once     # 한 프레임만 출력 (파이프·CI)
.dashboard/dashboard-refresh.sh    # 전체 스위트·수집 수 캐시 갱신
```

전체 스위트는 몇 분이 걸리므로 틱에서 돌리지 않습니다. 위 갱신 스크립트가
`.dashboard-cache/`에 결과를 넣고 대시보드는 그 값과 나이를 읽습니다. 캐시보다 나중에
수정된 소스가 있으면 그 결과는 이 트리를 설명하지 못하므로 나이 대신 경고를 띄웁니다.

작업 중인 세션이 대시보드에 한 줄을 올릴 수 있고, 읽는 쪽의 반응은
`.dashboard-cache/events.jsonl`에 한 줄짜리 JSON으로 쌓입니다.

```bash
.dashboard/dash-send.sh note "M5.1 범위 확인 중"
.dashboard/dash-send.sh ask "한 덩이로 갈까?" "그렇게" "나눠서"
.dashboard/dash-send.sh clear
```

클릭이 이스케이프 문자로 새어 나오는 터미널이면 `--no-mouse`로 끄고 키만 씁니다.
