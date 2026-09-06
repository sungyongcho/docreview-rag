"""L9: BM25 ranking derived from the stored PostgreSQL tsvector."""

import asyncio
import inspect
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text as sql
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.retrieval.embeddings import DeterministicEmbeddingProvider
from app.retrieval.types import RetrievalFilters
from tests.retrieval.conftest import make_settings
from tests.retrieval.test_01_contract import hit_values
from tests.support import need, optional_module

B = optional_module(os.getenv("RETRIEVAL_BM25_MODULE", "app.retrieval.bm25"))
S = optional_module(os.getenv("RETRIEVAL_SERVICE_MODULE", "app.retrieval.service"))
M = optional_module("app.retrieval.__main__")
PUBLIC = optional_module("app.retrieval")

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


def normalized_sql(statement) -> tuple[str, dict[str, object]]:
    """Compile a statement with PostgreSQL placeholders and normalized whitespace."""
    compiled = statement.compile(dialect=postgresql.dialect())
    return " ".join(str(compiled).split()), compiled.params


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
    scores = reference_scores(DOCUMENTS, QUERY, b=b, idf=idf)
    assert rounded(scores) == FIXTURE[expected_key]


def test_corpus_statistics_match_the_fixture():
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
    """``b`` is the whole disagreement between the two top documents.

    ``d1`` is short and dense: three lexemes, two of them ``risk``. ``d4`` is long
    and mentions ``market`` twice. With length normalisation on, ``d1``'s brevity
    wins. Turn it off with ``b=0`` and ``d4``'s extra ``market`` wins instead.
    """
    normalized = reference_scores(DOCUMENTS, QUERY, b=0.75)
    unnormalized = reference_scores(DOCUMENTS, QUERY, b=0.0)

    assert ranking(normalized)[:2] == ["d1", "d4"]
    assert ranking(unnormalized)[:2] == ["d4", "d1"]


def test_robertson_idf_goes_negative_and_inverts_the_ranking():
    """Robertson's idf punishes a chunk for containing a corpus-wide term.

    ``risk`` is in all five documents, so ``ln((N - df + 0.5) / (df + 0.5))`` is
    about -2.4. Every extra match then subtracts, and ``d5`` -- which matches
    ``risk`` once and nothing else -- outranks ``d1``, which matches ``risk`` twice
    and ``market`` as well. That is why Lucene's ``ln(1 + ...)`` is the default.
    """
    lucene = reference_scores(DOCUMENTS, QUERY, idf="lucene")
    robertson = reference_scores(DOCUMENTS, QUERY, idf="robertson")

    assert FIXTURE["idf"]["robertson"]["risk"] < 0
    assert all(score > 0 for score in lucene.values())
    assert all(score < 0 for score in robertson.values())
    assert ranking(lucene).index("d1") < ranking(lucene).index("d5")
    assert ranking(robertson).index("d5") < ranking(robertson).index("d1")


def test_lucene_idf_stays_nonnegative_for_every_document_frequency():
    n_documents = len(DOCUMENTS)
    for df in range(1, n_documents + 1):
        ratio = (n_documents - df + 0.5) / (df + 0.5)
        assert math.log(1 + ratio) >= 0


def test_repeated_query_terms_are_scored_once():
    once = reference_scores(DOCUMENTS, ["risk", "market"])
    twice = reference_scores(DOCUMENTS, ["risk", "risk", "market", "risk"])

    assert once == twice


# --------------------------------------------------------------------------
# The statement: bound, derived from the stored tsvector, deterministic.
# --------------------------------------------------------------------------


def test_statement_scores_from_the_derived_statistics_tables():
    need(B, "bm25_statement")
    sql, _params = normalized_sql(B.bm25_statement("market risk", 5))

    assert "FROM chunk_terms" in sql
    assert "JOIN lexeme_stats ON lexeme_stats.lexeme = chunk_terms.lexeme" in sql
    assert "JOIN chunk_lengths ON chunk_lengths.chunk_id = chunk_terms.chunk_id" in sql
    assert "count(chunk_lengths.chunk_id)" in sql
    assert "avg(chunk_lengths.dl)" in sql
    assert "GROUP BY chunk_terms.chunk_id" in sql


def test_statement_binds_the_query_and_never_interpolates_it():
    need(B, "bm25_statement")
    query = "capital expense'; DROP TABLE chunks --"
    statement = B.bm25_statement(query, 7, k1=1.5, b=0.4)
    sql, params = normalized_sql(statement)

    assert "to_tsvector(" in sql
    assert "tsvector_to_array(" in sql
    assert query not in sql
    assert query in params.values()
    assert 1.5 in params.values()
    assert 0.4 in params.values()
    assert 7 in params.values()


def test_statement_projects_the_complete_hit_surface_and_orders_deterministically():
    need(B, "bm25_statement")
    statement = B.bm25_statement("market risk", 5)
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
        "chunks.doc_id ASC, chunks.source_sha256 ASC, chunks.start_char ASC, "
        "chunks.end_char ASC, chunks.id ASC"
    ) in sql


@pytest.mark.parametrize(
    ("idf", "present", "absent"),
    [("lucene", "ln(%(param_1)s +", "ln(((CAST"), ("robertson", "ln(((CAST", "ln(%(param_1)s +")],
)
def test_statement_emits_the_selected_idf_variant(idf, present, absent):
    need(B, "bm25_statement")
    sql, _params = normalized_sql(B.bm25_statement("market risk", 5, idf=idf))

    assert present in sql
    assert absent not in sql


def test_statement_clamps_document_frequency_to_the_corpus_size():
    """Stale ``lexeme_stats`` must not make Robertson take ``ln`` of a negative."""
    need(B, "bm25_statement")
    sql, _params = normalized_sql(B.bm25_statement("market risk", 5, idf="robertson"))

    assert "least(CAST(lexeme_stats.df AS FLOAT)" in sql


def test_statement_applies_every_shared_filter():
    need(B, "bm25_statement")
    filters = RetrievalFilters(
        doc_ids=("NVDA-FY2024",),
        tickers=("NVDA",),
        fiscal_years=(2024,),
        forms=("10-K",),
        items=(None, "7"),
        kinds=("table",),
    )
    sql, params = normalized_sql(B.bm25_statement("market risk", 5, filters))

    assert "JOIN documents ON documents.doc_id = chunks.doc_id" in sql
    assert "chunks.doc_id IN" in sql
    assert "documents.ticker IN" in sql
    assert "documents.fiscal_year IN" in sql
    assert "documents.form IN" in sql
    assert "OR chunks.item IS NULL" in sql
    assert "chunks.kind IN" in sql
    assert ["NVDA-FY2024"] in params.values()
    assert [2024] in params.values()


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
    need(B, "bm25_statement")
    values = {"query": "market risk", "k": 5, "k1": 1.2, "b": 0.75, "idf": "lucene"}
    values.update(changes)
    with pytest.raises(ValueError):
        B.bm25_statement(
            values["query"],
            values["k"],
            k1=values["k1"],
            b=values["b"],
            idf=values["idf"],
        )


@pytest.mark.parametrize("b", [0.0, 1.0])
def test_statement_accepts_the_closed_length_normalisation_interval(b):
    need(B, "bm25_statement")
    assert B.bm25_statement("market risk", 1, b=b) is not None


def test_search_executes_once_and_returns_typed_hits():
    need(B, "bm25_search")
    mapping = hit_values(score=1.25)

    class Result:
        def mappings(self):
            return SimpleNamespace(all=lambda: [mapping])

    class Session:
        def __init__(self):
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)
            return Result()

    session = Session()
    hits = asyncio.run(B.bm25_search(session, "market risk", 4))

    assert len(session.statements) == 1
    assert [hit.chunk_id for hit in hits] == [mapping["chunk_id"]]
    assert hits[0].score == 1.25


def test_search_shares_the_first_four_parameters_with_lexical_search():
    """``retrieve`` swaps one call for the other, so the call shape must match."""
    need(B, "bm25_search")
    from app.retrieval.lexical import lexical_search

    baseline = list(inspect.signature(lexical_search).parameters)
    candidate = list(inspect.signature(B.bm25_search).parameters)

    assert candidate[:4] == baseline[:4] == ["session", "query", "k", "filters"]
    assert [p for p in candidate[4:]] == ["k1", "b", "idf"]


def test_backfill_refuses_a_session_that_is_already_in_a_transaction():
    need(B, "backfill_term_stats")

    class Session:
        def in_transaction(self):
            return True

    with pytest.raises(RuntimeError, match="without an active transaction"):
        asyncio.run(B.backfill_term_stats(Session()))


# --------------------------------------------------------------------------
# Wiring: settings, service, CLI, public surface.
# --------------------------------------------------------------------------


def test_public_surface_exports_the_bm25_entry_points():
    need(PUBLIC, "bm25_search", "backfill_term_stats", "TermStatCounts")
    assert {"bm25_search", "backfill_term_stats", "TermStatCounts"} <= set(PUBLIC.__all__)


def need_ranker_settings() -> None:
    """Skip until ``Settings`` carries the lexical-ranker fields."""
    if not hasattr(make_settings(), "lexical_ranker"):
        pytest.skip("not implemented yet: Settings.lexical_ranker")


def test_settings_default_to_ts_rank_cd_with_published_bm25_constants():
    need_ranker_settings()
    settings = make_settings()

    assert settings.lexical_ranker == "ts_rank_cd"
    assert settings.bm25_k1 == 1.2
    assert settings.bm25_b == 0.75
    assert settings.bm25_idf == "lucene"


@pytest.mark.parametrize(
    "changes",
    [{"bm25_k1": 0}, {"bm25_k1": -1}, {"bm25_b": -0.1}, {"bm25_b": 1.1}],
)
def test_settings_reject_out_of_range_bm25_constants(changes):
    need_ranker_settings()
    with pytest.raises(ValueError):
        make_settings(**changes)


def test_cli_exposes_the_ranker_flags():
    need(M, "arguments")
    try:
        args = M.arguments(
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
    except SystemExit:
        pytest.skip("not implemented yet: ranker CLI flags")

    assert args.lexical_ranker == "bm25"
    assert args.bm25_k1 == 1.5
    assert args.bm25_b == 0.4
    assert args.bm25_idf == "robertson"
    assert args.rebuild_bm25_stats is True


def test_cli_defaults_leave_every_ranker_override_unset():
    need(M, "arguments")
    args = M.arguments(["--query", "market risk"])
    if not hasattr(args, "lexical_ranker"):
        pytest.skip("not implemented yet: ranker CLI flags")

    assert args.lexical_ranker is None
    assert args.bm25_k1 is None
    assert args.bm25_b is None
    assert args.bm25_idf is None
    assert args.rebuild_bm25_stats is False


# --------------------------------------------------------------------------
# Live PostgreSQL: the SQL must agree with the oracle, not merely run.
# --------------------------------------------------------------------------

CREATE_CORPUS = (
    """
    CREATE TEMP TABLE documents (
        doc_id text PRIMARY KEY,
        ticker text NOT NULL,
        cik bigint NOT NULL,
        fiscal_year integer NOT NULL,
        form text NOT NULL
    )
    """,
    """
    CREATE TEMP TABLE chunks (
        id bigint PRIMARY KEY,
        doc_id text NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
        item text,
        kind text NOT NULL,
        ordinal integer NOT NULL,
        body text NOT NULL,
        context_header text NOT NULL,
        index_text text NOT NULL,
        start_char bigint NOT NULL,
        end_char bigint NOT NULL,
        source_sha256 text NOT NULL,
        citation text NOT NULL,
        embedding vector(384),
        content_tsv tsvector GENERATED ALWAYS AS (
            to_tsvector('english', index_text)
        ) STORED,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TEMP TABLE chunk_terms (
        chunk_id bigint NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
        lexeme text NOT NULL,
        tf integer NOT NULL,
        PRIMARY KEY (chunk_id, lexeme)
    )
    """,
    """
    CREATE TEMP TABLE chunk_lengths (
        chunk_id bigint PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
        dl integer NOT NULL
    )
    """,
    """
    CREATE TEMP TABLE lexeme_stats (
        lexeme text PRIMARY KEY,
        df integer NOT NULL
    )
    """,
)


def vector_literal(vector) -> str:
    """Serialize a finite embedding for an explicit PostgreSQL cast."""
    return "[" + ",".join(str(component) for component in vector) + "]"


async def _load_fixture_corpus(connection) -> None:
    """Materialize the committed fixture as real rows in temporary tables.

    ``index_text`` is the token list itself, with an empty context header so the
    ``ChunkHit`` identity ``index_text == body`` holds. Every fixture token is already an
    English snowball stem, so PostgreSQL's generated ``content_tsv`` reproduces the
    fixture's term frequencies and document lengths exactly, and the oracle and the
    database are then describing the same corpus rather than two similar ones.
    """
    await connection.execute(sql("CREATE EXTENSION IF NOT EXISTS vector"))
    for statement in CREATE_CORPUS:
        await connection.execute(sql(statement))
    await connection.execute(
        sql(
            "INSERT INTO documents (doc_id, ticker, cik, fiscal_year, form) VALUES "
            "('NVDA-FY2024', 'NVDA', 1045810, 2024, '10-K'), "
            "('AMD-FY2024', 'AMD', 2488, 2024, '10-K')"
        )
    )
    insert = sql(
        """
        INSERT INTO chunks (
            id, doc_id, item, kind, ordinal, body, context_header, index_text,
            start_char, end_char, source_sha256, citation, embedding
        ) VALUES (
            :id, :doc_id, :item, 'text', :ordinal, :body, :header, :index_text,
            :start_char, :end_char, :source_sha256, :citation,
            CAST(:embedding AS vector)
        )
        """
    )
    provider = DeterministicEmbeddingProvider()
    vectors = await provider.embed_documents(
        [" ".join(document["tokens"]) for document in FIXTURE["documents"]]
    )
    for ordinal, document in enumerate(FIXTURE["documents"]):
        chunk_id = ordinal + 1
        start_char = chunk_id * 100
        index_text = " ".join(document["tokens"])
        await connection.execute(
            insert,
            {
                "id": chunk_id,
                "doc_id": "NVDA-FY2024" if chunk_id <= 3 else "AMD-FY2024",
                "item": "7" if chunk_id <= 3 else "7A",
                "ordinal": ordinal,
                "body": index_text,
                "header": "",
                "index_text": index_text,
                "start_char": start_char,
                "end_char": start_char + len(document["text"]),
                "source_sha256": f"{chunk_id:064d}",
                "citation": document["id"],
                "embedding": vector_literal(vectors[ordinal]),
            },
        )
    await connection.commit()


def run_live(database_url, body) -> tuple[bool, str]:
    """Run ``body(session, connection)`` against a throwaway fixture corpus."""

    async def main() -> tuple[bool, str]:
        engine = create_async_engine(database_url, poolclass=NullPool)
        connection = None
        try:
            try:
                async with asyncio.timeout(5):
                    connection = await engine.connect()
                    await connection.execute(sql("SELECT 1"))
            except Exception as exc:
                return False, str(exc)

            await _load_fixture_corpus(connection)
            session = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                await body(session, connection)
            finally:
                await session.close()
            return True, ""
        finally:
            if connection is not None:
                await connection.close()
            await engine.dispose()

    return asyncio.run(main())


def live(database_url, body) -> None:
    """Execute a live-database body, skipping when PostgreSQL is unavailable."""
    reachable, detail = run_live(database_url, body)
    if not reachable:
        pytest.skip(f"PostgreSQL is unavailable: {detail}")


def test_live_backfill_reproduces_the_fixture_statistics_and_is_idempotent(
    postgres_test_database_url,
):
    need(B, "backfill_term_stats")

    async def body(session, _connection):
        first = await B.backfill_term_stats(session)
        second = await B.backfill_term_stats(session)

        assert first == second
        assert first.chunks == len(DOCUMENTS)
        assert first.lexemes == len(FIXTURE["corpus_stats"]["df"])

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

    live(postgres_test_database_url, body)


@pytest.mark.parametrize("idf", ["lucene", "robertson"])
def test_live_sql_scores_agree_with_the_python_oracle(postgres_test_database_url, idf):
    need(B, "backfill_term_stats", "bm25_search")
    expected = reference_scores(DOCUMENTS, QUERY, idf=idf)

    async def body(session, _connection):
        await B.backfill_term_stats(session)
        hits = await B.bm25_search(session, " ".join(QUERY), len(DOCUMENTS), idf=idf)

        assert len(hits) == len(DOCUMENTS)
        for hit in hits:
            assert math.isclose(
                hit.score,
                expected[FIXTURE_ID[hit.chunk_id]],
                rel_tol=1e-9,
                abs_tol=1e-12,
            )
        assert [FIXTURE_ID[hit.chunk_id] for hit in hits] == ranking(expected)

    live(postgres_test_database_url, body)


def test_live_length_normalisation_reverses_the_top_two_documents(postgres_test_database_url):
    need(B, "backfill_term_stats", "bm25_search")

    async def body(session, _connection):
        await B.backfill_term_stats(session)
        normalized = await B.bm25_search(session, " ".join(QUERY), 2, b=0.75)
        unnormalized = await B.bm25_search(session, " ".join(QUERY), 2, b=0.0)

        assert [FIXTURE_ID[hit.chunk_id] for hit in normalized] == ["d1", "d4"]
        assert [FIXTURE_ID[hit.chunk_id] for hit in unnormalized] == ["d4", "d1"]

    live(postgres_test_database_url, body)


def test_live_robertson_returns_finite_negative_scores(postgres_test_database_url):
    need(B, "backfill_term_stats", "bm25_search")

    async def body(session, _connection):
        await B.backfill_term_stats(session)
        hits = await B.bm25_search(session, " ".join(QUERY), 5, idf="robertson")

        assert all(hit.score < 0 for hit in hits)
        assert all(math.isfinite(hit.score) for hit in hits)
        assert FIXTURE_ID[hits[0].chunk_id] == "d4"

    live(postgres_test_database_url, body)


def test_live_stale_statistics_cannot_make_the_logarithm_fail(postgres_test_database_url):
    """Deleting chunks cascades ``chunk_terms`` away but leaves ``lexeme_stats``."""
    need(B, "backfill_term_stats", "bm25_search")

    async def body(session, connection):

        await B.backfill_term_stats(session)
        await session.execute(sql("DELETE FROM chunks WHERE id > 2"))
        await session.commit()

        remaining = await session.scalar(sql("SELECT count(*) FROM chunk_lengths"))
        stale = await session.scalar(sql("SELECT df FROM lexeme_stats WHERE lexeme = 'risk'"))
        assert remaining == 2
        assert stale == 5

        for idf in ("lucene", "robertson"):
            hits = await B.bm25_search(session, " ".join(QUERY), 5, idf=idf)
            assert len(hits) == 2
            assert all(math.isfinite(hit.score) for hit in hits)

    live(postgres_test_database_url, body)


def test_live_filters_narrow_candidates_without_changing_corpus_statistics(
    postgres_test_database_url,
):
    """``idf`` and ``avgdl`` stay corpus-wide; filters only remove candidates."""
    need(B, "backfill_term_stats", "bm25_search")
    expected = reference_scores(DOCUMENTS, QUERY)

    async def body(session, _connection):
        await B.backfill_term_stats(session)
        filtered = await B.bm25_search(
            session,
            " ".join(QUERY),
            5,
            RetrievalFilters(tickers=("AMD",)),
        )

        assert {FIXTURE_ID[hit.chunk_id] for hit in filtered} == {"d4", "d5"}
        for hit in filtered:
            assert math.isclose(hit.score, expected[FIXTURE_ID[hit.chunk_id]], rel_tol=1e-9)

    live(postgres_test_database_url, body)


def test_live_retrieve_switches_between_the_two_lexical_rankers(postgres_test_database_url):
    need(S, "retrieve")
    need(B, "backfill_term_stats")

    async def body(session, _connection):
        await B.backfill_term_stats(session)
        provider = DeterministicEmbeddingProvider()
        rankings = {}
        for ranker in ("ts_rank_cd", "bm25"):
            result = await S.retrieve(
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

    live(postgres_test_database_url, body)
