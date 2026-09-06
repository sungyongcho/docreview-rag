"""Inspect or prepare the local Compose schema without resetting existing data."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.bootstrap import SchemaDriftError, ensure_schema_compatibility
from app.db.models import Base
from scripts.local_env import load_local_environment
from scripts.quickstart import prepare_schema


async def schema_status(url: str, *, prepare: bool = False) -> dict[str, object]:
    """Inspect compatibility, optionally creating only an empty database's schema."""
    try:
        created = await prepare_schema(url) if prepare else False
        engine = create_async_engine(url, echo=False)
        try:
            async with engine.connect() as connection:
                await ensure_schema_compatibility(connection)
                tables = set(
                    await connection.run_sync(lambda sync: inspect(sync).get_table_names())
                )
            missing = sorted(set(Base.metadata.tables) - tables)
            status = "empty" if not tables else "incomplete" if missing else "compatible"
            return {"schema_status": status, "created": created, "missing_tables": missing}
        finally:
            await engine.dispose()
    except (SchemaDriftError, ValueError) as error:
        return {"schema_status": "drifted", "message": str(error), "created": False}
    except SQLAlchemyError as error:
        return {
            "schema_status": "unavailable",
            "message": f"Local database connection failed ({type(error).__name__}).",
            "created": False,
        }


def main() -> int:
    """Use the selected checkout's local published DB port, never an external DSN."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "prepare"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    bindings = load_local_environment(root / ".env", mode="dev")
    url = f"postgresql+asyncpg://filing:filing@127.0.0.1:{bindings['DB_PORT']}/filing"
    result = asyncio.run(schema_status(url, prepare=args.action == "prepare"))
    print(json.dumps(result, indent=2))
    return 0 if result["schema_status"] in {"compatible", "empty"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
