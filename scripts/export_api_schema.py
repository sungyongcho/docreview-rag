"""Export public/administrator or local operator API contracts for generated clients."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.api.app import COMMON_ERROR_RESPONSES, create_api_app
from app.api.routes.admin import router as admin_router
from app.operator.service import create_operator_app


def export_schema() -> str:
    """Build the complete API schema without starting providers or a database."""
    application = create_api_app()
    application.include_router(admin_router, responses=COMMON_ERROR_RESPONSES)
    return json.dumps(application.openapi(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def export_operator_schema() -> str:
    """Export the actual sidecar API without starting commands or reading a user's reset journal."""
    with TemporaryDirectory(prefix="docreview-operator-schema-") as directory:
        application = create_operator_app(
            token="schema-export-only",
            allowed_origin="http://127.0.0.1:8000",
            root=Path(directory),
        )
        return (
            json.dumps(application.openapi(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        )


def main() -> None:
    """Generate the authoritative client input or check its reproducibility."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--operator", action="store_true", help="Export the local operator API.")
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    payload = export_operator_schema() if arguments.operator else export_schema()
    output = arguments.output or Path(
        "schemas/operator.openapi.json" if arguments.operator else "schemas/api.openapi.json"
    )
    if arguments.check:
        if not output.is_file() or output.read_text() != payload:
            raise SystemExit(
                "API schema is out of date; run python -m scripts.export_api_schema"
                + (" --operator" if arguments.operator else "")
            )
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
