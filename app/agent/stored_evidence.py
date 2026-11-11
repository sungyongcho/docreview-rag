"""Read cited evidence and selected cells as stored now, for the final-answer review.

These readers are app-internal, not tools: the review calls them after the model
proposes a final answer, so the figure check and the cell selection judge what the
database stores, never what the model wrote.
"""

from sqlalchemy import select

from app.agent.cell_answers import StoredCell
from app.db.models import Chunk, ChunkTableCell, TableCell
from app.db.session_factory import SessionFactory
from app.figures.answers import EvidenceText
from app.retrieval.tables import (
    cell_ref,
    cell_ref_chunk,
    load_cell_catalog,
    load_chunk_tables,
)


async def read_cited_evidence(
    session_factory: SessionFactory, chunk_ids: tuple[int, ...]
) -> dict[int, EvidenceText]:
    """Read cited chunks' text and stored table readings for the answer figure check.

    A table chunk whose stored table is stale (built or read by code other than the
    running code) is cited with no body and no cells, so nothing in it can confirm a
    figure: its body is never read as running text in place of its table.
    """
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(Chunk.id, Chunk.body, Chunk.context_header).where(Chunk.id.in_(chunk_ids))
            )
        ).all()
        tables = await load_chunk_tables(session, chunk_ids)
    evidence: dict[int, EvidenceText] = {}
    for chunk_id, body, context_header in rows:
        table = tables.get(chunk_id)
        if table is not None and table.stale:
            evidence[chunk_id] = EvidenceText(chunk_id, "", context_header, ())
        else:
            readings = None if table is None else table.readings
            evidence[chunk_id] = EvidenceText(chunk_id, body, context_header, readings)
    return evidence


async def read_selected_cells(
    session_factory: SessionFactory, refs: tuple[str, ...]
) -> dict[str, StoredCell]:
    """Read selected cells as stored now, with the signed value the answer is written from.

    A ref whose chunk no longer stores that cell is left out, so the gate treats it as a
    changed source instead of answering from it.
    """
    chunk_ids = sorted({cell_ref_chunk(ref) for ref in refs})
    result: dict[str, StoredCell] = {}
    async with session_factory() as session:
        for chunk_id in chunk_ids:
            catalog = await load_cell_catalog(session, chunk_id)
            if catalog["status"] != "available":
                continue
            values = {
                cell_ref(chunk_id, row, column): value
                for row, column, value in await session.execute(
                    select(ChunkTableCell.source_row, ChunkTableCell.column_index, TableCell.value)
                    .join(
                        TableCell,
                        (TableCell.table_id == ChunkTableCell.table_id)
                        & (TableCell.source_row == ChunkTableCell.source_row)
                        & (TableCell.column_index == ChunkTableCell.column_index),
                    )
                    .where(ChunkTableCell.chunk_id == chunk_id)
                )
            }
            cells = catalog["cells"]
            assert isinstance(cells, list)
            for cell in cells:
                if cell["ref"] in refs:
                    result[cell["ref"]] = StoredCell(
                        cell["ref"],
                        chunk_id,
                        cell,
                        str(catalog["stable_key"]),
                        str(catalog["resolver_identity"]),
                        values.get(cell["ref"]),
                    )
    return result
