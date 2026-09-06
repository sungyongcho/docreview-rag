"""Live persistence and atomic publication for golden revisions."""

import asyncio
import hashlib
import json

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.evals.golden_admin import GoldenAdminService
from tests.live_postgres import live_postgres_unavailable


def _absent_case(question: str) -> dict[str, object]:
    """Build one strict source-free negative golden case."""
    return {
        "id": "test-01",
        "question": question,
        "category": "absent",
        "facet": "policy",
        "tags": [],
        "answers": [],
        "expected_label": "NOT_IN_DOCS",
        "reference_answer": "NOT_IN_DOCS",
        "note": "Deliberate negative case.",
        "curation_status": "agent-curated",
        "approval_status": "pending-author-approval",
        "human_verified": False,
    }


def test_canonical_cases_are_validated_without_creating_a_revision(tmp_path) -> None:
    """Read canonical JSON as a typed immutable question list without database writes."""
    golden_dir = tmp_path / "golden"
    corpus_dir = tmp_path / "corpus"
    golden_dir.mkdir()
    corpus_dir.mkdir()
    (golden_dir / "retrieval.json").write_text(
        json.dumps([_absent_case("Canonical question?")]), encoding="utf-8"
    )
    service = GoldenAdminService(golden_dir=golden_dir, corpus_dir=corpus_dir)

    canonical = service.canonical("sec-en")

    assert canonical.filename == "retrieval.json"
    assert canonical.payload[0]["question"] == "Canonical question?"
    assert len(canonical.sha256) == 64


async def _exercise(tmp_path) -> tuple[bool, str]:
    """Create, edit, validate, and publish inside one rolled-back connection."""
    engine = create_async_engine(make_url(get_settings().database_url), poolclass=NullPool)
    try:
        try:
            connection = await engine.connect()
        except Exception as error:
            return False, str(error)
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        golden_dir = tmp_path / "golden"
        corpus_dir = tmp_path / "corpus"
        golden_dir.mkdir()
        corpus_dir.mkdir()
        (golden_dir / "retrieval.json").write_text(
            json.dumps([_absent_case("Original question?")]), encoding="utf-8"
        )
        raw = "<p>Source.</p>"
        digest = hashlib.sha256(raw.encode()).hexdigest()
        (corpus_dir / "source.html").write_text(raw)
        manifest = corpus_dir / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "corpus": {"corpus_id": "test", "name": "Test"},
                    "documents": [
                        {
                            "document_id": "TEST-FY2024",
                            "registry": "sec",
                            "language": "en",
                            "issuer": "TEST",
                            "issuer_id": "0000000001",
                            "filing_id": "0000000001-24-000001",
                            "fiscal_year": 2024,
                            "form": "10-K",
                            "filing_date": "2025-01-01",
                            "report_period": "2024-12-31",
                            "source_url": "https://example.org/source",
                            "sec": {
                                "cik": "0000000001",
                                "accession": "0000000001-24-000001",
                                "primary_document": "source.html",
                            },
                        }
                    ],
                    "artifacts": [
                        {
                            "artifact_id": "source",
                            "document_id": "TEST-FY2024",
                            "role": "primary",
                            "path": "source.html",
                            "sha256": digest,
                            "byte_length": len(raw.encode()),
                            "encoding": "utf-8",
                            "acquisition": {
                                "acquired_at": "2025-01-01T00:00:00Z",
                                "url": "https://example.org/source",
                                "media_type": "text/html",
                            },
                        }
                    ],
                    "selections": [{"selection_id": "sec-evaluation", "artifact_ids": ["source"]}],
                }
            ),
            encoding="utf-8",
        )
        service = GoldenAdminService(
            session_factory=factory,
            golden_dir=golden_dir,
            corpus_dir=corpus_dir,
        )
        try:
            draft = await service.create_draft("sec-en")
            changed = _absent_case("Updated question?")
            edited = await service.replace_case(
                draft.revision_id,
                "test-01",
                expected_sha256=draft.sha256,
                payload=changed,
            )
            validated = await service.validate(edited.revision_id, expected_sha256=edited.sha256)
            published = await service.publish(
                validated.revision_id, expected_sha256=validated.sha256
            )
            written = json.loads((golden_dir / "retrieval.json").read_text(encoding="utf-8"))
            assert published.status == "published"
            assert written[0]["question"] == "Updated question?"
        finally:
            await transaction.rollback()
            await connection.close()
        return True, ""
    finally:
        await engine.dispose()


@pytest.mark.live_postgres
def test_golden_revision_lifecycle_is_persisted_and_atomic(tmp_path):
    """Require live PostgreSQL for the complete revision lifecycle."""
    reachable, detail = asyncio.run(_exercise(tmp_path))
    if not reachable:
        live_postgres_unavailable(detail)
