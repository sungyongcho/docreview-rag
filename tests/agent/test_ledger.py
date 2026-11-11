"""Both immutable ledgers keep repeated identities and retain conflicts until reset."""

import pytest

from app.agent.ledger import citation_records, ledger_failure, merge_identities
from app.contracts.evidence import EvidenceCitation


@pytest.mark.parametrize("key", [1, "1:r1c1"])
@pytest.mark.parametrize("values", [("a", "b"), ("b", "a")])
def test_conflicts_are_order_independent_and_sticky_until_reset(key, values):
    """Neither candidate nor an empty update repairs a conflict; a new question can reset it."""
    first = {key: {"digest": values[0]}}
    other = {key: {"digest": values[1]}}
    assert merge_identities(first, first) == first
    conflict = merge_identities(first, other)
    assert conflict == {key: {"conflict": True}}
    assert merge_identities(conflict, first) == conflict
    assert merge_identities(conflict, {}) == conflict
    assert ledger_failure(conflict) is not None
    assert merge_identities(conflict, None) == {}
    assert merge_identities(None, other) == other


def test_duplicate_identities_in_one_result_use_the_same_merge_contract():
    """Identical repeated hits are retained once, while differing source identities conflict."""
    first = EvidenceCitation(
        chunk_id=1, doc_id="d", citation="c", start_char=0, end_char=1, source_sha256="a" * 64
    )
    other = first.model_copy(update={"source_sha256": "b" * 64})
    assert citation_records((first, first)) == {1: first.model_dump(mode="json")}
    assert citation_records((first, other)) == {1: {"conflict": True}}
    assert citation_records((other, first)) == {1: {"conflict": True}}
