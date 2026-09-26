"""Routing one filing to the segmentation strategy its markup supports."""

from types import ModuleType

from tests.ingestion.edgar.support import build_blocks, build_numbered_body


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
    edgar_module: ModuleType,
) -> None:
    """Preserve the numbered, xref, and undefined detection cascade.

    The first strategy that succeeds wins; undefined means neither could set boundaries.
    """
    numbered_soup, numbered_blocks = build_blocks(edgar_module, build_numbered_body())
    xref_soup, xref_blocks = build_blocks(edgar_module, _xref_body())
    empty_soup, empty_blocks = build_blocks(edgar_module, "<p>Unstructured filing body</p>")

    assert edgar_module.detect_segmentation(numbered_soup, numbered_blocks)["type"] == "number"
    assert edgar_module.detect_segmentation(xref_soup, xref_blocks) == {"type": "xref"}
    assert edgar_module.detect_segmentation(empty_soup, empty_blocks) == {"type": "undefined"}
