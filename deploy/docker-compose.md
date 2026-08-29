# Docker Compose로 로컬 PostgreSQL 실행

루트의 `docker-compose.yml`은 로컬 통합 테스트용 PostgreSQL 16과 pgvector만
실행합니다. 애플리케이션 프로세스나 테스트를 자동으로 시작하지 않습니다.

## 테스트 경로

데이터베이스가 필요 없는 빠른 테스트는 다음과 같이 실행합니다.

```bash
uv run pytest -m "not live_postgres"
```

실제 PostgreSQL 동작을 확인할 때는 `db` 서비스를 시작하고 상태를 확인한 뒤
live 테스트를 실행합니다.

```bash
docker compose up -d db
docker compose ps db
uv run pytest -m live_postgres --require-live-postgres
```

`--require-live-postgres`를 사용하면 PostgreSQL에 연결할 수 없을 때 테스트를
건너뛰지 않고 실패로 처리합니다. `docker compose ps db`의 상태가 `healthy`가
된 뒤 테스트를 실행해야 합니다.

## 연결 설정

Compose의 로컬 개발용 기본값은 다음과 같습니다.

| 항목 | 값 |
|---|---|
| 이미지 | `pgvector/pgvector:pg16` |
| 데이터베이스 | `filing` |
| 사용자 | `filing` |
| 비밀번호 | `filing` |
| 호스트 포트 | `5432` |
| 연결 URL | `postgresql+asyncpg://filing:filing@localhost:5432/filing` |

이 자격 증명은 로컬 개발 전용이며 외부 환경이나 운영 배포에 사용하지 않습니다.

호스트의 `5432` 포트를 이미 사용 중이면 `DB_PORT`를 변경합니다. 테스트의
`DATABASE_URL`도 같은 포트를 가리켜야 합니다.

```bash
DB_PORT=55432 docker compose up -d db
DATABASE_URL=postgresql+asyncpg://filing:filing@127.0.0.1:55432/filing \
  uv run pytest -m live_postgres --require-live-postgres
```

## 서비스 수명주기와 데이터

테스트가 끝나면 서비스를 중지합니다. 이름 있는 `pg_data` 볼륨은 남으므로 다음
실행에서도 데이터가 유지됩니다.

```bash
docker compose stop db
docker compose start db
```

컨테이너와 네트워크만 제거하고 데이터 볼륨을 보존하려면 다음 명령을 사용합니다.

```bash
docker compose down
```

로컬 데이터까지 완전히 삭제하려면 `-v`를 사용합니다. 이 작업은 `pg_data` 볼륨을
제거하므로 복구할 수 없습니다.

```bash
docker compose down -v
```

## 상태 확인

```bash
docker compose ps db
docker compose logs db
```

연결 실패가 발생하면 먼저 서비스가 `healthy`인지, `DB_PORT`와 `DATABASE_URL`의
포트가 일치하는지 확인합니다.
