"""Export the public and administrator API contracts for generated clients."""

import argparse
import json
from pathlib import Path

from app.api.app import COMMON_ERROR_RESPONSES, create_api_app
from app.api.routes.admin import router as admin_router


def export_schema() -> str:
    """Build the complete API schema without starting providers or a database."""
    application = create_api_app()
    application.include_router(admin_router, responses=COMMON_ERROR_RESPONSES)
    return json.dumps(application.openapi(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def main() -> None:
    """Generate the authoritative client input or check its reproducibility."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("schemas/api.openapi.json"))
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    payload = export_schema()
    if arguments.check:
        if not arguments.output.is_file() or arguments.output.read_text() != payload:
            raise SystemExit("API schema is out of date; run python -m scripts.export_api_schema")
        return
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
