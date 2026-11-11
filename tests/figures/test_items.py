"""Single-module contract for canonical item keys, phrases and output labels."""

import pytest

from app.figures.items import ITEMS


def test_item_keys_are_explicit_and_match_their_definitions():
    """Keep canonical storage identities and nonempty concept sets stable."""
    assert set(ITEMS) == {
        "revenue",
        "cost of revenue",
        "gross profit",
        "operating income",
        "net income",
        "earnings per share",
        "basic earnings per share",
        "diluted earnings per share",
        "research and development",
        "sales and marketing",
        "selling, general and administrative",
        "income tax",
        "accounts receivable",
        "total assets",
        "total liabilities",
        "total equity",
        "cash and cash equivalents",
    }
    assert all(key == definition.key and definition.concepts for key, definition in ITEMS.items())


def test_item_phrases_are_unique_across_items():
    """One normalized phrase must never designate two financial items."""
    owners: dict[str, str] = {}
    for key, definition in ITEMS.items():
        assert definition.phrases
        for phrase in definition.phrases:
            normalized = " ".join(phrase.casefold().split())
            assert normalized
            assert normalized not in owners or owners[normalized] == key
            owners[normalized] = key


@pytest.mark.parametrize("key", ITEMS)
@pytest.mark.parametrize("locale", ["en", "ko"])
def test_output_labels_are_accepted_phrases_of_the_same_item(key, locale):
    """Every emitted label has exactly its own definition as its phrase owner."""
    label = getattr(ITEMS[key], f"label_{locale}").casefold()
    assert {k for k, d in ITEMS.items() if label in {p.casefold() for p in d.phrases}} == {key}
