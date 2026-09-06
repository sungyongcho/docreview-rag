"""Measured M1.3 corpus baseline: `(all chunks, text chunks, table chunks)`."""

CHUNK_COUNTS = {
    "AMD-FY2019": (467, 446, 21),
    "AMD-FY2020": (471, 425, 46),
    "AMD-FY2021": (435, 394, 41),
    "AMD-FY2022": (477, 428, 49),
    "AMD-FY2023": (458, 420, 38),
    "INTC-FY2019": (604, 588, 16),
    "INTC-FY2020": (537, 416, 121),
    "INTC-FY2021": (524, 417, 107),
    "INTC-FY2022": (537, 430, 107),
    "INTC-FY2023": (524, 440, 84),
    "MU-FY2020": (422, 365, 57),
    "MU-FY2021": (409, 356, 53),
    "MU-FY2022": (390, 337, 53),
    "MU-FY2023": (406, 354, 52),
    "MU-FY2024": (416, 368, 48),
    "NVDA-FY2020": (398, 376, 22),
    "NVDA-FY2021": (404, 364, 40),
    "NVDA-FY2022": (423, 380, 43),
    "NVDA-FY2023": (425, 381, 44),
    "NVDA-FY2024": (445, 398, 47),
}

TOTAL_CHUNKS = 9_172
TOTAL_TEXT_CHUNKS = 8_083
TOTAL_TABLE_CHUNKS = 1_089
