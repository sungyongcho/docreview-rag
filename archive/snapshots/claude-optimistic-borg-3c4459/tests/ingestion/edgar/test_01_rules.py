"""Heading rule constraints learned from one filing's own markup."""

from types import ModuleType

BOLD_10PT = 'style="font-weight:700;font-size:10.0pt;text-align:center"'


def _tag(edgar_module: ModuleType, html: str):
    return edgar_module.BeautifulSoup(html, "html.parser").find(True)


def test_unlisted_and_unknown_rule_keys_add_no_constraint(edgar_module: ModuleType) -> None:
    """Treat omitted and unknown properties as unconstrained.

    Partial learned rules stay usable, at the cost of a misspelled key not failing closed.
    """
    bold = _tag(edgar_module, f"<div {BOLD_10PT}>Item 1. Business</div>")

    assert edgar_module.matches_rule(bold, {"font_weight": 700}) is True
    assert edgar_module.matches_rule(bold, {"font_wieght": 700}) is True


def test_numeric_rules_are_inclusive_minimums(edgar_module: ModuleType) -> None:
    """Interpret numeric rule values as inclusive minimum thresholds.

    This matches profile learning, which stores the minimum observed heading style.
    """
    bold = _tag(edgar_module, f"<div {BOLD_10PT}>Item 1. Business</div>")

    assert edgar_module.matches_rule(bold, {"font_size": 9.0}) is True
    assert edgar_module.matches_rule(bold, {"font_size": 10.0}) is True
    assert edgar_module.matches_rule(bold, {"font_size": 11.0}) is False


def test_string_rules_require_equality(edgar_module: ModuleType) -> None:
    """Require exact equality for non-numeric string properties."""
    bold = _tag(edgar_module, f"<div {BOLD_10PT}>Item 1. Business</div>")

    assert edgar_module.matches_rule(bold, {"text_align": "center"}) is True
    assert edgar_module.matches_rule(bold, {"text_align": "left"}) is False


def test_in_table_rule_is_intentionally_asymmetric(edgar_module: ModuleType) -> None:
    """Use false for outside-only and true for no table-position constraint.

    Inside-only would reject ordinary headings once one filing put its headings in a table.
    """
    outside = _tag(edgar_module, f"<div {BOLD_10PT}>Item 1</div>")
    inside = edgar_module.BeautifulSoup(
        f"<table><tr><td><div {BOLD_10PT}>Item 1</div></td></tr></table>",
        "html.parser",
    ).find("div")

    assert edgar_module.matches_rule(outside, {"in_table": False}) is True
    assert edgar_module.matches_rule(inside, {"in_table": False}) is False
    assert edgar_module.matches_rule(outside, {"in_table": True}) is True
    assert edgar_module.matches_rule(inside, {"in_table": True}) is True


def test_boolean_rules_are_checked_before_numeric_rules(edgar_module: ModuleType) -> None:
    """Prevent Python booleans from being interpreted as integer thresholds.

    ``bool`` subclasses ``int``, so a numeric check first would read true as a minimum of one.
    """
    element = _tag(edgar_module, f"<div {BOLD_10PT}>Item 1</div>")

    assert edgar_module.block_props(element)["in_table"] is False
    assert edgar_module.matches_rule(element, {"font_weight": True}) is False


def test_block_props_normalizes_weight_and_reads_nested_spans(
    edgar_module: ModuleType,
) -> None:
    """Normalize bold to 700 and collect styles from up to two nested spans."""
    keyword = _tag(edgar_module, '<div style="font-weight:bold">x</div>')
    numeric = _tag(edgar_module, '<div style="font-weight:700">x</div>')
    nested = _tag(
        edgar_module,
        '<div><span style="font-weight:700;font-size:14.0pt">Risk Factors</span></div>',
    )

    assert edgar_module.block_props(keyword)["font_weight"] == 700
    assert edgar_module.block_props(numeric)["font_weight"] == 700
    assert edgar_module.block_props(nested)["font_weight"] == 700
    assert edgar_module.block_props(nested)["font_size"] == 14.0
    assert edgar_module.block_props(_tag(edgar_module, "<div>x</div>"))["font_weight"] == 400


def test_block_props_requires_the_whole_block_to_be_semantically_bold(
    edgar_module: ModuleType,
) -> None:
    """Do not promote a paragraph whose Item reference alone is bold."""
    partial = _tag(
        edgar_module,
        "<p><strong>Item 1A.</strong> appears in this ordinary sentence.</p>",
    )

    assert edgar_module.block_props(partial)["font_weight"] == 400


def test_matches_any_uses_or_semantics(edgar_module: ModuleType) -> None:
    """Accept an element when any learned heading rule matches."""
    bold = _tag(edgar_module, f"<div {BOLD_10PT}>Item 1. Business</div>")
    plain = _tag(edgar_module, '<div style="font-weight:400;font-size:9.0pt">Body</div>')
    rules = [{"font_size": 99.0}, {"font_weight": 700}]

    assert edgar_module.matches_any(bold, rules) is True
    assert edgar_module.matches_any(plain, rules) is False
    assert edgar_module.matches_any(bold, []) is False


def test_item_regex_is_anchored_and_prefers_two_digit_items(edgar_module: ModuleType) -> None:
    """Reject inline references and capture complete two-digit Item numbers."""

    def item_of(text: str) -> str | None:
        match = edgar_module.ITEM_RE.match(text)
        return (match.group("num") + (match.group("suffix") or "")).upper() if match else None

    assert item_of("Item 1. Business") == "1"
    assert item_of("Item 1A. Risk Factors") == "1A"
    assert item_of("Item 15. Exhibits") == "15"
    assert item_of("Item 16") == "16"
    assert item_of("ITEM 7A.") == "7A"
    assert item_of("as described in Item 1A above") is None
