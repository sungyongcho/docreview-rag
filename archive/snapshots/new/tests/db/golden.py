"""Golden M1.4 corpus identities and chunk totals."""

from tests.chunk.golden import CHUNK_COUNTS

EXPECTED_DOCUMENT_IDS = tuple(sorted(CHUNK_COUNTS))
EXPECTED_DOCUMENTS = len(EXPECTED_DOCUMENT_IDS)
EXPECTED_CHUNKS = sum(total for total, _text, _table in CHUNK_COUNTS.values())
EXPECTED_TEXT_CHUNKS = sum(text for _total, text, _table in CHUNK_COUNTS.values())
EXPECTED_TABLE_CHUNKS = sum(table for _total, _text, table in CHUNK_COUNTS.values())
