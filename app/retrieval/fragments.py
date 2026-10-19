"""Read the stored table fragments of retrieved table chunks."""

from collections.abc import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, SnapshotChunk


async def load_table_fragments(
    session: AsyncSession,
    chunk_ids: Iterable[int],
    snapshot_id: int | None = None,
) -> dict[int, Mapping[str, object]]:
    """Return the stored fragment of each table chunk, from the index it was retrieved from.

    Chunks without a fragment (text chunks, or tables chunked before fragments existed)
    are left out.
    """
    ids = sorted(set(chunk_ids))
    if not ids:
        return {}
    if snapshot_id is None:
        query = select(Chunk.id, Chunk.table_fragment).where(Chunk.id.in_(ids))
    else:
        query = select(SnapshotChunk.chunk_id, SnapshotChunk.table_fragment).where(
            SnapshotChunk.snapshot_id == snapshot_id, SnapshotChunk.chunk_id.in_(ids)
        )
    rows = (await session.execute(query)).all()
    return {chunk_id: fragment for chunk_id, fragment in rows if isinstance(fragment, dict)}
