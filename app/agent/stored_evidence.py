"""Read cited evidence and selected cells as stored now, for the final-answer review.

These readers are app-internal, not tools: the review calls them after the model
proposes a final answer, so the figure check and the cell selection judge what the
database stores, never what the model wrote.
"""

from sqlalchemy import select

from app.agent.cell_answers import StoredCell
from app.amendments.policy import require_eligible
from app.db.models import Chunk, ChunkTableCell, TableCell
from app.db.session_factory import SessionFactory
from app.figures.answers import EvidenceText
from app.retrieval.tables import (
    cell_ref,
    cell_ref_chunk,
    figure_evidence,
    load_cell_catalog,
    load_table_readings,
)


async def read_cited_evidence(
    session_factory: SessionFactory, chunk_ids: tuple[int, ...]
) -> dict[int, EvidenceText]:
    """Read cited chunks as the answer figure check takes them (see ``figure_evidence``).

    Raises
    ------
    EvidenceWithheldError
        If a cited chunk stopped being evidence after it was retrieved: a later filing
        replaced it or holds it back, so the answer must not be reported from it.
    """
    async with session_factory() as session:
        await require_eligible(session, chunk_ids)
        rows = (
            await session.execute(
                select(Chunk.id, Chunk.kind, Chunk.body, Chunk.context_header).where(
                    Chunk.id.in_(chunk_ids)
                )
            )
        ).all()
        readings = await load_table_readings(session, chunk_ids)
    return {
        chunk_id: figure_evidence(chunk_id, kind, body, context_header, readings)
        for chunk_id, kind, body, context_header in rows
    }


async def read_selected_cells(
    session_factory: SessionFactory, refs: tuple[str, ...]
) -> dict[str, StoredCell]:
    """Read selected cells as stored now, with the signed value the answer is written from.

    A ref whose chunk no longer stores that cell is left out, so the gate treats it as a
    changed source instead of answering from it.

    Raises
    ------
    EvidenceWithheldError
        If a selected cell's chunk stopped being evidence after it was fetched.
    """
    chunk_ids = sorted({cell_ref_chunk(ref) for ref in refs})
    result: dict[str, StoredCell] = {}
    async with session_factory() as session:
        await require_eligible(session, chunk_ids)
        for chunk_id in chunk_ids:
            catalog = await load_cell_catalog(session, chunk_id)
            match catalog["status"]:
                case "not_table" | "missing_records" | "stale_reading":
                    continue
                case "available":
                    pass
                case _:
                    raise ValueError("unknown cell catalog status")
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
