from types import ModuleType

BOLD_10PT = 'style="font-weight:700;font-size:10.0pt;text-align:center"'


def _tag(parser_module: ModuleType, html: str):
    return parser_module.BeautifulSoup(html, "html.parser").find(True)


def test_unlisted_and_unknown_rule_keys_add_no_constraint(parser_module: ModuleType) -> None:
    """Treat omitted and unknown properties as unconstrained.

    This keeps partial learned rules usable, although it also means misspelled keys do
    not fail closed.
    """
    bold = _tag(parser_module, f"<div {BOLD_10PT}>Item 1. Business</div>")

    assert parser_module.matches_rule(bold, {"font_weight": 700}) is True
    assert parser_module.matches_rule(bold, {"font_wieght": 700}) is True


def test_numeric_rules_are_inclusive_minimums(parser_module: ModuleType) -> None:
    """Interpret numeric rule values as inclusive minimum thresholds.

    This matches profile learning, which stores the minimum observed heading style.
    """
    bold = _tag(parser_module, f"<div {BOLD_10PT}>Item 1. Business</div>")

    assert parser_module.matches_rule(bold, {"font_size": 9.0}) is True
    assert parser_module.matches_rule(bold, {"font_size": 10.0}) is True
    assert parser_module.matches_rule(bold, {"font_size": 11.0}) is False


def test_string_rules_require_equality(parser_module: ModuleType) -> None:
    """Require exact equality for non-numeric string properties."""
    bold = _tag(parser_module, f"<div {BOLD_10PT}>Item 1. Business</div>")

    assert parser_module.matches_rule(bold, {"text_align": "center"}) is True
    assert parser_module.matches_rule(bold, {"text_align": "left"}) is False


def test_in_table_rule_is_intentionally_asymmetric(parser_module: ModuleType) -> None:
    """Use false for outside-only and true for no table-position constraint.

    Treating true as inside-only would reject ordinary headings whenever one learned
    filing happened to place its headings inside a table.
    """
    outside = _tag(parser_module, f"<div {BOLD_10PT}>Item 1</div>")
    inside = parser_module.BeautifulSoup(
        f"<table><tr><td><div {BOLD_10PT}>Item 1</div></td></tr></table>",
        "html.parser",
    ).find("div")

    assert parser_module.matches_rule(outside, {"in_table": False}) is True
    assert parser_module.matches_rule(inside, {"in_table": False}) is False
    assert parser_module.matches_rule(outside, {"in_table": True}) is True
    assert parser_module.matches_rule(inside, {"in_table": True}) is True


def test_boolean_rules_are_checked_before_numeric_rules(parser_module: ModuleType) -> None:
    """Prevent Python booleans from being interpreted as integer thresholds.

    Because bool subclasses int, checking numbers first would turn true into a minimum
    value of one and silently broaden heading matches.
    """
    element = _tag(parser_module, f"<div {BOLD_10PT}>Item 1</div>")

    assert parser_module.block_props(element)["in_table"] is False
    assert parser_module.matches_rule(element, {"font_weight": True}) is False


def test_block_props_normalizes_weight_and_reads_nested_spans(
    parser_module: ModuleType,
) -> None:
    """Normalize bold to 700 and collect styles from up to two nested spans."""
    keyword = _tag(parser_module, '<div style="font-weight:bold">x</div>')
    numeric = _tag(parser_module, '<div style="font-weight:700">x</div>')
    nested = _tag(
        parser_module,
        '<div><span style="font-weight:700;font-size:14.0pt">Risk Factors</span></div>',
    )

    assert parser_module.block_props(keyword)["font_weight"] == 700
    assert parser_module.block_props(numeric)["font_weight"] == 700
    assert parser_module.block_props(nested)["font_weight"] == 700
    assert parser_module.block_props(nested)["font_size"] == 14.0
    assert parser_module.block_props(_tag(parser_module, "<div>x</div>"))["font_weight"] == 400


def test_block_props_requires_the_whole_block_to_be_semantically_bold(
    parser_module: ModuleType,
) -> None:
    """Do not promote a paragraph whose Item reference alone is bold."""
    partial = _tag(
        parser_module,
        "<p><strong>Item 1A.</strong> appears in this ordinary sentence.</p>",
    )

    assert parser_module.block_props(partial)["font_weight"] == 400


def test_matches_any_uses_or_semantics(parser_module: ModuleType) -> None:
    """Accept an element when any learned heading rule matches."""
    bold = _tag(parser_module, f"<div {BOLD_10PT}>Item 1. Business</div>")
    plain = _tag(parser_module, '<div style="font-weight:400;font-size:9.0pt">Body</div>')
    rules = [{"font_size": 99.0}, {"font_weight": 700}]

    assert parser_module.matches_any(bold, rules) is True
    assert parser_module.matches_any(plain, rules) is False
    assert parser_module.matches_any(bold, []) is False


def test_item_regex_is_anchored_and_prefers_two_digit_items(parser_module: ModuleType) -> None:
    """Reject inline references and capture complete two-digit Item numbers."""

    def item_of(text: str) -> str | None:
        match = parser_module.ITEM_RE.match(text)
        return (match.group("num") + (match.group("suffix") or "")).upper() if match else None

    assert item_of("Item 1. Business") == "1"
    assert item_of("Item 1A. Risk Factors") == "1A"
    assert item_of("Item 15. Exhibits") == "15"
    assert item_of("Item 16") == "16"
    assert item_of("ITEM 7A.") == "7A"
    assert item_of("as described in Item 1A above") is None
