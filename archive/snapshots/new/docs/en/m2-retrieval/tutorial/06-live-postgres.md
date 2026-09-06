# M2.8 Tutorial 6 — Prove the whole path against real PostgreSQL

Every test so far **compiled SQL and checked the string.** Fast and offline, but there are things it cannot confirm.

- is the pgvector extension actually installed
- is the `vector(384)` dimension actually right
- does the `content_tsv` generated column actually get filled
- is the cosine ordering actually the direction we assumed

Syntactically correct does not mean semantically correct. This is where a live database first gets attached.

**Prerequisite:** Tutorial 5's `uv run pytest tests/retrieval/test_07_service.py -q` passes. This is the only document that uses a live PostgreSQL connection.

## What to verify and where to check it yourself

This document creates almost no new files. Instead it checks that what the previous five documents built **also holds on a live database**. So the learning action here is verification rather than writing.

| Stretch | Learning action | What to take away |
|---|---|---|
| `bootstrap_schema` | **Implement** the ordering constraint | the dependency direction between extension and tables |
| pgvector dimension check | **Check on a real database** | what compile-time verification cannot catch |
| `content_tsv` population check | **Check on a real database** | when a generated column is computed |
| Cosine ordering direction check | **Check on a real database** | the symptom of getting the operator direction backwards |
| Full acceptance run | **Interpret the result** | what separates a skip from a failure |

If the connection is unavailable, only this document's tests skip. A skip is not a pass, so writing "verified on live PostgreSQL" in a portfolio requires actually connecting and running it at least once.

## There is one ordering

In a fresh database the `vector(384)` type **does not exist.** Enabling the pgvector extension creates it.

So `bootstrap_schema` runs in exactly this order.

```
CREATE EXTENSION IF NOT EXISTS vector   ← first
        ↓
Base.metadata.create_all                ← then
```

Reverse it and creating the `chunks` table fails with "type vector does not exist." And thanks to `IF NOT EXISTS` it is idempotent, so the seed CLI can call it with `--create-schema` any number of times safely.

### Target file: `app/db/bootstrap.py`

<!-- src: app/db/bootstrap.py::ensure_vector_extension,bootstrap_schema -->
```python
async def ensure_vector_extension(connection: AsyncConnection) -> None:
    """Enable pgvector in the current database if it is not already enabled."""
    await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


async def bootstrap_schema(engine: AsyncEngine) -> None:
    """Enable pgvector before creating missing SQLAlchemy tables and indexes."""
    async with engine.begin() as connection:
        await ensure_vector_extension(connection)
        await connection.run_sync(Base.metadata.create_all)
```

**What to look for in the code**

- Both statements run inside one `engine.begin()` block, so a failure partway leaves no half-built schema behind.
- `run_sync` is what lets a synchronous SQLAlchemy API be driven from async code. `create_all` inspects and issues DDL synchronously; there is no async version of it.
- Neither function is called at import time. `--create-schema` is the only path that reaches them, which keeps schema creation an explicit act rather than a side effect of starting the program.

## What it takes for an integration test to be safe

A test that touches a real database carries risk, so there are several layers of defense.

**Only loopback is accepted.** The fixture takes only the configured project database and normalizes `localhost` to `127.0.0.1`. Even if a staging or production URL slips in, the test refuses it.

**It plays only in temporary tables.** The same approach as M1.4. Connection-scoped temporary `documents` and `chunks` are created and loaded with three deterministic vectors. They vanish when the connection closes, so **the application schema is untouched.**

**The reachability probe has a short timeout.** In an environment without a database, the test skips quickly instead of hanging for thirty seconds.

Within that, extension setup, exact cosine SQL, the generated FTS column, RRF, citation fields, and source hashes — **the whole path** — are proven at once.

```
bootstrap_schema → pgvector → tables → isolated test rows → vector/lexical search → RRF → grounded result
```

A skip here is not a pass but **"not yet verified."** The two have to be told apart.

This checkpoint introduces no new file. `app/db/bootstrap.py` and `app/ingestion/seed.py` already came from M1.4; here we finally exercise that boundary against PostgreSQL.

Nothing here is a new contract; every one was written earlier and asserted against compiled SQL. What changes is the authority behind the assertion.

| What compiled SQL could not tell you | What a real database settles |
|---|---|
| Whether the `vector` type exists at all | pgvector is installed and enabled. |
| Whether `vector(384)` matches the stored column | Query and column dimensions really agree. |
| Whether `content_tsv` is ever populated | The generated column is filled on write. |
| Which direction `<=>` actually orders | Nearest evidence really does rank first. |
| Whether the two paths return the same rows | RRF fuses lists drawn from one corpus. |

Save the file before asking the test for its verdict.

```bash
docker compose up -d db
uv run pytest tests/retrieval/test_08_postgres.py -q
```

A clean pass means the live test passes against the configured loopback PostgreSQL database. A skip means the environment proof is incomplete, not that M2 passed.

The rule for moving on is simple: do not mark M2 complete on a failure or skip. Keep the application corpus untouched and rerun after the project database is reachable.

When it fails, if the test skips, inspect `docker compose ps db` and the configured loopback database URL. If PostgreSQL reports that type `vector` does not exist, verify that `CREATE EXTENSION IF NOT EXISTS vector` runs before `Base.metadata.create_all`.

## What you should be able to explain now

- **Which class of defect can compiled-SQL tests never catch?**
  - **Answer:** They cannot catch live database behavior such as a missing extension or type, generated-column behavior, or the actual ordering produced by PostgreSQL operators.
- **Why must the extension be enabled before `create_all` and not after?**
  - **Answer:** `create_all` must resolve the `vector(384)` column type while creating the table, and that type does not exist until pgvector is enabled.
- **Why is a skipped integration test not the same as a passing one?**
  - **Answer:** A skip means the required environment was unavailable, so the live PostgreSQL behavior remains unverified.
- **What do temporary tables protect that a dedicated test database would not?**
  - **Answer:** They keep the application's persistent schema and rows untouched even inside the test database, and they disappear automatically with the connection.

# Complete acceptance path

```bash
docker compose up -d db
uv run python -m app.ingestion.seed --create-schema
uv run python -m app.retrieval --provider deterministic --embed-missing --query "NVDA 2024 R&D" -k 3
uv run pytest tests/retrieval -q
uv run ruff check --no-fix app tests scripts
uv run python scripts/check_doc_code.py
```

Read [verification](../05-verify.md) before interpreting a skip, changing providers, or adding an approximate index.

---

[← Previous: Service](05-service.md) · [Module overview](../03-build.md)
