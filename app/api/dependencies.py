"""Application-owned domain services shared by administrator routes."""

from dataclasses import dataclass

from app.api.documents.catalog import DocumentCatalog
from app.api.review.runtime import RuntimeApiServices
from app.config import get_settings
from app.corpus_admin.service import RuntimeCorpusAdminService
from app.evals.admin.service import EvaluationAdminService
from app.evals.golden.store import GoldenAdminService
from app.evals.snapshots.service import SnapshotService
from app.operator.jobs.execution import JobExecutionCoordinator
from app.operator.jobs.history import JobHistoryService
from app.operator.jobs.store import JobStore


@dataclass(frozen=True, slots=True)
class AdminDependencies:
    """Hold the domain owners an administrator request actually needs."""

    runtime: RuntimeApiServices
    documents: DocumentCatalog
    corpus: RuntimeCorpusAdminService
    evaluations: EvaluationAdminService
    golden: GoldenAdminService
    snapshots: SnapshotService
    jobs: JobStore
    history: JobHistoryService
    coordinator: JobExecutionCoordinator


def create_admin_services(
    *,
    runtime: RuntimeApiServices,
    corpus: RuntimeCorpusAdminService | None = None,
    evaluations: EvaluationAdminService | None = None,
) -> AdminDependencies:
    """Compose the shared ledger and execution turn before accepting admin requests."""
    jobs = JobStore(session_factory=runtime.session_factory)
    coordinator = JobExecutionCoordinator()
    corpus = corpus or RuntimeCorpusAdminService(
        session_factory=runtime.session_factory,
        embedding_provider=runtime.embedding_provider,
        job_store=jobs,
        corpus_access=runtime.corpus_access,
        execution_coordinator=coordinator,
    )
    corpus.corpus_access = runtime.corpus_access
    evaluations = evaluations or EvaluationAdminService(
        corpus_status=corpus.status,
        session_factory=runtime.session_factory,
        job_store=jobs,
        execution_coordinator=coordinator,
    )
    return AdminDependencies(
        runtime,
        DocumentCatalog(
            runtime.session_factory,
            public_only=False,
            company_names=runtime.company_names,
            embedding_identity=runtime.embedding_provider.identity,
        ),
        corpus,
        evaluations,
        GoldenAdminService(),
        SnapshotService(session_factory=runtime.session_factory),
        jobs,
        JobHistoryService(
            runtime.session_factory, get_settings().corpus_dir.parent / "job-history-backups"
        ),
        coordinator,
    )
