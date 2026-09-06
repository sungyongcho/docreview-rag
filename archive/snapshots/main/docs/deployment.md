# Deployment

로컬 개발 구성 → 배포 가능한 서비스 레이아웃 매핑. **정직하게:** 실제 배포는 아직 안 했다. 이 문서는 "어떻게 배포할지"의 설계다.

## 1. 로컬 (현재)

```
docker compose (db=pgvector, redis)   ← 인프라만 컨테이너
로컬 프로세스:
  - uvicorn app.main:app              (API)
  - arq app.worker.settings.WorkerSettings  (워커)
```
- API·워커는 로컬에서 직접 실행(모델 로딩 확인·디버깅 편의). DB·Redis만 compose.

## 2. 배포 레이아웃 (설계)

```
                 ┌──────────────┐
   인터넷 ─────▶ │  API (N개)   │──┐   FastAPI 컨테이너 (Dockerfile)
                 └──────────────┘  │
                                   ├─▶ Managed Postgres + pgvector   (Neon / Supabase / RDS)
                 ┌──────────────┐  │
                 │ 워커 (M개)   │──┤   같은 이미지, arq 엔트리포인트
                 └──────────────┘  │
                                   └─▶ Managed Redis                 (Upstash / ElastiCache)
```

| 로컬 | 배포 매핑 |
| --- | --- |
| `docker compose db` | **Managed Postgres (pgvector 지원 필수)** — Neon/Supabase/Railway/RDS |
| `docker compose redis` | **Managed Redis** — Upstash/ElastiCache |
| `uvicorn` (로컬) | **API 컨테이너** ×N (수평 확장, stateless) |
| `arq` (로컬) | **워커 컨테이너** ×M (큐에서 잡 나눠 가짐) |
| `.env` | **배포 시크릿/환경변수** (OPENAI_API_KEY, DATABASE_URL, REDIS_URL, EMBEDDING_PROVIDER=st) |

## 3. 컨테이너화 할 일 (Phase B, [`plan.md`](plan.md) Step 16)

- [ ] `Dockerfile`: `uv sync --frozen --no-dev` (dev 의존성 제외). API·워커 **같은 이미지**, 커맨드만 다르게.
- [ ] compose에 api·worker 서비스 추가 (`profiles: app`) 또는 배포는 별도 오케스트레이터.
- [ ] **메모리:** sentence-transformers(임베딩 ~100MB) + cross-encoder(~100MB)가 API·워커 양쪽에 로드 → 인스턴스 **RAM 512MB+**.
- [ ] 배포 DB에 시드 1회 (`python -m app.db.seed`, st 384차원).
- [ ] **CORS** — 프론트 도메인 허용.

## 4. 확장·운영 노트

- **API는 stateless** → 수평 확장 자유. 세션은 요청 스코프, 모델은 프로세스 싱글턴.
- **워커 수평 확장** → 여러 워커가 한 Redis 큐에서 잡 소비. `runs` 테이블이 상태 진실.
- **상태는 전부 Postgres** → 재시작해도 진행 중 잡·결과 유지. Redis는 큐(휘발).
- **비용 가드(운영):** `/review`(LLM 사용)는 rate-limit 또는 canned 모드. `/retrieve`(LLM 없음)는 공개 안전. 상세 [`plan.md`](plan.md) Phase B.

## 5. 아직 안 한 것 (정직)

- 실제 배포·CI/CD·모니터링 대시보드·인증/멀티테넌시.
- Alembic 마이그레이션(현재 `create_all`) — 배포 전 도입 권장.
- 프로바이더 폴백 실배선(2번째 프로바이더 키).
- 자세한 향후 계획 → [`plan.md`](plan.md) Phase B(Step 16~19).
