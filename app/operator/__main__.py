"""Run the host-only Operations API on a fixed loopback interface."""

import os
from pathlib import Path

import uvicorn

from app.operator.service import create_operator_app


def main() -> None:
    """Load ephemeral launch credentials and start the loopback API."""
    token = os.environ.get("DOCREVIEW_OPERATOR_TOKEN", "")
    origin = os.environ.get("DOCREVIEW_OPERATOR_ORIGIN", "http://127.0.0.1:8000")
    port = int(os.environ.get("DOCREVIEW_OPERATOR_PORT", "18001"))
    application = create_operator_app(
        token=token,
        allowed_origin=origin,
        root=Path(__file__).resolve().parents[2],
    )
    uvicorn.run(application, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
