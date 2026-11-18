"""Query helpers shared by readers and writers."""

from app.db.queries import slices


def test_slices_bound_each_statement_and_keep_every_id_in_order():
    """Split 2,500 ids into three bounded slices that rejoin to the original list."""
    ids = list(range(2_500))
    parts = list(slices(ids))
    assert [len(part) for part in parts] == [1_000, 1_000, 500]
    assert [value for part in parts for value in part] == ids
    assert list(slices([])) == []
