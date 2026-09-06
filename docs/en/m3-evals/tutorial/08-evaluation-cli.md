# M3.4 Tutorial 8 — Running against an isolated corpus

The last piece. Make the experiment run **without touching the real corpus.**

**Prerequisite:** The execution path of `retrieval_eval.py` is written through tutorial 7.

### An experiment must not touch the real corpus

Tutorial 7 finished the measuring instrument: `evaluate_retriever` walks a prepared corpus and turns one run into one artifact. What it left open is where that corpus comes from. Half of the experiment matrix changes chunk size, and experimenting at chunk size 500 requires re-chunking and re-indexing the whole corpus — while the only PostgreSQL this project has is the one holding the production tables.

Run that re-indexing against production and **the measured vectors are destroyed.** Seeding replaces the 1,200-character chunks with one experiment's 500-character variant, the embedding backfill overwrites the vectors M2 built, and the BM25 statistics are rebuilt for a corpus that stops existing at the next arm. No step raises an error — each one is the same code that legitimately maintains production — so the data meant to serve as portfolio evidence silently becomes a mid-experiment state, and no artifact records which arm left it that way.

The invariant of this document is therefore absolute: **an experiment must be able to run to completion — or die at any step — without the permanent tables changing by one byte.** So `temporary_corpus_session()` creates **temporary tables on a dedicated connection.** Parsing, chunking, indexing, and evaluation all happen there, and it all disappears when the connection closes. A second scratch database would isolate too, but it would need its own URL and its own pgvector install, and nothing would keep its schema honest against the one production actually runs. Temporary tables reuse the production database's exact environment — the same pattern used in M1.4 and M2.8.

```
ordered experiment configs → isolated corpus per arm → parsing/chunking/indexing measurement
    → 28 retrieval records → metrics over 24 positives → timestamped artifacts → budget table
```

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `build_chunking_batch` | **Define the structure** | Rebuilding the corpus by changing only chunk size |
| Temporary-table DDL | **Review the design decision** | Why hand-written DDL rather than the ORM |
| `temporary_corpus_session` | **Implement** the lifetime management yourself | Isolation bound to one connection |
| CLI arguments | **Define the structure** | Where the experiment axes open to the command line |
| `_run_cli` | **Inspect call order** | The flow that rebuilds a corpus per arm |

### 1. Rebuilding the corpus by changing only chunk size

#### Extend `app/evals/retrieval_eval.py` — building the chunking batch

**Learning action — define the structure:** note which hook in M1.4 the `chunker=` argument opens.

<!-- src: app/evals/retrieval_eval.py::build_chunking_batch -->
```python
def build_chunking_batch(
    target_text_chars: int,
    *,
    settings: Settings | None = None,
) -> SeedBatch:
    """Build one source-stable corpus arm without changing the canonical golden spans."""
    configured = settings or get_settings()
    entries = load_manifest(configured.corpus_dir / "manifest.json")
    chunk_config = ChunkConfig(target_text_chars=target_text_chars)
    return build_seed_batch(
        entries,
        expected_documents=20,
        chunker=lambda filing: chunk_filing(filing, chunk_config),
    )
```

**What to look for in the code**

- `chunker=` is passed to `build_seed_batch`. Because M1.4 left that hook open, the whole corpus can be rebuilt by changing only chunk size — manifest loading, integrity checks, and document construction are reused without duplication.
- The manifest and the source stay the same. **Only chunking changes**, which is why golden coordinates remain valid: a golden span is an offset pair into the immutable raw filing, not into any chunk, so no re-chunking can move it.
- `expected_documents=20` is still enforced. An arm that quietly lost a filing would score against a smaller corpus, and the comparison table would still present its numbers as comparable.

### 2. Why hand-written DDL rather than the ORM

#### Extend `app/evals/retrieval_eval.py` — creating temporary tables

**Learning action — review the design decision:** work out why `CREATE TEMP TABLE` cannot be replaced by `Base.metadata.create_all`.

<!-- src: app/evals/retrieval_eval.py::_create_temporary_corpus_tables -->
```python
async def _create_temporary_corpus_tables(connection: AsyncConnection, dimensions: int) -> None:
    extension = await connection.scalar(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    )
    if extension is None:
        raise RuntimeError("the configured PostgreSQL database does not have pgvector")
    await connection.execute(
        text(
            """
            CREATE TEMP TABLE documents (
                doc_id varchar(32) PRIMARY KEY,
                ticker varchar(16) NOT NULL,
                cik bigint NOT NULL,
                fiscal_year integer NOT NULL,
                form varchar(16) NOT NULL,
                filing_date varchar(10) NOT NULL,
                report_period varchar(10) NOT NULL,
                accession varchar(32) NOT NULL,
                url text NOT NULL,
                parse_status varchar(32) NOT NULL,
                item_index jsonb NOT NULL,
                source_length bigint NOT NULL,
                source_sha256 varchar(64) NOT NULL
            ) ON COMMIT PRESERVE ROWS
            """
        )
    )
    await connection.execute(
        text(
            f"""
            CREATE TEMP TABLE chunks (
                id bigserial PRIMARY KEY,
                doc_id varchar(32) NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
                item varchar(8),
                kind varchar(16) NOT NULL,
                ordinal integer NOT NULL,
                body text NOT NULL,
                context_header text NOT NULL,
                index_text text NOT NULL,
                start_char bigint NOT NULL,
                end_char bigint NOT NULL,
                source_sha256 varchar(64) NOT NULL,
                citation text NOT NULL,
                embedding vector({dimensions}),
                content_tsv tsvector GENERATED ALWAYS AS (
                    to_tsvector('english', index_text)
                ) STORED,
                created_at timestamptz NOT NULL DEFAULT now(),
                UNIQUE (doc_id, ordinal)
            ) ON COMMIT PRESERVE ROWS
            """
        )
    )
    await connection.execute(text("CREATE INDEX ON chunks USING gin (content_tsv)"))
    for statement in (
        """
        CREATE TEMP TABLE chunk_terms (
            chunk_id bigint NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
            lexeme text NOT NULL,
            tf integer NOT NULL,
            PRIMARY KEY (chunk_id, lexeme)
        ) ON COMMIT PRESERVE ROWS
        """,
        """
        CREATE TEMP TABLE chunk_lengths (
            chunk_id bigint PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
            dl integer NOT NULL
        ) ON COMMIT PRESERVE ROWS
        """,
        """
        CREATE TEMP TABLE lexeme_stats (
            lexeme text PRIMARY KEY,
            df integer NOT NULL
        ) ON COMMIT PRESERVE ROWS
        """,
        "CREATE INDEX ON chunk_terms (lexeme)",
    ):
        await connection.execute(text(statement))
    await connection.commit()
```

**What to look for in the code**

- `CREATE TEMP TABLE` is written by hand. SQLAlchemy's `create_all` builds permanent tables — temporary tables are not expressible in the ORM metadata — and it skips any table that already exists. Pointed at this database, it would see production's `documents` and `chunks`, create nothing, and let the experiment run against the live corpus: the exact accident this module exists to prevent.
- The table names are `documents` and `chunks` — **the same as production.** PostgreSQL puts the temporary schema ahead in the search path, so `persist_seed_batch` and the retrieval code use the temporary tables unmodified. That is the core mechanism of the isolation.
- The pgvector version is checked first and refused if absent. Probing `pg_extension` up front turns a confusing failure halfway through creating the `vector({dimensions})` column into a named precondition.
- `ON COMMIT PRESERVE ROWS` matches the PostgreSQL default for temporary tables and is spelled out on purpose. **The other two values, `ON COMMIT DELETE ROWS` and `ON COMMIT DROP`, clear the rows or the table at commit time, so the DDL records the premise that the corpus survives its commits.** The session commits several times between seeding and the first retrieval, and a reader auditing this DDL should not have to recall PostgreSQL's default table to know the corpus survives them.
- The `content_tsv` generated column and the GIN index mirror the production schema, and the two possible omissions fail very differently. Drop the column and the run dies loudly before any evaluation — `backfill_term_stats` reads it from `chunks`, and a shadowed name offers no fallback to production. Drop only the index and nothing fails: M2.4's lexical queries return identical rows through sequential scans, and the latency budget quietly measures an index shape production does not have.

> **Concept — Temporary-table shadowing**
>
> PostgreSQL resolves an unqualified table name through the schema search path, and the connection's temporary schema is searched ahead of everything else on that path. From the moment this connection creates a temporary table named chunks, that bare name means the temporary table for every later statement on the same connection — ORM inserts, raw SQL strings, even the LOCK TABLE inside the BM25 rebuild — while every other connection still resolves it to production.
>
> This is why the isolation costs zero changes to the seeding and retrieval code: those modules never schema-qualify their table names, so redirecting them is not a code path but a name-resolution consequence. The price is discipline. A column the temporary table lacks does not fall back to production — it simply does not exist — so the DDL must reproduce the production shape exactly.

### 3. Isolation bound to one connection

#### Extend `app/evals/retrieval_eval.py` — the temporary corpus session

**Learning action — implement the lifetime management:** note what `try/finally` guarantees and where `yield` sits.

<!-- src: app/evals/retrieval_eval.py::temporary_corpus_session -->
```python
@asynccontextmanager
async def temporary_corpus_session(
    engine: AsyncEngine,
    batch: SeedBatch,
    provider: EmbeddingProvider,
    *,
    target_text_chars: int,
    embedding_provider: str,
    clock: Clock = time.perf_counter_ns,
    started_at_ns: int | None = None,
) -> AsyncIterator[tuple[AsyncSession, IndexingBudgetMeasurement]]:
    """Index one isolated corpus arm and discard it when its connection closes."""
    started = clock() if started_at_ns is None else started_at_ns
    connection = await engine.connect()
    session: AsyncSession | None = None
    try:
        await _create_temporary_corpus_tables(connection, provider.dimensions)
        session = AsyncSession(bind=connection, expire_on_commit=False)
        await persist_seed_batch(session, batch)
        # One rebuild per corpus arm. Every BM25 experiment on this chunking shares
        # it, and the next chunk target gets its own corpus and its own statistics,
        # because df, avgdl, and dl are all properties of a particular chunking.
        await backfill_term_stats(session)
        backfill = await embed_missing_chunks(session, provider)
        if backfill.embedded != len(batch.chunks) or backfill.skipped_stale:
            raise RuntimeError("temporary corpus embedding backfill was incomplete")
        elapsed_seconds = (clock() - started) / 1_000_000_000
        measurement = assess_indexing_budget(
            target_text_chars=target_text_chars,
            document_count=len(batch.documents),
            chunk_count=len(batch.chunks),
            embedding_provider=embedding_provider,
            total_seconds=elapsed_seconds,
        )
        yield session, measurement
    finally:
        if session is not None:
            await session.close()
        await connection.close()
```

**What to look for in the code**

- `engine.connect()` takes **one connection** and the session binds to it. Temporary tables belong to a connection, so a session that picked a different one from a pool would find no tables.
- The indexing measurement wraps everything from `_create_temporary_corpus_tables` through backfill completion. Table creation, seeding, the BM25 statistics rebuild, and the embedding backfill all count as "indexing," because the budget's question is how long a fresh corpus of this chunking takes to become queryable — any preparation step left outside the clock could grow without ever failing the budget.
- `backfill.embedded != len(batch.chunks)` is checked. Evaluating on a partially embedded corpus produces low recall whose cause is preparation failure rather than retrieval — and nothing would say so.
- `finally` closes the session and then the connection. Closing the connection drops the temporary tables — no separate cleanup code is needed.

> **Concept — Connection-scoped lifetime**
>
> A PostgreSQL temporary table belongs to one session, and through this driver a session is one database connection: the table is invisible to every other connection and is dropped automatically the moment its connection closes. No shorter scope would work — a transaction ends long before the experiment does — and no longer scope exists for it to leak into.
>
> That scoping dictates the shape of this function. It acquires exactly one connection and binds the session to it, because an ordinary engine-bound session may borrow a different pooled connection per transaction — it would create the tables on one connection and then look for them on another. The same scoping makes cleanup free and crash-proof: there is no explicit DROP in the finally block because closing the connection is the drop, even when the process dies mid-arm.

The committed budgets artifact records what this measurement costs in practice: the 500-character arm indexes 20 documents into 12,984 chunks in about 38.5 seconds, the 1,200-character arm produces 9,172 chunks in about 33.9 seconds, and both pass the 300-second indexing budget with room to spare (the CLI starts this clock before `build_chunking_batch`, so the committed seconds include parsing and chunking as well). The numbers are reproducible from the repository:

```bash
python3 -c "import json; d = json.load(open('data/eval_runs/20260824T203336Z-budgets.json')); [print(i['target_text_chars'], i['chunk_count'], round(i['total_seconds'], 1), i['passed']) for i in d['indexing']]"
```

### 4. Opening the experiment axes to the command line

#### Extend `app/evals/retrieval_eval.py` — CLI arguments

**Learning action — define the structure:** check that the defaults reproduce M3's full matrix — the 2×3 core crossed with the lexical-ranker axis.

<!-- src: app/evals/retrieval_eval.py::_positive_int,arguments -->
```python
def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the isolated M3 ablation command."""
    parser = argparse.ArgumentParser(
        description="Run isolated source-span retrieval ablations and latency budgets."
    )
    parser.add_argument("--suite", default="m3-retrieval-v1")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_PATH)
    parser.add_argument("--artifact-dir", type=Path, default=Path("data/eval_runs"))
    parser.add_argument("--provider", choices=("deterministic", "openai"), default="deterministic")
    parser.add_argument("--target-text-chars", type=_positive_int, nargs="+", default=[500, 1200])
    parser.add_argument(
        "--strategies",
        choices=("lexical", "vector", "hybrid"),
        nargs="+",
        default=["lexical", "vector", "hybrid"],
    )
    parser.add_argument(
        "--lexical-rankers",
        choices=("ts_rank_cd", "bm25"),
        nargs="+",
        default=["ts_rank_cd", "bm25"],
        help="Lexical rankers to cross with every lexical and hybrid arm.",
    )
    parser.add_argument("-k", type=_positive_int, default=5)
    parser.add_argument("--candidate-k", type=_positive_int, default=20)
    parser.add_argument("--rrf-k", type=_positive_int, default=DEFAULT_RRF_K)
    parser.add_argument("--budget-queries", type=_positive_int, default=QUERY_BUDGET_COUNT)
    parser.add_argument("--persist-results", action="store_true")
    return parser.parse_args(argv)
```

**What to look for in the code**

- `--target-text-chars` and `--strategies` use `nargs="+"`. The axes can be widened or narrowed from the command line, and `--suite` or `--artifact-dir` can point a throwaway run away from the committed evidence.
- The defaults are `[500, 1200]`, all three strategies, and both lexical rankers. Run with no arguments and ten arms execute: per chunk size, the ranker axis splits the lexical and hybrid rows into two arms each, while the vector arm takes no ranker.
- `--provider` offers `deterministic` and `openai` only. The settings layer also names an `sbert` provider, but as pinned this command line cannot select it — a limit of the current flag, not a property of the experiment design.
- `_positive_int` is used as an `argparse` type. A bad value is caught during argument parsing rather than minutes into a corpus build.
- `--persist-results` defaults to off. Writing to the database has to be asked for explicitly, because a measuring run that stored itself by default would become the newest comparable baseline for the next run — the opt-in rule tutorial 7 established.

### 5. Rebuilding a corpus per arm

#### Complete `app/evals/retrieval_eval.py` — CLI execution

**Learning action — inspect call order:** count how many times a corpus is built per chunk size.

<!-- src: app/evals/retrieval_eval.py::_run_cli,main -->
```python
async def _run_cli(args: argparse.Namespace) -> dict[str, Any]:
    from app.db.bootstrap import bootstrap_schema
    from app.evals.ablation import ExperimentConfig, experiment_matrix, run_ablation

    if args.candidate_k < args.k:
        raise ValueError("candidate_k must be at least k")
    settings = get_settings().model_copy(update={"embedding_provider": args.provider})
    provider = get_embedding_provider(settings)
    cases = load_golden_cases(args.golden)
    recorded_at = datetime.now(UTC)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    all_outcomes = []
    indexing_measurements: list[IndexingBudgetMeasurement] = []
    query_budget: QueryBudgetMeasurement | None = None
    budget_ranker: LexicalRanker | None = None
    try:
        for target_text_chars in sorted(set(args.target_text_chars)):
            indexing_started_at_ns = time.perf_counter_ns()
            batch = build_chunking_batch(target_text_chars, settings=settings)
            configs = experiment_matrix(
                target_text_chars=(target_text_chars,),
                strategies=tuple(args.strategies),
                lexical_rankers=tuple(dict.fromkeys(args.lexical_rankers)),
                embedding_provider=args.provider,
                dimensions=provider.dimensions,
                k=args.k,
                candidate_k=args.candidate_k,
                rrf_k=args.rrf_k,
            )
            async with temporary_corpus_session(
                engine,
                batch,
                provider,
                target_text_chars=target_text_chars,
                embedding_provider=args.provider,
                started_at_ns=indexing_started_at_ns,
            ) as (session, indexing):
                indexing_measurements.append(indexing)

                async def evaluator(config: ExperimentConfig) -> RetrievalEvaluation:
                    retriever = make_retriever(
                        session,
                        strategy=config.strategy,
                        provider=provider,
                        lexical_ranker=config.lexical_ranker,
                        candidate_k=config.candidate_k,
                        rrf_k=config.rrf_k,
                    )
                    return await evaluate_retriever(
                        cases,
                        retriever,
                        suite=args.suite,
                        config=config.to_dict(),
                        k=config.k,
                        recorded_at=recorded_at,
                    )

                report = await run_ablation(
                    configs,
                    evaluator,
                    artifact_dir=args.artifact_dir,
                    recorded_at=recorded_at,
                )
                all_outcomes.extend(report.outcomes)

                if target_text_chars == max(args.target_text_chars):
                    budget_strategy = (
                        "hybrid" if "hybrid" in args.strategies else args.strategies[-1]
                    )
                    budget_ranker = None if budget_strategy == "vector" else args.lexical_rankers[0]
                    budget_retriever = make_retriever(
                        session,
                        strategy=budget_strategy,
                        provider=provider,
                        lexical_ranker=budget_ranker,
                        candidate_k=args.candidate_k,
                        rrf_k=args.rrf_k,
                    )
                    query_budget = await measure_query_budget(
                        [case.question for case in cases],
                        budget_retriever,
                        k=args.k,
                        query_count=args.budget_queries,
                    )

        if query_budget is None:
            raise RuntimeError("query budget was not measured")

        timestamp = recorded_at.strftime("%Y%m%dT%H%M%SZ")
        budget_path = args.artifact_dir / f"{timestamp}-budgets.json"
        budget_payload = {
            "schema_version": RAW_ARTIFACT_SCHEMA_VERSION,
            "recorded_at": _utc_text(recorded_at),
            "measurement_provenance": {
                "embedding_provider": args.provider,
                "budget_lexical_ranker": budget_ranker,
                "environment": "isolated-temporary-postgresql",
                "paid_api_calls": args.provider != "deterministic",
                "populated_corpus_embeddings_modified": False,
            },
            "indexing": [asdict(measurement) for measurement in indexing_measurements],
            "query_budget": asdict(query_budget),
        }
        budget_path.parent.mkdir(parents=True, exist_ok=True)
        budget_path.write_text(
            json.dumps(budget_payload, allow_nan=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        persisted = []
        if args.persist_results:
            await bootstrap_schema(engine)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                for outcome in all_outcomes:
                    persisted.append(
                        await persist_evaluation(
                            session,
                            outcome.evaluation,
                            raw_artifact_path=outcome.artifact_path,
                        )
                    )
                await session.commit()

        from app.evals.ablation import AblationReport

        combined = AblationReport(outcomes=tuple(all_outcomes))
        return {
            "comparison_table": combined.comparison_markdown(),
            "artifacts": [str(outcome.artifact_path) for outcome in all_outcomes],
            "budget_artifact": str(budget_path),
            "indexing": [asdict(measurement) for measurement in indexing_measurements],
            "query_budget": asdict(query_budget),
            "persisted": [asdict(result) for result in persisted],
        }
    finally:
        await engine.dispose()


def main() -> None:
    """Run the complete isolated M3 evaluation command."""
    result = asyncio.run(_run_cli(arguments()))
    print(result["comparison_table"])
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "comparison_table"}, indent=2
        )
    )
```

**What to look for in the code**

- The corpus is built **once** per chunk size and every strategy-ranker arm runs inside it. Re-indexing per arm would rebuild the same corpus five times over, the indexing measurement would count the same preparation repeatedly, and a difference between arms could always be blamed on corpora that were merely built at different moments.
- The engine is created with `NullPool`, so releasing a connection really closes it instead of returning it to a pool. The lifetime rule from section 3 is the reason: a pooled connection keeps its temporary tables, and the next arm checking it out would inherit — and shadow production with — the previous arm's corpus.
- The query budget is measured once, on the largest chunk target — under the defaults that is the 1,200-character corpus, the same chunking production serves — preferring `hybrid` and taking the first listed ranker, `ts_rank_cd` under the defaults. Measuring it per arm would multiply the run's cost without changing what the budget claims. The committed budgets artifact records exactly that arm: 200 sequential queries in about 29.8 seconds against the 90-second budget.
- `bootstrap_schema` is called only under `--persist-results`. A run that stores nothing never touches the permanent schema.
- `finally: await engine.dispose()` is present. A mid-experiment failure leaves no connection behind.

What a default run leaves behind is worth pinning down: exactly eleven files in `data/eval_runs/` — ten per-arm artifacts, five per chunk size because the ranker axis doubles the lexical and hybrid rows while the vector artifact carries no ranker suffix, plus one budgets artifact sharing the run's timestamp. The committed run in this repository has exactly that shape:

```bash
ls data/eval_runs/ | grep -c 20260824T203336Z
```

The command prints `11`.

The budgets artifact is born at the end of `_run_cli`, after every arm has finished: one indexing measurement per chunk target plus the single query-budget measurement, wrapped in a provenance block recording which embedding provider ran, whether any paid API was called, and that the populated corpus was not modified. Nothing ever edits the file — a later run writes a new timestamp beside it — and the committed copy is what this module's findings cite as latency evidence. Its scope stays what tutorial 7 established: wall-clock evidence for this machine, not a hosted-latency guarantee.

Append the module execution guard at the end of the file. Those two lines are what let `python -m app.evals.retrieval_eval` run directly.

```python
if __name__ == "__main__":
    main()
```

#### Create `app/evals/__main__.py` — module execution entry point

**Learning action — define the structure:** four lines. It is what makes `python -m app.evals` work.

```python
"""Command-line entry point for the complete M3 evaluation matrix."""

from app.evals.retrieval_eval import main

if __name__ == "__main__":
    main()
```

### Focused tests and the contracts they protect

```bash
uv run pytest tests/evals/test_04_ablation.py tests/evals/test_05_runner.py -q
```

| Value the test breaks | Contract being protected |
|---|---|
| A non-monotonic clock | A negative latency never contaminates the percentiles. |
| A partially embedded temporary corpus | Preparation failure is never reported as retrieval failure. |
| A baseline captured after storing | A run is never compared against itself. |
| Absent cases mixed into scoring | Absence judgment never enters recall. |
| An artifact with a different key order | Two runs' artifacts stay comparable with `diff`. |

The integration path needs a real PostgreSQL.

```bash
docker compose up -d db
uv run pytest tests/evals/test_06_postgres.py -q
```

A skip is not a pass but **environment verification incomplete.**

### What you should be able to explain now

- **What exactly is destroyed if an experiment runs against production tables?**
  - **Answer:** Re-chunking overwrites the serving corpus and its embeddings with one experiment's intermediate chunk-size variant. If production used a paid API embedding provider such as OpenAI, it also discards paid work; the default deterministic provider has no API charge.
- **Why must the temporary table names match the production ones?**
  - **Answer:** PostgreSQL places the temporary schema first, so matching names shadow the production tables and let unchanged seeding and retrieval code operate on the isolated corpus.
- **When does the corpus vanish without `ON COMMIT PRESERVE ROWS`?**
  - **Answer:** It does not vanish when the clause is omitted because PostgreSQL preserves temporary-table rows across commits by default. `ON COMMIT DELETE ROWS` clears the rows at commit, while `ON COMMIT DROP` removes the table.
- **Which symptom appears if `NullPool` is not used?**
  - **Answer:** A pooled connection reused by a later experiment arm can still own the previous arm's temporary tables or rows, causing name collisions or stale-corpus leakage. The session is already bound to one acquired connection, so switching to a second connection is not the issue here.
- **Why is a corpus built only once per chunk size?**
  - **Answer:** Vector, lexical, and hybrid must run against the same prepared corpus, and rebuilding it per strategy would triple identical work and invalidate the indexing measurement.

---

[← Previous: Evaluation run](07-evaluation-run.md) · [Module overview](../03-build.md) · [Next: Golden curation →](09-golden-curation.md)
