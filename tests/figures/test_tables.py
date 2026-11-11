"""Table cells read as values, units, currencies, years, scopes and items."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.figures.tables import (
    TableStatement,
    interpret_table_cell,
    read_table_cells,
    read_table_unit,
)
from tests.figures.support import (
    INCOME_TABLE,
    SEPARATE,
    USD_INCOME_TABLE,
    fact,
    reading,
    stated_revenue,
    table_fragment,
    tagged_revenue,
    term_years,
)


def test_table_readings_expose_each_figure_cell_with_its_resolved_unit():
    """Read the USD income table's figure cells with their coordinates, years and unit."""
    fragment = table_fragment()
    readings = {(cell.row, cell.column): cell for cell in read_table_cells(fragment)}
    revenue = next(
        cell for cell in readings.values() if cell.values == frozenset({Decimal("25785")})
    )
    assert revenue.years == frozenset({2024})
    assert revenue.scale == Decimal(1_000_000)
    assert revenue.item == "revenue"
    assert revenue.currency == "USD"
    assert revenue.percent is False
    assert read_table_unit(fragment).status == "known"


def test_table_readings_keep_an_ambiguous_dollar_unresolved():
    """Leave the "$" family unresolved when the note states a scale but no currency."""
    fragment = table_fragment(INCOME_TABLE)
    currencies = {cell.currency for cell in read_table_cells(fragment) if cell.item == "revenue"}
    assert currencies == {"$"}


@pytest.mark.parametrize(
    ("text", "changes", "status", "value"),
    [
        ("1,234", {}, "known", Decimal(1234)),
        ("(1,234)", {}, "known", Decimal(-1234)),
        ("△1,234.50", {}, "known", Decimal("-1234.50")),
        ("▲1,234", {}, "conflicting", None),
        ("1,234", {"scale": None}, "scale_unknown", Decimal(1234)),
        ("1,234", {"percent": None}, "scale_unknown", Decimal(1234)),
        ("1,234", {"currency": "$"}, "currency_unconfirmed", Decimal(1234)),
        ("1,234", {"currency": None}, "currency_unconfirmed", Decimal(1234)),
        ("1,234", {"currency": "!"}, "conflicting", Decimal(1234)),
        ("1,234", {"years": frozenset()}, "period_unknown", Decimal(1234)),
        ("1,234", {"years": frozenset({2023, 2024})}, "period_unknown", Decimal(1234)),
        ("1,234", {"item": None}, "item_unknown", Decimal(1234)),
        ("1,234", {"measure": "other"}, "not_monetary", Decimal(1234)),
        ("1,234", {"scope": "axis=member"}, "scope_qualified", Decimal(1234)),
        ("1,234", {"scope": "axis=member", "years": frozenset()}, "period_unknown", Decimal(1234)),
        ("12.5%", {"percent": True, "scale": None, "currency": None}, "known", Decimal("12.5")),
    ],
)
def test_a_cell_is_known_only_when_every_fact_is_established(text, changes, status, value):
    """Keep sign and decimals, and name the first missing fact instead of guessing."""
    result = interpret_table_cell(text, [reading(**changes)])
    assert (result.status, result.value) == (status, value)


@pytest.mark.parametrize("text", ["", "  ", "—", "-", "– –"])
def test_a_blank_or_dash_cell_is_blank_not_zero(text):
    """Report an empty or dash-only cell as blank with no value."""
    result = interpret_table_cell(text, [])
    assert (result.status, result.value) == ("blank", None)


def test_a_cell_without_one_figure_is_not_selectable():
    """Keep labels unselectable and refuse a cell that states two figures."""
    assert interpret_table_cell("Net revenue", []).status == "not_numeric"
    assert interpret_table_cell("1,234 / 5,678", [reading()]).status == "conflicting"


@pytest.mark.parametrize(
    ("text", "changes", "status", "reason"),
    [
        ("▲1,234", {"measure": "other"}, "conflicting", "sign marker is ambiguous"),
        (
            "1,234",
            {"measure": "other", "scale": None},
            "not_monetary",
            "tagged unit is not an amount",
        ),
        (
            "1,234",
            {"measure": "other", "percent": None},
            "not_monetary",
            "tagged unit is not an amount",
        ),
        ("1,234", {"percent": None, "currency": None}, "scale_unknown", "percentage unknown"),
        ("1,234", {"scale": None, "currency": "!"}, "scale_unknown", "no readable scale"),
        ("1,234", {"scale": None, "years": frozenset()}, "scale_unknown", "no readable scale"),
        ("1,234", {"currency": "!", "years": frozenset()}, "conflicting", "currencies disagree"),
        (
            "1,234",
            {"currency": None, "years": frozenset()},
            "currency_unconfirmed",
            "no explicit currency",
        ),
        ("1,234", {"currency": "$", "item": None}, "currency_unconfirmed", "no explicit currency"),
        ("1,234", {"years": frozenset(), "item": None}, "period_unknown", "no single fiscal year"),
        ("1,234", {"years": frozenset(), "scope": "?"}, "period_unknown", "no single fiscal year"),
        (
            "1,234",
            {"scope": "?", "item": None},
            "scope_unknown",
            "the filing declares no entity scope for it",
        ),
        ("1,234", {"scope": "axis=member", "item": None}, "scope_qualified", "axis=member"),
        (
            "12.5%",
            {"percent": True, "scale": None, "currency": None, "years": frozenset()},
            "period_unknown",
            "no single fiscal year",
        ),
    ],
)
def test_a_cell_missing_two_facts_reports_the_first_in_a_fixed_order(text, changes, status, reason):
    """Pin which status wins when two facts are missing at once."""
    result = interpret_table_cell(text, [reading(**changes)])
    assert (result.status, result.reason) == (status, reason)


def test_an_inline_xbrl_amount_fixes_currency_scale_and_year():
    """The tag resolves the "$" the text leaves ambiguous, and the cell becomes known."""
    cell = tagged_revenue(fact())
    assert (cell.currency, cell.scale, cell.years, cell.percent) == (
        "USD",
        Decimal(1_000_000),
        frozenset({2024}),
        False,
    )
    assert (cell.basis, cell.measure, cell.scope, cell.overrides) == ("fact", "amount", None, ())
    assert interpret_table_cell("$ 25,785", [cell]).status == "known"


def test_a_tag_that_contradicts_the_text_overrides_it_and_says_so():
    """A tagged year or scale wins over the header and note, and the override is kept."""
    cell = tagged_revenue(fact(fiscal_year=2023, scale=3))
    assert (cell.years, cell.scale, cell.overrides) == (
        frozenset({2023}),
        Decimal(1000),
        ("year", "scale"),
    )


def test_a_per_share_tag_states_plain_currency_units():
    """USD per share at scale 0 is plain dollars even under an "(In millions)" note."""
    cell = tagged_revenue(fact(denominator="xbrli:shares", scale=0))
    assert (cell.measure, cell.scale, cell.currency, cell.overrides) == (
        "per_share",
        Decimal(1),
        "USD",
        ("scale",),
    )


def test_tagged_values_that_are_not_amounts_keep_the_text_unit():
    """Shares and ratios are not amounts; their text unit stays and they are not selectable."""
    text_cell = tagged_revenue()
    cell = tagged_revenue(fact(numerator="xbrli:shares"))
    assert (cell.measure, cell.scale, cell.currency) == ("other", text_cell.scale, "$")
    assert interpret_table_cell("$ 25,785", [cell]).status == "not_monetary"


def test_a_tagged_currency_still_conflicts_with_a_different_written_one():
    """A euro tag on a cell the note declares in U.S. dollars is a conflict, not a choice."""
    cell = tagged_revenue(fact(numerator="iso4217:EUR"), html=USD_INCOME_TABLE)
    assert interpret_table_cell("$ 25,785", [cell]).status == "conflicting"


@pytest.mark.parametrize(
    ("dimensions", "scope"),
    [
        ((), None),
        (
            (
                (
                    "ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis",
                    "ifrs-full:ConsolidatedMember",
                ),
            ),
            None,
        ),
        (
            (
                (
                    "ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis",
                    "ifrs-full:SeparateMember",
                ),
            ),
            "ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis=ifrs-full:SeparateMember",
        ),
        (
            (("us-gaap:StatementBusinessSegmentsAxis", "amd:DataCenterMember"),),
            "us-gaap:StatementBusinessSegmentsAxis=amd:DataCenterMember",
        ),
    ],
)
def test_only_the_whole_entity_is_unscoped(dimensions, scope):
    """No dimension, or DART's consolidated statement, is the entity; anything else is a part."""
    assert tagged_revenue(fact(dimensions=dimensions)).scope == scope


def test_a_dart_tag_fixes_the_year_and_keeps_the_text_unit():
    """DART tags state no unit, so the note's currency and scale stay as read."""
    text_cell = tagged_revenue(html=USD_INCOME_TABLE)
    cell = tagged_revenue(fact(numerator=None, scale=None, fiscal_year=2024), html=USD_INCOME_TABLE)
    assert (cell.basis, cell.measure, cell.years) == ("fact", None, frozenset({2024}))
    assert (cell.scale, cell.currency) == (text_cell.scale, text_cell.currency)


def test_a_fact_applies_only_alone_and_on_the_same_number():
    """Two tags, or a tag showing another number, leave the cell to its text reading."""
    text_cell = tagged_revenue()
    assert tagged_revenue(fact(), fact()) == text_cell
    assert tagged_revenue(fact(text="22,680")) == replace(text_cell, overrides=("number",))


@pytest.mark.parametrize(
    ("header", "years"),
    [
        ("당기", {2024}),
        ("당 기", {2024}),
        ("당기말", {2024}),
        ("제 56 기", {2024}),
        ("제56기말", {2024}),
        ("전기", {2023}),
        ("당기 금액", set()),
        ("제57기", set()),
        ("제56기(2024년)", {2024}),
    ],
)
def test_a_header_that_is_a_defined_period_word_dates_its_column(header, years):
    """Only a header that is the word alone names its year; a written year still wins."""
    assert term_years(header) == years


def test_period_words_mean_nothing_without_the_reports_definitions():
    """Without the document's declarations 당기 and 전기 date nothing."""
    assert term_years("당기", {}) == frozenset()


@pytest.mark.parametrize(
    ("statement", "status"),
    [
        (None, "known"),
        (TableStatement("income", "consolidated"), "known"),
        (TableStatement("summary", "consolidated"), "known"),
        (TableStatement("income", "separate"), "scope_qualified"),
        (TableStatement("notes", "consolidated"), "scope_unknown"),
        (TableStatement("equity", "consolidated"), "scope_unknown"),
        (TableStatement(None, "consolidated"), "scope_unknown"),
        (TableStatement("income", "conflicting"), "scope_unknown"),
        (TableStatement(None, None), "scope_unknown"),
    ],
)
def test_only_a_declared_consolidated_entity_statement_is_the_entity(statement, status):
    """Separate statements are a scope of their own; notes, equity and silence are unknown."""
    cell = stated_revenue(statement)
    assert interpret_table_cell("300,870,903", [cell]).status == status


def test_a_consolidated_tag_in_a_separate_statement_overrides_its_declaration():
    """The tag decides the scope and the contradicted declaration is recorded."""
    dart_fact = fact(numerator=None, scale=None, text="300,870,903")
    cell = stated_revenue(TableStatement("income", "separate"), dart_fact)
    assert (cell.scope, cell.overrides) == (None, ("scope",))
    agreeing = stated_revenue(
        TableStatement("income", "separate"),
        replace(
            dart_fact,
            dimensions=(
                (
                    "ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis",
                    "ifrs-full:SeparateMember",
                ),
            ),
        ),
    )
    assert (agreeing.scope, agreeing.overrides) == (SEPARATE, ())


# NVDA's layout: the percent sign of a margin sits in a source cell of its own.
SPLIT_PERCENT_TABLE = (
    '<table><tr><td>(In millions of U.S. dollars)</td><td colspan="2">2024</td></tr>'
    "<tr><td>Net revenue</td><td>25,785</td><td></td></tr>"
    "<tr><td>Gross margin</td><td>72.7</td><td>%</td></tr></table>"
)


def test_a_percent_sign_in_its_own_cell_is_never_an_amount():
    """The margin's "%" cell makes "72.7 %" a percentage its reading does not carry."""
    readings = {(c.row, c.column): c for c in read_table_cells(table_fragment(SPLIT_PERCENT_TABLE))}
    margin = interpret_table_cell("72.7 %", [readings[(2, 1)]])
    assert (margin.status, margin.reason) == (
        "conflicting",
        "a percent sign outside the figure's own cell",
    )
    assert interpret_table_cell("25,785", [readings[(1, 1)]]).status == "known"


@pytest.mark.parametrize(
    ("text", "changes", "status"),
    [
        ("12.5 %", {}, "conflicting"),
        ("12.5 %", {"percent": None}, "conflicting"),
        ("12.5 %", {"percent": True, "scale": None, "currency": None}, "known"),
        ("12.5%", {"percent": True, "scale": None, "currency": None}, "known"),
    ],
)
def test_a_percentage_is_known_only_when_its_reading_is_one(text, changes, status):
    """A normalized percentage stays known only on a reading that is a percentage."""
    assert interpret_table_cell(text, [reading(**changes)]).status == status


@pytest.mark.parametrize(
    ("changes", "text", "overrides", "value"),
    [
        ({"sign": "-"}, "$ 25,785", ("sign",), Decimal(-25785)),
        ({"sign": "+"}, "$ 25,785", (), Decimal(25785)),
        ({"sign": None}, "$ 25,785", (), Decimal(25785)),
    ],
)
def test_an_inline_xbrl_sign_is_the_values_sign(changes, text, overrides, value):
    """A negating tag on an unsigned figure flips the value and records the override."""
    cell = tagged_revenue(fact(**changes))
    assert cell.overrides == overrides
    assert interpret_table_cell(text, [cell]).value == value


def test_a_tag_without_a_sign_overrides_a_negative_notation():
    """ "(1,641)" tagged with no sign attribute is the positive value the tag states."""
    html = INCOME_TABLE.replace("<td>1,641</td>", "<td>(1,641)</td>")
    readings = read_table_cells(table_fragment(html), {(2, 1): (fact(text="1,641", sign="+"),)})
    cell = next(c for c in readings if (c.row, c.column) == (2, 1))
    assert cell.overrides == ("sign",)
    assert interpret_table_cell("(1,641)", [cell]).value == Decimal(1641)
    agreeing = read_table_cells(table_fragment(html), {(2, 1): (fact(text="1,641", sign="-"),)})
    cell = next(c for c in agreeing if (c.row, c.column) == (2, 1))
    assert (cell.overrides, interpret_table_cell("(1,641)", [cell]).value) == ((), Decimal(-1641))


@pytest.mark.parametrize(
    ("label", "item", "text", "changes", "status", "value"),
    [
        ("Net loss", "net income", "1,641", {}, "conflicting", Decimal(1641)),
        ("Operating loss", "operating income", "1,641", {}, "conflicting", Decimal(1641)),
        ("영업손실", "operating income", "1,234", {}, "conflicting", Decimal(1234)),
        ("당기순손실 (주5)", "net income", "1,234", {}, "conflicting", Decimal(1234)),
        ("Net loss", "net income", "1,641", {"basis": "fact"}, "conflicting", Decimal(1641)),
        ("Net loss", "net income", "(1,641)", {}, "known", Decimal(-1641)),
        ("영업손실", "operating income", "△1,234", {}, "known", Decimal(-1234)),
        ("Net loss", "net income", "0", {}, "known", Decimal(0)),
        ("Net loss", "net income", "1,641", {"measure": "amount"}, "known", Decimal(1641)),
        ("Net income (loss)", "net income", "1,641", {}, "known", Decimal(1641)),
        ("영업이익(손실)", "operating income", "1,234", {}, "known", Decimal(1234)),
        ("Net income", "net income", "1,641", {}, "known", Decimal(1641)),
    ],
)
def test_an_unsigned_figure_under_a_loss_only_label_is_not_one_amount(
    label, item, text, changes, status, value
):
    """A loss phrase alone leaves an unsigned figure's sign unstated unless a tag states it."""
    cell = reading(row_label=label, item=item, **changes)
    assert interpret_table_cell(text, [cell]).status == status
    assert interpret_table_cell(text, [cell]).value == value


def test_a_tag_showing_another_number_makes_the_cell_conflicting():
    """One tag whose number differs from the text is recorded and holds the cell."""
    cell = tagged_revenue(fact(text="22,680"))
    assert (cell.basis, cell.overrides) == ("text", ("number",))
    result = interpret_table_cell("$ 25,785", [cell])
    assert (result.status, result.reason) == (
        "conflicting",
        "the tagged number differs from the text",
    )


def test_a_glued_footnote_with_its_tag_is_not_an_amount():
    """ "25,785<sup>1</sup>" reads 25,7851: the tag of 25,785 disagrees with it."""
    html = USD_INCOME_TABLE.replace("<td>$ 25,785</td>", "<td>$ 25,785<sup>1</sup></td>")
    readings = read_table_cells(table_fragment(html), {(1, 1): (fact(),)})
    cell = next(c for c in readings if (c.row, c.column) == (1, 1))
    assert interpret_table_cell("$ 25,7851", [cell]).status == "conflicting"


@pytest.mark.parametrize(
    ("text", "status"),
    [
        ("25,7851", "conflicting"),
        ("1,23,456", "conflicting"),
        ("(1,2345)", "conflicting"),
        ("4,5,28", "conflicting"),
        ("25,785", "known"),
        ("1,234,567.89", "known"),
        ("(1,641)", "known"),
        ("257851", "known"),
        ("0.5", "known"),
    ],
)
def test_a_figure_with_malformed_grouping_is_not_one_amount(text, status):
    """Only digits grouped in threes, or not grouped at all, stand as one amount."""
    assert interpret_table_cell(text, [reading()]).status == status


@pytest.mark.parametrize(
    ("note", "cell", "status", "scale"),
    [
        ("(In U.S. dollars)", "25.8 billion", "known", Decimal(10) ** 9),
        ("(In U.S. dollars)", "$25.8B", "known", Decimal(10) ** 9),
        ("(단위 : 원)", "300조", "known", Decimal(10) ** 12),
        ("(In millions of U.S. dollars)", "25.8 billion", "conflicting", None),
        ("(단위 : 백만원)", "300조", "conflicting", None),
        ("(In U.S. dollars)", "25,785", "known", Decimal(1)),
        ("(In millions of U.S. dollars)", "25,785", "known", Decimal(10) ** 6),
        ("(In millions)", "25.8 billion", "conflicting", None),
    ],
)
def test_a_scale_word_in_the_cell_is_its_unit_only_under_plain_units(note, cell, status, scale):
    """A cell's own scale word applies under plain units and contradicts a table scale."""
    html = (
        f"<table><tr><td>{note}</td><td>2024</td></tr>"
        f"<tr><td>Net revenue</td><td>{cell}</td></tr></table>"
    )
    (reading_,) = read_table_cells(table_fragment(html))
    assert reading_.scale == scale
    assert interpret_table_cell(cell, [reading_]).status == status


def test_a_tagged_scale_that_the_cells_scale_word_contradicts_is_conflicting():
    """A billion written in a cell tagged at millions is no one amount."""
    result = interpret_table_cell("25.8 billion", [reading(scale=Decimal(10) ** 6)])
    assert (result.status, result.reason) == (
        "conflicting",
        "the cell's scale word disagrees with its unit",
    )
