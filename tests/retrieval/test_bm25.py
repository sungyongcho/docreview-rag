"""PostgreSQL BM25 ranking and statistic-rebuild tests."""

import asyncio
from dataclasses import asdict
import hashlib
import inspect
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text as sql, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings, get_settings
from app.db.bootstrap import ensure_bm25_stats_invalidation
from app.db.models import Base, Chunk as ChunkModel, ChunkEmbedding
from app.ingestion.chunk import Chunk
from app.ingestion.parser import Block, ParsedFiling, Section
from app.ingestion.seed import (
    SeedBatch,
    _persist_sources,
    document_upsert_statement,
    filing_records,
)
import app.retrieval as public
from app.retrieval import __main__ as cli, bm25, service
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from app.retrieval.types import RetrievalFilters
from tests.ingestion.support import filing_document, filing_source
from tests.live_postgres import live_postgres_unavailable
from tests.retrieval.support import hit_values, normalized_sql

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "bm25_sample.json").read_text(encoding="utf-8")
)
DOCUMENTS = {document["id"]: document["tokens"] for document in FIXTURE["documents"]}
QUERY = FIXTURE["query"]
FIXTURE_ID = {index + 1: document["id"] for index, document in enumerate(FIXTURE["documents"])}
K1 = FIXTURE["k1"]
B_PARAM = FIXTURE["b"]


def reference_scores(
    documents: dict[str, list[str]],
    query: list[str],
    *,
    k1: float = K1,
    b: float = B_PARAM,
    idf: str = "lucene",
) -> dict[str, float]:
    """Score every document with the published BM25 formula, in plain Python.

    This is the oracle the SQL implementation is checked against. It repeats the
    formula rather than importing it so that a mistake in ``bm25_statement`` cannot
    hide by being made twice.

    Repeated query terms are collapsed first. PostgreSQL cannot see them either:
    the statement turns the query into a ``tsvector``, and a ``tsvector`` records
    each lexeme once regardless of how often it was written.
    """
    n_documents = len(documents)
    lengths = {doc_id: len(tokens) for doc_id, tokens in documents.items()}
    avgdl = sum(lengths.values()) / n_documents

    document_frequency: dict[str, int] = {}
    for tokens in documents.values():
        for term in set(tokens):
            document_frequency[term] = document_frequency.get(term, 0) + 1

    scores: dict[str, float] = {}
    for doc_id, tokens in documents.items():
        total = 0.0
        for term in dict.fromkeys(query):
            tf = tokens.count(term)
            if tf == 0:
                continue
            df = document_frequency[term]
            ratio = (n_documents - df + 0.5) / (df + 0.5)
            weight = math.log(1 + ratio) if idf == "lucene" else math.log(ratio)
            norm = 1 - b + b * lengths[doc_id] / avgdl
            total += weight * (tf * (k1 + 1)) / (tf + k1 * norm)
        scores[doc_id] = total
    return scores


def ranking(scores: dict[str, float]) -> list[str]:
    """Order document ids by descending score, breaking ties by id."""
    return sorted(scores, key=lambda doc_id: (-scores[doc_id], doc_id))


def rounded(scores: dict[str, float]) -> dict[str, float]:
    """Round to the precision the committed fixture records."""
    return {doc_id: round(score, 4) for doc_id, score in scores.items()}


@pytest.fixture(scope="module")
def database_url() -> URL:
    """Return the configured PostgreSQL URL for optional live tests."""
    return make_url(get_settings().database_url)


# --------------------------------------------------------------------------
# The formula, checked against a corpus small enough to verify by hand.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("idf", "b", "expected_key"),
    [
        ("lucene", B_PARAM, "expected_scores"),
        ("lucene", 0.0, "expected_scores_b0"),
        ("robertson", B_PARAM, "expected_scores_robertson"),
        ("robertson", 0.0, "expected_scores_robertson_b0"),
    ],
)
def test_reference_implementation_reproduces_the_committed_fixture(idf, b, expected_key):
    """Reproduce every committed BM25 fixture score with the Python oracle."""
    scores = reference_scores(DOCUMENTS, QUERY, b=b, idf=idf)
    assert rounded(scores) == FIXTURE[expected_key]


def test_corpus_statistics_match_the_fixture():
    """Match document lengths and aggregate corpus statistics."""
    lengths = {doc["id"]: doc["dl"] for doc in FIXTURE["documents"]}
    assert lengths == {doc_id: len(tokens) for doc_id, tokens in DOCUMENTS.items()}
    assert FIXTURE["corpus_stats"]["n_documents"] == len(DOCUMENTS)
    assert FIXTURE["corpus_stats"]["avgdl"] == sum(lengths.values()) / len(lengths)


def test_document_frequency_counts_documents_not_occurrences():
    """``df`` is how many chunks contain a lexeme, never how often it occurs."""
    occurrences = sum(tokens.count("risk") for tokens in DOCUMENTS.values())

    assert occurrences == 11
    assert FIXTURE["corpus_stats"]["df"]["risk"] == len(DOCUMENTS) == 5
    assert FIXTURE["corpus_stats"]["df"]["market"] == 3


def test_length_normalisation_decides_the_top_document():
    """Show that length normalization changes the top-ranked document."""
    normalized = reference_scores(DOCUMENTS, QUERY, b=0.75)
    unnormalized = reference_scores(DOCUMENTS, QUERY, b=0.0)

    assert ranking(normalized)[:2] == ["d1", "d4"]
    assert ranking(unnormalized)[:2] == ["d4", "d1"]


def test_robertson_idf_goes_negative_and_inverts_the_ranking():
    """Expose negative Robertson weights for corpus-wide terms."""
    lucene = reference_scores(DOCUMENTS, QUERY, idf="lucene")
    robertson = reference_scores(DOCUMENTS, QUERY, idf="robertson")

    assert FIXTURE["idf"]["robertson"]["risk"] < 0
    assert all(score > 0 for score in lucene.values())
    assert all(score < 0 for score in robertson.values())
    assert ranking(lucene).index("d1") < ranking(lucene).index("d5")
    assert ranking(robertson).index("d5") < ranking(robertson).index("d1")


def test_lucene_idf_stays_nonnegative_for_every_document_frequency():
    """Keep Lucene inverse document frequency nonnegative."""
    n_documents = len(DOCUMENTS)
    for df in range(1, n_documents + 1):
        ratio = (n_documents - df + 0.5) / (df + 0.5)
        assert math.log(1 + ratio) >= 0


def test_repeated_query_terms_are_scored_once():
    """Drive duplicate-term coverage from the committed fixture contract."""
    once = reference_scores(DOCUMENTS, QUERY)
    duplicate = reference_scores(DOCUMENTS, FIXTURE["duplicate_query"])

    assert duplicate == once
    assert rounded(duplicate) == FIXTURE["expected_scores_duplicate_query"]


# --------------------------------------------------------------------------
# The statement: bound, derived from the stored tsvector, deterministic.
# --------------------------------------------------------------------------


def test_statement_scores_from_persisted_corpus_statistics():
    """Read one-row corpus metadata instead of aggregating every query."""
    sql, _params = normalized_sql(bm25.bm25_statement("market risk", 5))

    assert "FROM chunk_terms" in sql
    assert "JOIN lexeme_stats ON lexeme_stats.lexeme = chunk_terms.lexeme" in sql
    assert "JOIN chunk_lengths ON chunk_lengths.chunk_id = chunk_terms.chunk_id" in sql
    assert "FROM bm25_corpus_stats" in sql
    assert "count(" not in sql
    assert "avg(" not in sql
    assert "GROUP BY chunk_terms.chunk_id" in sql


def test_statement_binds_the_query_and_never_interpolates_it():
    """Bind raw queries and numeric parameters without SQL interpolation."""
    query = "capital expense'; DROP TABLE chunks --"
    statement = bm25.bm25_statement(query, 7, k1=1.5, b=0.4)
    sql, params = normalized_sql(statement)

    assert "websearch_to_tsquery(" in sql
    assert "to_tsvector(" in sql
    assert "tsvector_to_array(" in sql
    assert query not in sql
    assert bm25.relaxed_websearch_query(query) in params.values()
    assert bm25.positive_websearch_text(query) in params.values()
    assert 1.5 in params.values()
    assert 0.4 in params.values()
    assert 7 in params.values()


def test_statement_projects_the_complete_hit_surface_and_orders_deterministically():
    """Project complete hits with stable source tie-breakers."""
    statement = bm25.bm25_statement("market risk", 5)
    sql, _params = normalized_sql(statement)

    assert set(statement.selected_columns.keys()) == {
        "chunk_id",
        "doc_id",
        "item",
        "kind",
        "citation",
        "start_char",
        "end_char",
        "source_sha256",
        "body",
        "context_header",
        "index_text",
        "score",
    }
    assert "ORDER BY" in sql
    assert (
        'chunks.doc_id COLLATE "C" ASC, chunks.source_sha256 COLLATE "C" ASC, '
        "chunks.start_char ASC, "
        "chunks.end_char ASC, chunks.id ASC"
    ) in sql


@pytest.mark.parametrize(
    ("idf", "present", "absent"),
    [("lucene", "ln(%(param_1)s +", "ln(((CAST"), ("robertson", "ln(((CAST", "ln(%(param_1)s +")],
)
def test_statement_emits_the_selected_idf_variant(idf, present, absent):
    """Emit the selected inverse-document-frequency formula."""
    sql, _params = normalized_sql(bm25.bm25_statement("market risk", 5, idf=idf))

    assert present in sql
    assert absent not in sql


def test_statement_matches_the_relaxed_websearch_query_but_scores_only_positives():
    """Preserve phrase and negation matching without scoring excluded terms."""
    sql, params = normalized_sql(bm25.bm25_statement('"market risk" -volatility', 5))

    assert "MATERIALIZED" in sql
    assert "websearch_to_tsquery(" in sql
    assert "chunks.content_tsv @@ bm25_query.tsquery" in sql
    assert '"market risk" -volatility' in params.values()
    assert '"market risk"' in params.values()


def test_statement_applies_every_shared_filter():
    """Apply every shared chunk and issuer filter."""
    filters = RetrievalFilters(
        doc_ids=("NVDA-FY2024",),
        issuers=("NVDA",),
        fiscal_years=(2024,),
        forms=("10-K",),
        items=(None, "7"),
        kinds=("table",),
    )
    sql, params = normalized_sql(bm25.bm25_statement("market risk", 5, filters))

    assert "JOIN documents ON documents.doc_id = chunks.doc_id" in sql
    assert "chunks.doc_id IN" in sql
    assert "documents.issuer IN" in sql
    assert "documents.fiscal_year IN" in sql
    assert "documents.form IN" in sql
    assert "OR chunks.item IS NULL" in sql
    assert "chunks.kind IN" in sql
    assert ["NVDA-FY2024"] in params.values()
    assert [2024] in params.values()


def test_snapshot_statement_uses_frozen_membership_and_bm25_statistics():
    """Score a snapshot only with its retained chunks and lexical statistics."""
    sql, params = normalized_sql(
        bm25.bm25_statement("market risk", 5, RetrievalFilters(snapshot_id=7))
    )

    assert "snapshot_chunks" in sql
    assert "snapshot_chunk_terms" in sql
    assert "snapshot_chunk_lengths" in sql
    assert "snapshot_bm25_corpus_stats" in sql
    assert "snapshot_lexeme_stats" in sql
    assert "FROM chunk_terms" not in sql
    assert 7 in params.values()


@pytest.mark.parametrize(
    "changes",
    [
        {"query": ""},
        {"query": "   "},
        {"k": 0},
        {"k": -1},
        {"k": True},
        {"k1": 0},
        {"k1": -0.5},
        {"k1": math.inf},
        {"k1": math.nan},
        {"b": -0.1},
        {"b": 1.1},
        {"b": math.nan},
        {"idf": "okapi"},
    ],
)
def test_statement_rejects_out_of_range_parameters(changes):
    """Reject invalid query, limit, saturation, normalization, and idf values."""
    values = {"query": "market risk", "k": 5, "k1": 1.2, "b": 0.75, "idf": "lucene"}
    values.update(changes)
    with pytest.raises(ValueError):
        bm25.bm25_statement(
            values["query"],
            values["k"],
            k1=values["k1"],
            b=values["b"],
            idf=values["idf"],
        )


@pytest.mark.parametrize("b", [0.0, 1.0])
def test_statement_accepts_the_closed_length_normalisation_interval(b):
    """Accept both endpoints of the length-normalization interval."""
    assert bm25.bm25_statement("market risk", 1, b=b) is not None


def test_search_executes_once_and_returns_typed_hits():
    """Execute one BM25 statement and return typed hits."""
    mapping = hit_values(score=1.25)

    class Result:
        """Expose deterministic mapping rows like a SQLAlchemy result."""

        def mappings(self):
            """Return the recorded BM25 hit mapping."""
            return SimpleNamespace(all=lambda: [mapping])

    class Session:
        """Record BM25 statements while returning deterministic results."""

        def __init__(self):
            self.statements = []

        async def execute(self, statement):
            """Record and satisfy the hit query."""
            self.statements.append(statement)
            return Result()

        async def scalar(self, statement):
            """Record and satisfy the statistics freshness query."""
            self.statements.append(statement)
            return 1

    session = Session()
    hits = asyncio.run(bm25.bm25_search(cast(AsyncSession, session), "market risk", 4))

    assert len(session.statements) == 2
    assert [hit.chunk_id for hit in hits] == [mapping["chunk_id"]]
    assert hits[0].score == 1.25


def test_search_raises_when_statistics_are_missing_or_stale():
    """Refuse to turn a missing freshness sentinel into an empty result."""

    class Result:
        """Expose an empty SQLAlchemy-style mapping result."""

        def mappings(self):
            """Return no BM25 hit mappings."""
            return SimpleNamespace(all=list)

    class Session:
        """Return stale statistics and no candidate rows."""

        async def execute(self, _statement):
            """Return the empty hit result."""
            return Result()

        async def scalar(self, _statement):
            """Report that the freshness sentinel is absent."""
            return None

    with pytest.raises(RuntimeError, match="missing or stale"):
        asyncio.run(bm25.bm25_search(cast(AsyncSession, Session()), "market risk", 4))


def test_search_shares_the_first_four_parameters_with_lexical_search():
    """``retrieve`` swaps one call for the other, so the call shape must match."""
    from app.retrieval.lexical import lexical_search

    baseline = list(inspect.signature(lexical_search).parameters)
    candidate = list(inspect.signature(bm25.bm25_search).parameters)

    assert candidate[:4] == baseline[:4] == ["session", "query", "k", "filters"]
    assert [p for p in candidate[4:]] == ["k1", "b", "idf", "text_search_config"]
    assert baseline[4:] == ["text_search_config"]


def test_backfill_refuses_a_session_that_is_already_in_a_transaction():
    """Reject statistic rebuilds inside an active transaction."""

    class Session:
        """Represent a session with an existing transaction."""

        def in_transaction(self):
            """Report the active transaction state."""
            return True

    with pytest.raises(RuntimeError, match="without an active transaction"):
        asyncio.run(bm25.backfill_term_stats(cast(AsyncSession, Session())))


# --------------------------------------------------------------------------
# Wiring: settings, service, CLI, public surface.
# --------------------------------------------------------------------------


def test_public_surface_exports_the_bm25_entry_points():
    """Export BM25 search and statistic-rebuild entry points."""
    assert {"bm25_search", "backfill_term_stats", "TermStatCounts"} <= set(public.__all__)


def test_settings_default_to_ts_rank_cd_with_published_bm25_constants():
    """Keep native lexical search as the default with published BM25 constants."""
    settings = Settings()

    assert settings.lexical_ranker == "ts_rank_cd"
    assert settings.bm25_k1 == 1.2
    assert settings.bm25_b == 0.75
    assert settings.bm25_idf == "lucene"


@pytest.mark.parametrize(
    "changes",
    [
        {"bm25_k1": 0},
        {"bm25_k1": -1},
        {"bm25_k1": math.inf},
        {"bm25_k1": math.nan},
        {"bm25_b": -0.1},
        {"bm25_b": 1.1},
        {"bm25_b": math.inf},
        {"bm25_b": math.nan},
    ],
)
def test_settings_reject_out_of_range_bm25_constants(changes):
    """Reject invalid BM25 settings before runtime."""
    with pytest.raises(ValueError):
        Settings(**changes)


@pytest.mark.parametrize(
    ("name", "value"),
    [("BM25_K1", "inf"), ("BM25_K1", "nan"), ("BM25_B", "inf"), ("BM25_B", "nan")],
)
def test_settings_reject_nonfinite_bm25_environment_values(monkeypatch, name, value):
    """Reject nonfinite BM25 values loaded through the environment."""
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        Settings()


def test_cli_exposes_the_ranker_flags():
    """Expose lexical ranker and BM25 overrides through the CLI."""
    args = cli.arguments(
        [
            "--query",
            "market risk",
            "--lexical-ranker",
            "bm25",
            "--bm25-k1",
            "1.5",
            "--bm25-b",
            "0.4",
            "--bm25-idf",
            "robertson",
            "--rebuild-bm25-stats",
        ]
    )

    assert args.lexical_ranker == "bm25"
    assert args.bm25_k1 == 1.5
    assert args.bm25_b == 0.4
    assert args.bm25_idf == "robertson"
    assert args.rebuild_bm25_stats is True


def test_cli_defaults_leave_every_ranker_override_unset():
    """Leave lexical overrides unset by default."""
    args = cli.arguments(["--query", "market risk"])
    assert args.lexical_ranker is None
    assert args.bm25_k1 is None
    assert args.bm25_b is None
    assert args.bm25_idf is None
    assert args.rebuild_bm25_stats is False


# --------------------------------------------------------------------------
# Live PostgreSQL: the SQL must agree with the oracle, not merely run.
# --------------------------------------------------------------------------


async def _load_fixture_corpus(connection, source_root: Path, schema: str) -> None:
    """Load the exact oracle tokens using the complete normalized production schema.

    Empty context headers preserve the oracle term frequencies. The two filing
    sources contain those exact tokens, with real byte hashes, source spans, parsed
    structures, and document-parse pointers. Fixed chunk IDs retain the existing
    fixture-to-oracle mapping independently of document insertion order.
    """
    await connection.execute(sql("CREATE EXTENSION IF NOT EXISTS vector"))
    await connection.run_sync(lambda sync: Base.metadata.create_all(sync, checkfirst=False))
    await ensure_bm25_stats_invalidation(connection, schema=schema)
    await connection.commit()
    documents = []
    records = []
    filings = []
    chunk_ids = {}
    for issuer, positions in (("NVDA", range(3)), ("AMD", range(3, 5))):
        bodies = [" ".join(FIXTURE["documents"][position]["tokens"]) for position in positions]
        raw = "\n".join(bodies)
        path = source_root / f"{issuer}.html"
        path.write_text(raw, encoding="utf-8")
        metadata = filing_document(
            issuer=issuer,
            filing_id=("0001045810-24-000001" if issuer == "NVDA" else "0001045810-24-000002"),
        )
        source = filing_source(path, document=metadata)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        blocks = []
        units = []
        offset = 0
        item = "7" if issuer == "NVDA" else "7A"
        for ordinal, (position, body) in enumerate(zip(positions, bodies, strict=True)):
            end = offset + len(body)
            blocks.append(Block("paragraph", body, source_pos=offset, end_pos=end))
            unit = Chunk(
                metadata.document_id,
                item,
                "text",
                ordinal,
                body,
                "",
                FIXTURE["documents"][position]["id"],
                offset,
                end,
                digest,
            )
            units.append(unit)
            chunk_ids[unit.stable_key] = position + 1
            offset = end + 1
        filing = ParsedFiling(
            source=source,
            source_length=len(raw),
            source_sha256=digest,
            sections=[Section("II", item, "", "", blocks)],
        )
        document, chunk_records = filing_records(filing, units)
        documents.append(document)
        records.extend(chunk_records)
        filings.append(filing)
    batch = SeedBatch(
        tuple(sorted(documents, key=lambda document: document.doc_id)),
        tuple(sorted(records, key=lambda record: (record.doc_id, record.ordinal))),
        tuple(filings),
    )
    provider = DeterministicEmbeddingProvider()
    async with AsyncSession(bind=connection, expire_on_commit=False) as session:
        async with session.begin():
            await session.execute(document_upsert_statement(batch.documents))
            await _persist_sources(session, batch)
            await session.execute(
                insert(ChunkModel),
                [
                    {"id": chunk_ids[record.stable_key], **record.values()}
                    for record in batch.chunks
                ],
            )
            vectors = await provider.embed_documents([record.index_text for record in batch.chunks])
            await session.execute(
                insert(ChunkEmbedding),
                [
                    {
                        "chunk_id": chunk_ids[record.stable_key],
                        "input_sha256": record.values()["index_text_sha256"],
                        "provider": provider.identity.provider,
                        "model": provider.identity.model,
                        "dimensions": provider.identity.dimensions,
                        "tokenizer": provider.identity.tokenizer,
                        "embedding": vector,
                    }
                    for record, vector in zip(batch.chunks, vectors, strict=True)
                ],
            )


def run_live(database_url, body) -> tuple[bool, str]:
    """Run the oracle checks in a disposable complete-schema namespace."""

    async def main() -> tuple[bool, str]:
        """Create, exercise, and clean up only this test's schema and local sources."""
        engine = create_async_engine(database_url, poolclass=NullPool)
        connection = None
        schema = "bm25_fixture_" + uuid4().hex
        created = False
        try:
            try:
                async with asyncio.timeout(5):
                    connection = await engine.connect()
                    await connection.execute(sql("SELECT 1"))
            except Exception as exc:
                return False, str(exc)
            await connection.execute(sql(f"CREATE SCHEMA {schema}"))
            created = True
            await connection.execute(sql(f"SET search_path TO {schema}, public"))
            with TemporaryDirectory(prefix="docreview-bm25-source-") as directory:
                await _load_fixture_corpus(connection, Path(directory), schema)
                async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                    await body(session, connection)
            return True, ""
        finally:
            if connection is not None:
                await connection.rollback()
                if created:
                    await connection.execute(sql("SET search_path TO public"))
                    await connection.execute(sql(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
                    await connection.commit()
                await connection.close()
            await engine.dispose()

    return asyncio.run(main())


def live(database_url, body) -> None:
    """Execute live SQL, failing when PostgreSQL was explicitly required."""
    reachable, detail = run_live(database_url, body)
    if not reachable:
        live_postgres_unavailable(detail)


def test_live_helper_fails_when_postgres_is_expected(monkeypatch):
    """Turn unavailable live SQL into a failure under the explicit local gate."""
    monkeypatch.setenv("DOCREVIEW_EXPECT_LIVE_POSTGRES", "1")
    monkeypatch.setattr(
        "tests.retrieval.test_bm25.run_live",
        lambda _database_url, _body: (False, "connection refused"),
    )

    with pytest.raises(pytest.fail.Exception, match="Expected live PostgreSQL"):
        live("postgresql+asyncpg://unused", object())


@pytest.mark.live_postgres
def test_live_backfill_reproduces_the_fixture_statistics_and_is_idempotent(
    database_url,
):
    """Rebuild exact fixture statistics idempotently in PostgreSQL."""

    async def body(session, _connection):
        """Assert live rebuilt statistics and idempotence."""
        first = await bm25.backfill_term_stats(session)
        second = await bm25.backfill_term_stats(session)

        assert first == second
        assert first.chunks == len(DOCUMENTS)
        assert first.lexemes == len(FIXTURE["corpus_stats"]["df"])

        corpus = (await session.execute(sql("SELECT n, avgdl FROM bm25_corpus_stats"))).one()
        assert corpus.n == FIXTURE["corpus_stats"]["n_documents"]
        assert corpus.avgdl == FIXTURE["corpus_stats"]["avgdl"]

        rows = (await session.execute(sql("SELECT lexeme, df FROM lexeme_stats"))).all()
        assert dict(rows) == FIXTURE["corpus_stats"]["df"]

        lengths = (await session.execute(sql("SELECT chunk_id, dl FROM chunk_lengths"))).all()
        assert dict(lengths) == {
            index + 1: document["dl"] for index, document in enumerate(FIXTURE["documents"])
        }

        terms = (await session.execute(sql("SELECT chunk_id, lexeme, tf FROM chunk_terms"))).all()
        observed: dict[int, dict[str, int]] = {}
        for chunk_id, lexeme, tf in terms:
            observed.setdefault(chunk_id, {})[lexeme] = tf
        for index, document in enumerate(FIXTURE["documents"]):
            expected = {token: document["tokens"].count(token) for token in document["tokens"]}
            assert observed[index + 1] == expected

    live(database_url, body)


@pytest.mark.live_postgres
@pytest.mark.parametrize("idf", ["lucene", "robertson"])
def test_live_sql_scores_agree_with_the_python_oracle(database_url, idf):
    """Match live PostgreSQL scores to the Python oracle."""
    expected = reference_scores(DOCUMENTS, QUERY, idf=idf)

    async def body(session, _connection):
        """Compare live BM25 scores and ranks with the oracle."""
        await bm25.backfill_term_stats(session)
        hits = await bm25.bm25_search(session, " ".join(QUERY), len(DOCUMENTS), idf=idf)

        assert len(hits) == len(DOCUMENTS)
        for hit in hits:
            assert math.isclose(
                hit.score,
                expected[FIXTURE_ID[hit.chunk_id]],
                rel_tol=1e-9,
                abs_tol=1e-12,
            )
        assert [FIXTURE_ID[hit.chunk_id] for hit in hits] == ranking(expected)

    live(database_url, body)


@pytest.mark.live_postgres
def test_live_length_normalisation_reverses_the_top_two_documents(database_url):
    """Verify live length normalization changes the leading documents."""

    async def body(session, _connection):
        """Compare normalized and unnormalized live rankings."""
        await bm25.backfill_term_stats(session)
        normalized = await bm25.bm25_search(session, " ".join(QUERY), 2, b=0.75)
        unnormalized = await bm25.bm25_search(session, " ".join(QUERY), 2, b=0.0)

        assert [FIXTURE_ID[hit.chunk_id] for hit in normalized] == ["d1", "d4"]
        assert [FIXTURE_ID[hit.chunk_id] for hit in unnormalized] == ["d4", "d1"]

    live(database_url, body)


@pytest.mark.live_postgres
def test_live_robertson_returns_finite_negative_scores(database_url):
    """Return finite negative Robertson scores for common terms."""

    async def body(session, _connection):
        """Assert the live Robertson score shape and ordering."""
        await bm25.backfill_term_stats(session)
        hits = await bm25.bm25_search(session, " ".join(QUERY), 5, idf="robertson")

        assert all(hit.score < 0 for hit in hits)
        assert all(math.isfinite(hit.score) for hit in hits)
        assert FIXTURE_ID[hits[0].chunk_id] == "d4"

    live(database_url, body)


@pytest.mark.live_postgres
def test_live_chunk_writes_invalidate_statistics_and_search_fails(database_url):
    """Invalidate the singleton after relevant insert, update, and delete statements."""

    async def body(session, _connection):
        """Exercise each live write path and assert fail-closed search."""
        original = (
            await session.execute(select(ChunkModel).where(ChunkModel.id == 1))
        ).scalar_one()

        def changed_values(context: str, ordinal: int) -> dict:
            """Keep the source body/span while changing indexed contextual text."""
            unit = Chunk(
                original.doc_id,
                original.item,
                original.kind,
                ordinal,
                original.body,
                context,
                original.citation,
                original.start_char,
                original.end_char,
                original.source_sha256,
            )
            return {
                **asdict(unit),
                "stable_key": unit.stable_key,
                "structure_id": original.structure_id,
                "language": original.language,
                "index_text": unit.content,
                "index_text_sha256": hashlib.sha256(unit.content.encode()).hexdigest(),
            }

        writes = (
            update(ChunkModel).where(ChunkModel.id == 1).values(**changed_values("changed", 0)),
            insert(ChunkModel).values(id=99, **changed_values("inserted", 99)),
            sql("DELETE FROM chunks WHERE id = 99"),
        )
        await session.rollback()

        for statement in writes:
            await bm25.backfill_term_stats(session)
            await session.execute(statement)
            await session.commit()

            assert await session.scalar(sql("SELECT count(*) FROM bm25_corpus_stats")) == 0
            with pytest.raises(RuntimeError, match="missing or stale"):
                await bm25.bm25_search(session, " ".join(QUERY), 5)
            await session.rollback()

    live(database_url, body)


@pytest.mark.live_postgres
def test_live_phrase_and_negation_match_like_relaxed_websearch(database_url):
    """Keep phrase adjacency and exclusions while scoring only positive lexemes."""

    async def body(session, _connection):
        """Assert live phrase and exclusion query semantics."""
        await bm25.backfill_term_stats(session)
        phrase = await bm25.bm25_search(session, '"market risk"', 5)
        market = await bm25.bm25_search(session, "market", 5)
        without_volatility = await bm25.bm25_search(session, "market -volatility", 5)

        assert [FIXTURE_ID[hit.chunk_id] for hit in phrase] == ["d1"]
        assert {FIXTURE_ID[hit.chunk_id] for hit in without_volatility} == {"d1", "d4"}
        market_scores = {hit.chunk_id: hit.score for hit in market}
        assert all(
            math.isclose(hit.score, market_scores[hit.chunk_id]) for hit in without_volatility
        )

    live(database_url, body)


@pytest.mark.live_postgres
def test_live_filters_narrow_candidates_without_changing_corpus_statistics(
    database_url,
):
    """``idf`` and ``avgdl`` stay corpus-wide; filters only remove candidates."""
    expected = reference_scores(DOCUMENTS, QUERY)

    async def body(session, _connection):
        """Assert filtering preserves corpus-wide BM25 scores."""
        await bm25.backfill_term_stats(session)
        filtered = await bm25.bm25_search(
            session,
            " ".join(QUERY),
            5,
            RetrievalFilters(issuers=("AMD",)),
        )

        assert {FIXTURE_ID[hit.chunk_id] for hit in filtered} == {"d4", "d5"}
        for hit in filtered:
            assert math.isclose(hit.score, expected[FIXTURE_ID[hit.chunk_id]], rel_tol=1e-9)

    live(database_url, body)


@pytest.mark.live_postgres
def test_live_retrieve_switches_between_the_two_lexical_rankers(database_url):
    """Switch retrieval between native lexical and BM25 rankings."""

    async def body(session, _connection):
        """Compare live retrieval rankings across lexical rankers."""
        await bm25.backfill_term_stats(session)
        provider = DeterministicEmbeddingProvider()
        rankings = {}
        for ranker in ("ts_rank_cd", "bm25"):
            result = await service.retrieve(
                session,
                " ".join(QUERY),
                provider=provider,
                k=3,
                candidate_k=5,
                lexical_ranker=ranker,
            )
            rankings[ranker] = result.component_rankings.lexical

        assert set(rankings["ts_rank_cd"]) and set(rankings["bm25"])
        assert rankings["ts_rank_cd"] != rankings["bm25"]

    live(database_url, body)
