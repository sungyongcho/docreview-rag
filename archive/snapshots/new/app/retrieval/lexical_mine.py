"""Your turn: implement PostgreSQL full-text lexical retrieval.

The reference implementation is the mandatory lexical baseline and uses
``websearch_to_tsquery`` plus ``ts_rank_cd`` cover-density ranking. PostgreSQL
full-text search is not literal BM25.

Run the reference tests:
    uv run pytest tests/retrieval/test_04_lexical.py

Grade this learner module instead:
    RETRIEVAL_LEXICAL_MODULE=app.retrieval.lexical_mine \
        uv run pytest tests/retrieval/test_04_lexical.py -v

Missing symbols skip their dependent tests, so pytest remains a progress board.
"""
