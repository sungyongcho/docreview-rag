"""Pin ``tests.prepared.prepared`` so unprepared live checks always skip."""

import pytest

from tests.prepared import prepared

_FIRST = "DOCREVIEW_PREPARED_TEST_FIRST"
_SECOND = "DOCREVIEW_PREPARED_TEST_SECOND"
_THIRD = "DOCREVIEW_PREPARED_TEST_THIRD"


def test_returns_values_as_a_tuple_in_name_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Return every named variable's value as a tuple in the order requested."""
    monkeypatch.setenv(_FIRST, "alpha")
    monkeypatch.setenv(_SECOND, "beta")

    values = prepared(_SECOND, _FIRST)

    assert type(values) is tuple
    assert values == ("beta", "alpha")


def test_unset_variable_skips_naming_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip with a message naming the variable when it is absent from the environment."""
    monkeypatch.delenv(_FIRST, raising=False)

    with pytest.raises(pytest.skip.Exception) as skipped:
        prepared(_FIRST)

    assert _FIRST in str(skipped.value)


def test_empty_variable_counts_as_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip with a message naming the variable when it is set to the empty string."""
    monkeypatch.setenv(_FIRST, "")

    with pytest.raises(pytest.skip.Exception) as skipped:
        prepared(_FIRST)

    assert _FIRST in str(skipped.value)


def test_partial_variables_skip_naming_only_the_missing_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Name every unset or empty variable in the skip message, and none of the set ones."""
    monkeypatch.setenv(_FIRST, "ready")
    monkeypatch.delenv(_SECOND, raising=False)
    monkeypatch.setenv(_THIRD, "")

    with pytest.raises(pytest.skip.Exception) as skipped:
        prepared(_FIRST, _SECOND, _THIRD)

    message = str(skipped.value)
    assert _SECOND in message
    assert _THIRD in message
    assert _FIRST not in message
