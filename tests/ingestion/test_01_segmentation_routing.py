from types import ModuleType

from tests.ingestion.parser.support import build_blocks, build_numbered_body


def _xref_body() -> str:
    xref_rows = "".join(
        f"<tr><td>Item {item}.</td><td>Section {item}</td><td>{page}</td></tr>"
        for item, page in [
            ("1", 5),
            ("1A", 11),
            ("2", 15),
            ("3", 19),
            ("4", 25),
            ("5", 30),
            ("6", 35),
            ("7", 40),
            ("8", 45),
            ("16", 120),
        ]
    )
    toc_rows = "".join(
        f"<tr><td>Section {number}</td><td>{number}</td></tr>" for number in range(1, 11)
    )
    return (
        f'<table id="xref">{xref_rows}</table>'
        f'<table id="toc"><tr><th>Section</th><th>Page</th></tr>{toc_rows}</table>'
    )


def test_detect_segmentation_uses_number_then_xref_then_undefined(
    parser_module: ModuleType,
) -> None:
    """Preserve the numbered, xref, and undefined detection cascade.

    The first successful strategy wins. Undefined is returned only when neither body
    headings nor both required xref tables can establish section boundaries.
    """
    numbered_soup, numbered_blocks = build_blocks(parser_module, build_numbered_body())
    xref_soup, xref_blocks = build_blocks(parser_module, _xref_body())
    empty_soup, empty_blocks = build_blocks(parser_module, "<p>Unstructured filing body</p>")

    assert parser_module.detect_segmentation(numbered_soup, numbered_blocks)["type"] == "number"
    assert parser_module.detect_segmentation(xref_soup, xref_blocks) == {"type": "xref"}
    assert parser_module.detect_segmentation(empty_soup, empty_blocks) == {"type": "undefined"}


def test_last_xref_section_keeps_its_later_disjoint_page_range(
    parser_module: ModuleType,
    xref_module: ModuleType,
    monkeypatch,
) -> None:
    """Do not clamp the final located section when no next boundary can receive its tail."""
    soup, blocks = build_blocks(
        parser_module,
        """
        <p>Exhibits</p><p>First disclosure</p><p>5</p>
        <p>6</p><p>Later disclosure</p><p>7</p>
        """,
    )
    entry = xref_module.XrefEntry("15", "Exhibits", [(5, 5), (7, 7)])
    monkeypatch.setattr(parser_module, "find_tables", lambda _soup: (None, None))
    monkeypatch.setattr(parser_module, "parse_xref", lambda _table: [entry])
    monkeypatch.setattr(parser_module, "parse_toc", lambda _table: [("Exhibits", 5)])
    monkeypatch.setattr(parser_module, "in_tables", lambda _blocks, _tables: set())
    monkeypatch.setattr(
        parser_module,
        "locate_sections",
        lambda _blocks, _toc, _skip: [("Exhibits", 5, 0)],
    )
    monkeypatch.setattr(parser_module, "assign_items", lambda _located, _entries: {0: "15"})
    monkeypatch.setattr(parser_module, "find_missing", lambda *_args: [])
    monkeypatch.setattr(parser_module, "page_map", lambda _blocks: [(2, 5), (5, 7)])

    sections, _index = parser_module.segment_by_xref(soup, blocks)
    item_15 = next(section for section in sections if section.item == "15")

    assert "Later disclosure" in [block.text for block in item_15.blocks]
