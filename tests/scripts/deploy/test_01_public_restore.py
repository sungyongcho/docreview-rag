"""Read-only acceptance against an explicitly restored disposable PostgreSQL database."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

import asyncpg
import pytest

from tests.live_postgres import live_postgres_unavailable

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.live_postgres
def test_restored_public_portfolio_matches_checked_artifacts(tmp_path):
    """Verify the real restore without touching schema, corpus, vectors or runtime records."""
    dsn = os.environ.get("DOCREVIEW_RESTORE_TEST_DSN")
    artifact_dir = os.environ.get("DOCREVIEW_PUBLIC_ARTIFACT_DIR")
    if not dsn or not artifact_dir:
        live_postgres_unavailable("Set the disposable restore DSN and public artifact directory")
    parsed = urlsplit(dsn)
    assert parsed.hostname in {"127.0.0.1", "localhost"}
    assert parsed.path.startswith("/pipeline_test_")

    async def read_report():
        """Execute the production acceptance SQL in a read-only transaction."""
        connection = await asyncpg.connect(dsn)
        try:
            async with connection.transaction(readonly=True):
                return await connection.fetchval(
                    (ROOT / "deploy/gcp/verify_restore.sql").read_text()
                )
        finally:
            await connection.close()

    report = asyncio.run(read_report())
    assert json.loads(report)["matching_embeddings"] == 10586
    report_path = tmp_path / "database-report.json"
    report_path.write_text(report)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "deploy/gcp/verify_artifacts.py"),
            artifact_dir,
            "--database-report",
            str(report_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "Public portfolio artifacts verified."
