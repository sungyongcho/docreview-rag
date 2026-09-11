# DEVELOPMENT_STORY_OUTLINE 검토 노트

> 참고용 검토 노트입니다. `docs/DEVELOPMENT_STORY_OUTLINE.md`를 대신하지 않습니다.
> 사용자가 읽고 채택 여부를 판단합니다. 아래 "제안" 문장은 그대로 쓰지 말고 사용자 문장으로 확정합니다.

## 0. 조사 근거

- Git: `main` 213커밋(전부 squash/rebase, merge 0), 2026-08-28 루트 `ab2c23b`부터. 6~8월 초 `new`/`zero`/`assemble` 이력은 현재 오브젝트 그래프에서 도달 불가, `v1` 브랜치 `archive/provenance/history.jsonl`(2026-06-08~09-02)에만 보존.
- GitHub: 저장소 2026-09-05 생성, 이슈 86 / PR 126(머지 119). 작업 상태 원장(`commit-it:work-state`) 84건, 인수인계(`ops:handoff:v2`) 7건.
- 태그는 `v2.0.0`(`61cb17b`) 하나. `v1`은 태그가 아니라 parentless 아카이브 브랜치(`ccd4fa4`).
- 증거: `docs/issue-evidence/` 49개 그룹(대부분 UI 캡처), `docs/log.md`(8/28 학습 메모), `docs/m10.md`(DART/한국어 설계 노트).

## 1. 사실 검증 — 본문 쓰기 전에 고쳐야 할 것

| 드래프트 뉘앙스 | 실제 (근거) | 수정 방향 |
|---|---|---|
| 이미지/그림까지 파싱 | OCR/PDF/vision 없음. `img` 제거, 순수 HTML 텍스트·표 추출 (`app/ingestion/parser.py`) | "표 포함 HTML 텍스트 파싱"으로 한정. "이미지가 핵심 정보를 담지 않는다고 판단"은 사용자 경험으로 유지 가능 |
| "BM25 사용" | 기본 어휘 랭커는 PostgreSQL `ts_rank_cd`. BM25는 옵션(프리셋/평가) 구현 (`app/retrieval/bm25.py`) | "BM25를 별도 옵션으로 구현·비교" |
| 하이브리드 점수 결합 | RRF(rank-only), `1/(60+rank)`, `rrf_k=60` (`app/retrieval/hybrid.py`) | RRF로 명시. 점수 가중합 아님 |
| text-embedding 3 med/large | `text-embedding-3-large` + `dimensions=384`(Matryoshka 절단), DB 계약 `Literal[384]` (`app/openai_models.py:60-65`) | "large 384차원 고정". 384 선택 이유는 코드/문서에 없음 → 품질/비용 실측 주장 금지 |
| 답변 모델 | DEV 예시 terra(현재 `.env`에 `REVIEW_MODEL` 없음 → 답변 503), PROD는 luna 강제 (`app/openai_models.py`, `deploy/gcp/docker-compose.deploy.yml`) | DEV/PROD 구분해서 서술 |
| 리랭커 상시 사용 | Accuracy 프리셋에서만 `cross-encoder/ms-marco-MiniLM-L-6-v2` | "선택형" |
| 배포/운영 중 | 실제 배포 없음. PR #210 명시 "No cloud creation, deployment" | "확정한 스펙·예상 비용" |
| 공개 한도 단일 | GCP 2/min·5/day·$0.10·$0.005, HF 10/100·$0.01 | 배포판 명시 |
| 인용 sha `101bae7`, `df094df` | 현재 git에서 도달 불가(아카이브 전용) | 전체 sha + "v1 아카이브 기록" 표기: `101bae7d37a7f2002a533b15a08ca9bbbcda25bd`, `df094df2a57601d1eec5dc4a8c507c98c84ea63f` |
| LangChain/LangGraph 재구현 | 의존성/코드 근거 0 | "튜토리얼 학습 후 직접 구현"만 |

현재 이력에서 유효한 인용: `2b47b71`, `7532b72`, `dd4cc60`, `c5bb137`, `3c83469`.

## 2. `[...]` 항목별 결론과 제안 텍스트

### L11 왜 지금? — 통합 권장
별도 소제목은 비어 보입니다. "왜 이 프로젝트를 하게 됐는지"에 한 줄로 붙이세요.
제안: "RAG를 개념으로만 알던 상태에서, 공시처럼 근거 검증이 중요한 문서에 직접 적용해 보는 것이 목표였다."

### L15 파싱 기법 명칭
제안: "BeautifulSoup + html.parser 기반 DOM 텍스트 추출(태그 스트리핑). iXBRL `ix:*`는 unwrap, `script/style/img`는 제거하고 원문 라인·오프셋을 보존했다. EDGAR는 폰트 굵기·Item 제목 휴리스틱, DART는 `SECTION-1/TITLE` 마크업을 기준으로 분절했다."

### L16 청킹 — 프레이밍 수정
사실: target 2,048 tokens, max 8,192, 구조(group·heading·table) 경계 준수, **overlap 없음**(원문 span 정렬·인용 정확도), 표는 행→셀 분할 + 헤더 반복, 청크 앞 context header(citation·제목·헤딩).
제안: "검색 속도보다 **검색 정밀도와 인용 정확도**를 위해 구조 경계를 지키고 원문 위치를 유지하는 청킹을 택했다."

### L17 1-3 임베딩
사실: OpenAI `text-embedding-3-large` 384차원, deterministic 해시(fallback), sbert(MiniLM L6/L12) 로컬 옵션.
제안: "개발 중 OpenAI 임베딩으로 전환해 384차원으로 고정했고, 학습·테스트용으로는 결정적 해시와 로컬 sentence-transformers 경로를 두었다."

### L18 1-4 — 문장 다듬기
사실: RRF `1/(60+rank)`, BM25 k1=1.2·b=0.75, IDF `ln(1+(N-df+0.5)/(df+0.5))`, tf 포화식.
제안: "IDF에 로그를 취해 희귀 단어를 가중하고, tf 포화로 반복 등장의 한계 효용을 제한하는 구조가 인상적이었다. 같은 로직을 SQL 기반으로 구현해 옵션 랭커로 비교했다."

### L19/L21 개발 순서 추적 + 누락 점검
기록 기반 실제 순서:
1. 파싱(M1: 10-K Item, 표) → 2. **표 정규화(rowspan/colspan→그리드→헤더 추론→마크다운)** → 3. 청킹 → 4. DB 적재 → 5. 임베딩 → 6. **RRF·retrieval service** → 7. **BM25·로컬 임베딩/리랭킹** → 8. 평가 프레임워크·ablation·golden → 9. **DART 파서·한국어 테이블** → 10. **한국어 lexical·KR golden·2×2 parity** → 11. API 경계·CLI/compose → 12. UI(Build·Measure·System)·Help → 13. 로컬 엔진(Ollama).

드래프트에서 빠진 항목: ①표 정규화, ②DART·한국어 arm, ③평가 프레임워크/cross-lingual, ④타입화된 실행 실패·run trace, ⑤답변 엔진 라우팅·증거 선택.

### L22 제목
추천: **"2. AI 협업 개발 루프: 반복은 줄이고 판단은 유지"**
대안: "AI와 함께 품질과 속도를 끌어올린 과정" / "판단은 내가, 실행은 AI와".

### L23 형상관리 imply — 내부 정보 노출 없이
제안: "이슈 계약으로 범위를 고정하고, 작업을 격리한 뒤 검증 증거와 인수인계 상태를 기록하는 내부 작업 흐름을 직접 운영·개선 중이다." (도구명·worker ID·비공개 저장소 구조는 노출하지 않음)
숫자 근거(원하면): 이슈 86 · PR 126(머지 119) · 작업 상태 원장 84 · 인수인계 7.

### L25 web api 검증
맞습니다. "RAG 파이프라인은 CLI로도 충분하지만, 이 프로젝트는 공개 웹 서비스를 목표로 FastAPI + 웹 UI로 구성했다."

### L34 테스트 보충
제안: "구현과 함께 테스트를 생성·수정하고, 모듈 미러 구조(`app/X/y.py` → `tests/X/test_y.py`)로 두었다. 스키마처럼 실제 DB가 필요한 검증은 `live_postgres` 마커로 분리해 격리된 PostgreSQL에서만 실행했다."

### L36 API 한계 보충
제안: "공개 서비스는 IP당 2회/분·5회/24시간, 호출당 $0.005, UTC 일일 $0.10 예약 상한으로 제한했다. 임베딩과 답변 호출 모두 실제 호출 직전에 상한을 예약하고, 영속 SQLite 원장으로 원자 처리한다(단일 호스트 범위). SDK 자동 재시도는 비활성화해 상한을 우회하지 못하게 했다."

### L37 클라우드 비용 보충
제안: "e2-medium 온디맨드 약 $0.034/h(월 약 $25) + 30GB 디스크 약 $1 → **월 약 $26**. 임시 IP 무료(고정 예약 시 +$3), Firebase/Cloudflare 무료 등급, OpenAI는 일일 $0.10 상한. 약정(CUD)이나 spot으로 절감 가능."
톤: "운영 중"이 아니라 "확정한 예상 스펙".

### L38 한 개 더 추천
**"실패를 타입으로 나누는 진단 설계"** (workflow budget / provider failure / node error). 기능 추가보다 재현·디버깅에 직접 기여한 설계 협업.

### L43a 데이터 (가벼운 텍스트)
사용 가능: `이슈 86 · PR 126(머지 119) · 작업 상태 원장 84 · 인수인계 7 · 리뷰 승인 라벨 운영`.
불가: 에이전트 토큰 사용량(저장소에 기록 없음).

### L43b 단점 → 문제 해결 재서술
제안: "대기·비용·불만족은 있었지만, **범위를 이슈 계약으로 고정하고 작업을 격리하고 검증 증거를 보존하며 라이브 세션으로 즉시 피드백**하는 방식으로 재작업을 줄였다."

### L44 톤 가이드
- 이력서 원칙: 역량 언어·정체성 먼저·한계 먼저. "worked with Codex"류 표현은 이력서/README 금지.
- 사이트 `/logs`는 AI 활용이 주제인 공간이라 도구 공개 선례가 있음 → 이 로그에서는 활용 방식이 드러나도 됨.
- 문장 공식: "관찰 → 시도 → 결과/한계". "AI를 못 쓴다"가 아니라 "판단·승인은 내가, 실행 속도는 AI".

### L47 §3 개념 초안 (참고용 — 문장은 사용자가 확정)
뼈대:
1. 검색 지표(recall@k·hit·MRR)는 검색 품질이고 답변 품질과 별개다.
2. `SUPPORTED`는 "근거 확인 필요" 신호이며 정답 보증이 아니다.
3. `NOT_IN_DOCS`(근거 부족)와 운영 실패(제공자·노드·예산)는 다른 결과다.
4. 저장된 실행 기록을 재사용해 비교하고, 새 실행은 조건이 같을 때만 비교한다.
5. 숫자를 읽을 때는 데이터셋·인덱스·설정이 같은지 먼저 확인한다.

### L51~58 §4 초안 (표)
스펙/비용:
| 항목 | 내용 | 비용 |
|---|---|---|
| GCP e2-medium | 2 shared vCPU, 4GB + 2GB swap, 30GB pd-standard | 약 $26/월 |
| 외부 IP | 임시(고정 예약 시 +$3) | $0 |
| Firebase Hosting | 정적 export | $0 |
| Cloudflare Worker | gomoku Worker와 공유 | $0 |
| OpenAI | 일일 $0.10 상한 | ≤ $0.10/day |

임베딩 가격(코드 근거 `app/openai_models.py:60-65`):
| 모델 | 입력 | 출력 |
|---|---|---|
| `text-embedding-3-large` | $0.13 / 1M tokens | $0 |

PROD/DEV 차이: PROD는 파싱·청킹·임베딩이 끝난 코퍼스를 DB에 적재한 상태로 공개 기능만, DEV는 수집·파싱·청킹·임베딩·평가 전체 파이프라인 + admin/로컬 엔진.

### L60 프레임워크 미사용 — 포함 권장(짧게)
근거: `pyproject`에 langchain/langgraph 의존성 없음, `new`/`zero` 학습 분리 흔적 존재.
제안: "튜토리얼로 개념을 익힌 뒤에는 이해와 통제를 위해 프레임워크 없이 직접 구현했다."

### L61 agentic 문장 — 검증 결과 타당
근거: agent tool loop 커밋(`8881041`, `d1dd9b7`), workflow runner.
제안: "RAG의 검색-생성 루프를 직접 만들어 보며, 도구 호출과 상태를 다루는 agentic 흐름으로 확장해 생각하게 됐다."

### L62 아쉬움 — 포함 권장(단, 범위 결정으로)
제안: "시간상 하이퍼파라미터·대안 알고리즘을 전수 실험하기보다 **평가 프레임워크와 재현 가능한 실행 기록을 남기는 쪽**을 택했다."

### L64 느낀점 1개 추천
**"품질은 모델 교체보다 데이터(파싱·청킹·평가셋)에서 결정됐다."** 근거: 일정 대부분이 표 파싱·한국어 lexical·golden·parity에 투입됨.

### L68 대화록 반영
가져올 조각: ① `new`(완성본)/`zero`(학습용) 분리 학습 루프, ② ORM·BM25/IDF 질문, ③ `assemble` 재조립·검토 루프.
정리할 것: `"""` 블록, `----------------------`, `##2.`/`##3.` 오타(→ `## 2.`/`## 3.`), 중복 골격.

### L92 Codex Forecast
References에서 제거 권장. 유지하려면 §2 본문에 유머 한 줄로만.

## 3. 프로세스 이슈 (진행 전 결정 필요)

1. **저자 규칙 충돌**: #30/PR #38은 "에이전트는 본문·사례·학습 설명·홍보 문구를 작성하지 않는다". 지금 브래킷 요청(제목·§3 초안·보충·polish)은 명시적 예외 승인이 필요.
2. **커밋 위치**: 로그 변경은 `docs/30-development-log` 브랜치/PR #38(merge 금지)로 가야 하는데, 현재 수정본은 `interactive/4-manual-ui-polish` 워킹트리에 있음.
3. **미결**: #30 acceptance 3건 미체크, "확인 필요" 4건 답변 없음.
4. 파일 위생은 사용자 텍스트를 건드리므로 별도 승인 후 진행.

## 4. 다음 선택지

- (a) 이 노트의 제안을 반영해 `docs/30-development-log`에 커밋
- (b) `docs/DEVELOPMENT_STORY_OUTLINE.md` 파일 위생(`"""`·오타)만 정리
- (c) §3/§4 초안을 더 구체화
- (d) 배포 논의로 복귀
