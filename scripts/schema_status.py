"""Inspect or prepare the local Compose schema without resetting existing data."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys

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
    parser.add_argument("action", choices=("check", "prepare", "recover", "recreate"))
    parser.add_argument(
        "--parent",
        type=Path,
        help="Existing directory outside this checkout for a new isolated recovery clone.",
    )
    parser.add_argument(
        "--return-stage",
        choices=("filings", "index", "embeddings", "lexical", "ask", "answer_model", "evaluate"),
        default="index",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.parent and args.action != "recover":
        parser.error("--parent is only available with recover")
    if args.action == "recreate":
        from scripts.schema_recreate import run

        try:
            return run(root)
        except ValueError, OSError, SQLAlchemyError, subprocess.CalledProcessError:
            print(
                "Recreation could not be confirmed. The API may remain stopped. "
                "Check DB access/dependencies and run schema_status check before retrying. "
                "DB changes are transactional; no automatic retry occurs.",
                file=sys.stderr,
            )
            return 1
        except EOFError, KeyboardInterrupt:
            print(
                "Stopped. Run schema_status check to inspect state; no automatic retry.",
                file=sys.stderr,
            )
            return 130
    if args.action == "recover":
        from scripts.schema_recovery import create_recovery, start_recovery

        target = None
        try:
            target = create_recovery(root, args.parent or root.parent)
            start_recovery(target, return_stage=args.return_stage)
        except ValueError, RuntimeError, OSError, subprocess.CalledProcessError:
            print(
                "Recovery did not complete; no readiness claim can be made. "
                "Original data was preserved.",
                file=sys.stderr,
            )
            if target:
                print(f"Inspect the retained recovery checkout: {target}", file=sys.stderr)
                print(
                    "In that directory: uv sync --locked; source ./rag_alias.sh; "
                    "rag-dev up -d --wait db; uv run python -m scripts.schema_status prepare; "
                    "rag-dev up --build -d; uv run python -m scripts.schema_status check.",
                    file=sys.stderr,
                )
            return 1
        return 0
    if args.parent:
        parser.error("--parent is only available with recover")
    bindings = load_local_environment(root / ".env", mode="dev")
    url = f"postgresql+asyncpg://filing:filing@127.0.0.1:{bindings['DB_PORT']}/filing"
    result = asyncio.run(schema_status(url, prepare=args.action == "prepare"))
    result["database_target"] = f"127.0.0.1:{bindings['DB_PORT']}/filing"
    print(json.dumps(result, indent=2))
    return 0 if result["schema_status"] in {"compatible", "empty"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
