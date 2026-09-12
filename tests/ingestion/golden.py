"""Measured regression baselines for the committed twenty-document filing corpus.

This file is the single source of truth for corpus-level assertions. The values were
measured from a clean profile state against ``data/corpus/manifest.json``.

The corpus is widened from the command line, so these baselines are a **subset** of
whatever the manifest holds today rather than an inventory of it. Compare through
``measured`` so a filing someone added is not asserted against numbers nobody
measured for it, while a baseline document that disappeared still fails.
"""

from collections.abc import Mapping


def measured[T](actual: Mapping[str, T], baseline: Mapping[str, T]) -> dict[str, T]:
    """Return the measured documents' values, refusing a baseline the corpus has lost.

    Parameters
    ----------
    actual : Mapping[str, T]
        What this run produced, over the whole corpus.
    baseline : Mapping[str, T]
        The measured values, keyed by document ID.
    """
    missing = sorted(set(baseline) - set(actual))
    assert not missing, f"documents measured in the baseline are gone from the corpus: {missing}"
    return {document: value for document, value in actual.items() if document in baseline}


# Stages 1-2: (leaf blocks, table blocks, all document tables).
BLOCKS = {
    "sec-0000002488-20-000008": (5505, 22, 105),
    "sec-0001628280-21-001185": (1394, 54, 74),
    "sec-0000002488-22-000016": (1269, 49, 71),
    "sec-0000002488-23-000047": (1650, 54, 77),
    "sec-0000002488-24-000012": (1484, 43, 76),
    "sec-0001045810-20-000010": (5263, 23, 158),
    "sec-0001045810-21-000010": (1323, 46, 59),
    "sec-0001045810-22-000036": (1346, 49, 61),
    "sec-0001045810-23-000017": (1420, 50, 66),
    "sec-0001045810-24-000029": (1341, 52, 66),
}

# Legacy filings contain many wrapper divs, so their block counts are unusually large.
LEGACY_FILES = frozenset({"sec-0000002488-20-000008", "sec-0001045810-20-000010"})

# Final check 2: (all document characters, characters assigned to sections).
COVERAGE = {
    "sec-0000002488-20-000008": (358178, 352812),
    "sec-0001628280-21-001185": (362278, 355792),
    "sec-0000002488-22-000016": (343224, 336569),
    "sec-0000002488-23-000047": (380277, 373047),
    "sec-0000002488-24-000012": (382481, 375210),
    "sec-0001045810-20-000010": (258346, 247153),
    "sec-0001045810-21-000010": (294000, 282319),
    "sec-0001045810-22-000036": (296849, 285038),
    "sec-0001045810-23-000017": (306714, 295261),
    "sec-0001045810-24-000029": (329808, 318319),
}

# Near-100% coverage usually means cover or TOC material leaked into Item 1.
COVERAGE_BAND = {"number": (95.0, 99.0), "xref": (93.0, 97.0)}

# Final check 1: expected segmentation strategy for each document.
SEGMENT_TYPE = {
    "sec-0000002488-20-000008": "number",
    "sec-0001628280-21-001185": "number",
    "sec-0000002488-22-000016": "number",
    "sec-0000002488-23-000047": "number",
    "sec-0000002488-24-000012": "number",
    "sec-0001045810-20-000010": "number",
    "sec-0001045810-21-000010": "number",
    "sec-0001045810-22-000036": "number",
    "sec-0001045810-23-000017": "number",
    "sec-0001045810-24-000029": "number",
}

# Expected Item counts grow as SEC Items 1C and 9C become applicable.
N_ITEMS = {
    "sec-0000002488-20-000008": 21,
    "sec-0001628280-21-001185": 21,
    "sec-0000002488-22-000016": 22,
    "sec-0000002488-23-000047": 22,
    "sec-0000002488-24-000012": 23,
    "sec-0001045810-20-000010": 20,
    "sec-0001045810-21-000010": 21,
    "sec-0001045810-22-000036": 22,
    "sec-0001045810-23-000017": 22,
    "sec-0001045810-24-000029": 23,
}

# Only these Items may be absent without indicating a missed heading.
ALWAYS_OPTIONAL = frozenset({"1C", "9C", "16"})

# Profile baseline: ticker -> (default year, explicitly learned years).
PROFILE_YEARS = {
    "AMD": ("2023", ["2019", "2020", "2021", "2023"]),
    "NVDA": ("2024", ["2020", "2021", "2022", "2024"]),
}

# Learned heading rules: ticker -> year -> (font weight, font size, in table).
PROFILE_RULES = {
    "AMD": {
        "2019": (700, 10.0, True),
        "2020": (700, 10.0, False),
        "2021": (700, 10.0, False),
        "2023": (700, 10.0, False),
    },
    "NVDA": {
        "2020": (700, 11.0, False),
        "2021": (700, 11.0, False),
        "2022": (700, 11.0, False),
        "2024": (700, 10.0, False),
    },
}

# Every expected non-parsed section in NVDA-FY2024.
STATUS_NVDA_FY2024 = {
    "1B": "empty_disclosure",
    "4": "empty_disclosure",
    "9": "empty_disclosure",
    "8": "incorporated_by_reference",
    "9C": "incorporated_by_reference",
    "11": "incorporated_by_reference",
    "13": "incorporated_by_reference",
}
NVDA_FY2024_ITEM15_MIN_CHARS = 80_000

# xref baseline: document -> (index entries, TOC rows).
# Intel filings use xref segmentation; these baselines reactivate when the
# filings are re-acquired under their accession-keyed document ids.
XREF_TABLES = {
    "sec-0000050863-20-000011": (21, 30),
    "sec-0000050863-21-000010": (21, 29),
    "sec-0000050863-22-000007": (22, 26),
    "sec-0000050863-23-000006": (22, 25),
    "sec-0000050863-24-000010": (23, 29),
}

# xref page-join result: document -> (Item 7 body characters, Item 8 tables).
XREF_ITEM_SHAPE = {
    "sec-0000050863-20-000011": (33_445, 7),
    "sec-0000050863-21-000010": (76_692, 65),
    "sec-0000050863-22-000007": (69_838, 60),
    "sec-0000050863-23-000006": (76_131, 64),
    "sec-0000050863-24-000010": (74_065, 52),
}

# Final check 4: source offsets for NVDA-FY2024 headings.
NVDA_FY2024_FILE = "data/corpus/sec/NVDA/0001045810-24-000029/primary.html"
NVDA_FY2024_OFFSETS = {
    "1": (198007, "Item 1. Business"),
    "1A": (289841, "Item 1A. Risk Factors"),
    "1B": (462881, "Item 1B. Unresolved Staff Comments"),
    "1C": (463352, "Item 1C. Cybersecurity"),
}

# M1.2 table conversion baseline.
# Tuple: (empty markdown, expanded cells, collapsed cells).
# The table-block count is already pinned by ``BLOCKS``, so it is not repeated here.
#
# SEC tables are layout tables. The median table has 63.6% empty raw cells,
# the corpus has no <th>, and colspan positions content. A logical three-column
# income statement arrives as 12 physical columns.
#
# The stages are 221,730 expanded cells, 70,358 cells after empty-axis removal,
# and 47,918 cells after unit folding. A higher final count leaves layout behind;
# a lower count removes content. The 26 empty outputs are layout-only spacer tables.
TABLES = {
    "sec-0000002488-20-000008": (0, 3628, 2494),
    "sec-0001628280-21-001185": (4, 10644, 1995),
    "sec-0000002488-22-000016": (4, 10098, 1799),
    "sec-0000002488-23-000047": (1, 11577, 2220),
    "sec-0000002488-24-000012": (1, 9603, 1925),
    "sec-0001045810-20-000010": (0, 3689, 2337),
    "sec-0001045810-21-000010": (0, 10473, 1821),
    "sec-0001045810-22-000036": (0, 12090, 1986),
    "sec-0001045810-23-000017": (0, 11100, 1924),
    "sec-0001045810-24-000029": (0, 11937, 2108),
}

# The one NVDA-FY2024 table holding both "Gross profit" and "Net income per share" is the
# Consolidated Statements of Income. Its 18 physical columns collapse to four: each year
# pairs a currency column with a value column, and spacer columns separate the years.
# The header rows are centered spans, so every year keeps its "Year Ended" context.
NVDA_FY2024_INCOME_MD = """\
|  | Year Ended Jan 28, 2024 | Year Ended Jan 29, 2023 | Year Ended Jan 30, 2022 |
| --- | --- | --- | --- |
| Revenue | $ 60,922 | $ 26,974 | $ 26,914 |
| Cost of revenue | 16,621 | 11,618 | 9,439 |
| Gross profit | 44,301 | 15,356 | 17,475 |
| Operating expenses |  |  |  |
| Research and development | 8,675 | 7,339 | 5,268 |
| Sales, general and administrative | 2,654 | 2,440 | 2,166 |
| Acquisition termination cost | — | 1,353 | — |
| Total operating expenses | 11,329 | 11,132 | 7,434 |
| Operating income | 32,972 | 4,224 | 10,041 |
| Interest income | 866 | 267 | 29 |
| Interest expense | (257) | (262) | (236) |
| Other, net | 237 | (48) | 107 |
| Other income (expense), net | 846 | (43) | (100) |
| Income before income tax | 33,818 | 4,181 | 9,941 |
| Income tax expense (benefit) | 4,058 | (187) | 189 |
| Net income | $ 29,760 | $ 4,368 | $ 9,752 |
| Net income per share: |  |  |  |
| Basic | $ 12.05 | $ 1.76 | $ 3.91 |
| Diluted | $ 11.93 | $ 1.74 | $ 3.85 |
| Weighted average shares used in per share computation: |  |  |  |
| Basic | 2,469 | 2,487 | 2,496 |
| Diluted | 2,494 | 2,507 | 2,535 |"""
