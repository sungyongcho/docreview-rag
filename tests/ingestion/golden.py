"""Measured regression baselines for the 20-document filing corpus.

This file is the single source of truth for corpus-level assertions. The values were
measured from a clean profile state against ``data/corpus/manifest.json``.
"""

# Stages 1-2: (leaf blocks, table blocks, all document tables).
BLOCKS = {
    "AMD-FY2019": (5505, 22, 105),
    "AMD-FY2020": (1394, 54, 74),
    "AMD-FY2021": (1269, 49, 71),
    "AMD-FY2022": (1650, 54, 77),
    "AMD-FY2023": (1484, 43, 76),
    "INTC-FY2019": (10448, 18, 492),
    "INTC-FY2020": (2230, 133, 337),
    "INTC-FY2021": (2344, 119, 324),
    "INTC-FY2022": (2267, 120, 305),
    "INTC-FY2023": (2333, 95, 296),
    "MU-FY2020": (2130, 59, 72),
    "MU-FY2021": (2071, 55, 69),
    "MU-FY2022": (1976, 55, 68),
    "MU-FY2023": (2014, 54, 69),
    "MU-FY2024": (2071, 50, 68),
    "NVDA-FY2020": (5263, 23, 158),
    "NVDA-FY2021": (1323, 46, 59),
    "NVDA-FY2022": (1346, 49, 61),
    "NVDA-FY2023": (1420, 50, 66),
    "NVDA-FY2024": (1341, 52, 66),
}

# Legacy filings contain many wrapper divs, so their block counts are unusually large.
LEGACY_FILES = frozenset({"AMD-FY2019", "NVDA-FY2020", "INTC-FY2019"})

# Final check 2: (all document characters, characters assigned to sections).
COVERAGE = {
    "AMD-FY2019": (358178, 352812),
    "AMD-FY2020": (362278, 355792),
    "AMD-FY2021": (343224, 336569),
    "AMD-FY2022": (380277, 373047),
    "AMD-FY2023": (382481, 375210),
    "INTC-FY2019": (389944, 366166),
    "INTC-FY2020": (398474, 381491),
    "INTC-FY2021": (410587, 389769),
    "INTC-FY2022": (439377, 416727),
    "INTC-FY2023": (440913, 418780),
    "MU-FY2020": (311918, 302485),
    "MU-FY2021": (307031, 297276),
    "MU-FY2022": (292828, 282421),
    "MU-FY2023": (301271, 292345),
    "MU-FY2024": (312017, 303550),
    "NVDA-FY2020": (258346, 247153),
    "NVDA-FY2021": (294000, 282319),
    "NVDA-FY2022": (296849, 285038),
    "NVDA-FY2023": (306714, 295261),
    "NVDA-FY2024": (329808, 318319),
}

# Near-100% coverage usually means cover or TOC material leaked into Item 1.
COVERAGE_BAND = {"number": (95.0, 99.0), "xref": (93.0, 97.0)}

# Final check 1: expected segmentation strategy for each document.
SEGMENT_TYPE = {
    "AMD-FY2019": "number",
    "AMD-FY2020": "number",
    "AMD-FY2021": "number",
    "AMD-FY2022": "number",
    "AMD-FY2023": "number",
    "INTC-FY2019": "xref",
    "INTC-FY2020": "xref",
    "INTC-FY2021": "xref",
    "INTC-FY2022": "xref",
    "INTC-FY2023": "xref",
    "MU-FY2020": "number",
    "MU-FY2021": "number",
    "MU-FY2022": "number",
    "MU-FY2023": "number",
    "MU-FY2024": "number",
    "NVDA-FY2020": "number",
    "NVDA-FY2021": "number",
    "NVDA-FY2022": "number",
    "NVDA-FY2023": "number",
    "NVDA-FY2024": "number",
}

# Expected Item counts grow as SEC Items 1C and 9C become applicable.
N_ITEMS = {
    "AMD-FY2019": 21,
    "AMD-FY2020": 21,
    "AMD-FY2021": 22,
    "AMD-FY2022": 22,
    "AMD-FY2023": 23,
    "INTC-FY2019": 21,
    "INTC-FY2020": 21,
    "INTC-FY2021": 22,
    "INTC-FY2022": 22,
    "INTC-FY2023": 23,
    "MU-FY2020": 21,
    "MU-FY2021": 22,
    "MU-FY2022": 22,
    "MU-FY2023": 22,
    "MU-FY2024": 23,
    "NVDA-FY2020": 20,
    "NVDA-FY2021": 21,
    "NVDA-FY2022": 22,
    "NVDA-FY2023": 22,
    "NVDA-FY2024": 23,
}

# Only these Items may be absent without indicating a missed heading.
ALWAYS_OPTIONAL = frozenset({"1C", "9C", "16"})

# Profile baseline: ticker -> (default year, explicitly learned years).
PROFILE_YEARS = {
    "AMD": ("2023", ["2019", "2021", "2023"]),
    "INTC": ("2019", ["2019"]),
    "MU": ("2024", ["2020", "2021", "2024"]),
    "NVDA": ("2024", ["2020", "2021", "2022", "2024"]),
}

# Learned heading rules: ticker -> year -> (font weight, font size, in table).
PROFILE_RULES = {
    "AMD": {
        "2019": (700, 10.0, True),
        "2021": (700, 10.0, False),
        "2023": (700, 10.0, False),
    },
    "MU": {
        "2020": (700, 14.0, False),
        "2021": (700, 14.0, False),
        "2024": (700, 14.0, False),
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
XREF_TABLES = {
    "INTC-FY2019": (21, 30),
    "INTC-FY2020": (21, 29),
    "INTC-FY2021": (22, 26),
    "INTC-FY2022": (22, 25),
    "INTC-FY2023": (23, 29),
}

# xref page-join result: document -> (Item 7 body characters, Item 8 tables).
XREF_ITEM_SHAPE = {
    "INTC-FY2019": (33_445, 7),
    "INTC-FY2020": (76_692, 65),
    "INTC-FY2021": (69_838, 60),
    "INTC-FY2022": (76_131, 64),
    "INTC-FY2023": (74_065, 52),
}

# Final check 4: source offsets for NVDA-FY2024 headings.
NVDA_FY2024_FILE = "data/corpus/NVDA/2024-02-21_0001045810-24-000029.html"
NVDA_FY2024_OFFSETS = {
    "1": (198007, "Item 1. Business"),
    "1A": (289841, "Item 1A. Risk Factors"),
    "1B": (462881, "Item 1B. Unresolved Staff Comments"),
    "1C": (463352, "Item 1C. Cybersecurity"),
}
