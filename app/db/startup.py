"""Gate runtime image startup on a prepared, compatible database without provider calls."""

from __future__ import annotations

import asyncio
import json
import os
import sys

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.bootstrap import SchemaDriftError, prepare_empty_schema


async def prepare(url: str) -> bool:
    """Use the container's effective database target and always release its connection."""
    engine = create_async_engine(url, echo=False)
    try:
        return await prepare_empty_schema(engine)
    finally:
        await engine.dispose()


def main() -> int:
    """Prepare only runtime databases, then replace the gate with the shipped app command."""
    command = sys.argv[1:]
    if not command:
        print("A server command is required.", file=sys.stderr)
        return 2
    if os.environ.get("DOCREVIEW_MODE", "canned") == "runtime":
        url = os.environ.get("DATABASE_URL")
        if not url:
            print("Database configuration is missing; server startup blocked.", file=sys.stderr)
            return 1
        try:
            created = asyncio.run(prepare(url))
        except SchemaDriftError as error:
            print(
                json.dumps({"schema_status": "drifted", "created": False, "message": str(error)}),
                flush=True,
            )
            print(
                "Server startup blocked; existing data preserved. In a local checkout run "
                "uv run python -m scripts.schema_status check, then "
                "uv run python -m scripts.schema_status recover --return-stage index. "
                "To discard only local DEV database contents, explicitly review "
                "uv run python -m scripts.schema_status recreate. "
                "For deployed databases, select a compatible target or an explicitly approved "
                "migration. Restarting does not repair drift.",
                flush=True,
            )
            return 1
        except SQLAlchemyError, OSError, ValueError:
            print(
                "Database preparation unavailable; server startup blocked. Check database "
                "health and configuration. No reset was performed.",
                file=sys.stderr,
            )
            return 1
        print(json.dumps({"schema_status": "compatible", "created": created}), flush=True)
    os.execvp(command[0], command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
