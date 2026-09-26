"""Canonical JSON text is compact, key-sorted, readable in any script and finite."""

import math

import pytest

from app.canonical_json import canonical_json


def test_keys_sort_at_every_depth_with_compact_separators_and_unescaped_text():
    """Nested keys sort, separators carry no spaces and non-ASCII text stays readable."""
    value = {"b": [1.5, None, True], "a": {"é": "한국어", "c": 0}}

    assert canonical_json(value) == '{"a":{"c":0,"é":"한국어"},"b":[1.5,null,true]}'


@pytest.mark.parametrize(
    "number",
    [pytest.param(math.nan, id="not-a-number"), pytest.param(math.inf, id="infinity")],
)
def test_non_finite_numbers_are_refused(number):
    """NaN and infinities have no JSON spelling, so serialization fails loudly."""
    with pytest.raises(ValueError):
        canonical_json({"score": number})
