"""Financial identities survive question, row, answer and application assembly."""

from decimal import Decimal

import pytest

from app.agent.cell_answers import StoredCell, _line
from app.figures.answers import _claims
from app.figures.items import ITEMS
from app.figures.tables import _label_item
from app.figures.vocabulary import items_named


@pytest.mark.parametrize("item,phrase", [(k, p) for k, d in ITEMS.items() for p in d.phrases])
def test_every_phrase_names_the_same_item_on_three_sides(item, phrase):
    """Read every accepted item phrase in questions, rows and stated answers."""
    question = (
        f"What was {phrase} in 2024?" if phrase.isascii() else f"2024년 {phrase}은 얼마인가요?"
    )
    assert items_named(question) == {item}
    assert _label_item(phrase) == item
    assert _claims(f"FY2024 {phrase}: 1,234 million USD.", answer=True)[0].item == item


@pytest.mark.parametrize("item", ITEMS)
@pytest.mark.parametrize("locale", ["en", "ko"])
def test_assembled_labels_are_read_back_as_the_same_item(item, locale):
    """Round-trip both application output languages without borrowing a row label."""
    cell = StoredCell(
        "1:r1c1",
        1,
        {
            "item": item,
            "fiscal_years": [2024],
            "row_label": "foreign",
            "percent": False,
            "scale": "1000000",
            "currency": "USD",
        },
        "s",
        "r",
        Decimal(1234),
    )
    answer = _line(cell, locale)
    assert _claims(answer, answer=True)[0].item == item
    assert _label_item(ITEMS[item].label_en) == item
    assert _label_item(ITEMS[item].label_ko) == item


@pytest.mark.parametrize(
    "phrase", ["adjusted net income", "Data Center revenue", "조정매출액", "R&D expense ratio"]
)
def test_shared_phrases_do_not_erase_qualifiers(phrase):
    """An item synonym never makes a qualified claim whole-entity evidence."""
    assert not items_named(f"What was {phrase} in 2024?")
    assert _label_item(phrase) is None
    assert _claims(f"FY2024 {phrase}: USD 1,234 million.", answer=True)[0].item is None
