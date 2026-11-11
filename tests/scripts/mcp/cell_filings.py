"""Serve the controlled filings server with stored table cells for chunk 2024.

Run as ``python -m tests.scripts.mcp.cell_filings <log path>``. It is
``tests.mcp.controlled_filings`` with ``include_cells`` on and only the stored-cell
catalog read replaced, so ``fetch_chunk`` returns chunk 2024 with one known revenue
cell through the production registry, validation and stdio transport.
"""

import asyncio
from pathlib import Path
import sys
from typing import Any
from unittest.mock import patch

from tests.mcp.controlled_filings import main

STABLE_KEY = "k" * 64
RESOLVER_IDENTITY = "r" * 64
REVENUE_CELL: dict[str, Any] = {
    "ref": "2024:r1c1",
    "row_label": "Net revenue",
    "column_header": "2024",
    "raw_text": "$ 25,785",
    "item": "revenue",
    "fiscal_years": [2024],
    "scale": "1000000",
    "currency": "USD",
    "percent": False,
    "status": "known",
    "complete": True,
}


async def load_cell_catalog(session: object, chunk_id: int) -> dict[str, object]:
    """Return chunk 2024's stored table with its revenue cell; other chunks are text."""
    del session
    if chunk_id != 2024:
        return {"status": "not_table"}
    return {
        "status": "available",
        "stable_key": STABLE_KEY,
        "resolver_identity": RESOLVER_IDENTITY,
        "unit": {"status": "known", "scale": "1000000", "currency": ["USD"]},
        "cells": [REVENUE_CELL],
    }


if __name__ == "__main__":
    with patch("app.agent.tools.filings.load_cell_catalog", load_cell_catalog):
        asyncio.run(main(Path(sys.argv[1]), include_cells=True))
