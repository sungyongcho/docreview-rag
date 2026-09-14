"""Check, prepare, recover, or explicitly recreate the local Compose schema."""

import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys

from sqlalchemy.exc import SQLAlchemyError

from scripts.schema.status import schema_status
from scripts.stack.environment import load_local_environment


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
    parser.add_argument(
        "--keep-sources",
        action="store_true",
        help="Recreate DB only, preserving downloaded source files.",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Clean DB and sources, then preset NVDA/AMD FY2023–2024 without downloading.",
    )
    args = parser.parse_args()
    if (args.keep_sources or args.sample) and args.action != "recreate":
        parser.error("--keep-sources and --sample require recreate")
    if args.keep_sources and args.sample:
        parser.error("--keep-sources and --sample are mutually exclusive")
    root = Path(__file__).resolve().parents[2]
    if args.parent and args.action != "recover":
        parser.error("--parent is only available with recover")
    if args.action == "recreate":
        from scripts.schema.recreate import run

        try:
            return (
                1
                if run(root, keep_sources=args.keep_sources, sample=args.sample) == "incomplete"
                else 0
            )
        except ValueError, OSError, SQLAlchemyError, subprocess.CalledProcessError:
            print(
                "Recreation could not be confirmed. The API may remain stopped. "
                "Check DB access/dependencies and run rag-dev schema check before retrying. "
                "Inspect any retained source journal before retrying. "
                "DB changes are transactional, "
                "but connection loss can leave the commit outcome unconfirmed. "
                "No automatic retry occurs.",
                file=sys.stderr,
            )
            return 1
        except EOFError, KeyboardInterrupt:
            print(
                "Stopped. Run rag-dev schema check to inspect state; no automatic retry.",
                file=sys.stderr,
            )
            return 130
    if args.action == "recover":
        from scripts.schema.recovery import create_recovery, start_recovery

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
                    "In that directory: uv sync --locked; source ./rag-alias.sh; "
                    "rag-dev compose up -d --wait db; uv run python -m scripts.schema prepare; "
                    "rag-dev compose up --build -d; uv run python -m scripts.schema check.",
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
