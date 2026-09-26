"""Construct application services with shared corpus, provider, and job ownership."""

from dataclasses import dataclass

from app.api.documents.catalog import DocumentCatalog
from app.api.review.runtime import RuntimeApiServices
from app.config import Settings, get_settings
from app.corpus_admin.service import RuntimeCorpusAdminService
from app.evals.admin.service import EvaluationAdminService
from app.evals.golden.store import GoldenAdminService
from app.evals.snapshots.service import SnapshotService
from app.operator.jobs.execution import JobExecutionCoordinator
from app.operator.jobs.history import JobHistoryService
from app.operator.jobs.store import JobStore


@dataclass(frozen=True, slots=True)
class AdminServices:
    """Domain owners sharing one runtime and one persistent job ledger."""

    runtime: RuntimeApiServices
    documents: DocumentCatalog
    corpus: RuntimeCorpusAdminService
    evaluations: EvaluationAdminService
    golden: GoldenAdminService
    snapshots: SnapshotService
    jobs: JobStore
    history: JobHistoryService
    coordinator: JobExecutionCoordinator


def runtime_settings(runtime: RuntimeApiServices) -> Settings:
    """Use the selected runtime corpus for public readers and administrator services."""
    settings = get_settings()
    if runtime.corpus_root is not None:
        settings = settings.model_copy(update={"corpus_dir": runtime.corpus_root})
    return settings


def create_admin_services(*, runtime: RuntimeApiServices) -> AdminServices:
    """Compose administrators around the runtime's resources and a shared execution turn."""
    settings = runtime_settings(runtime)
    jobs = JobStore(session_factory=runtime.session_factory)
    coordinator = JobExecutionCoordinator()
    corpus = RuntimeCorpusAdminService(
        settings=settings,
        session_factory=runtime.session_factory,
        embedding_provider=runtime.embedding_provider,
        job_store=jobs,
        corpus_access=runtime.corpus_access,
        execution_coordinator=coordinator,
    )
    evaluations = EvaluationAdminService(
        settings=settings,
        provider=runtime.embedding_provider,
        corpus_status=corpus.status,
        session_factory=runtime.session_factory,
        job_store=jobs,
        execution_coordinator=coordinator,
    )
    return AdminServices(
        runtime=runtime,
        documents=DocumentCatalog(
            runtime.session_factory,
            public_only=False,
            company_names=runtime.company_names,
            embedding_identity=runtime.embedding_provider.identity,
        ),
        corpus=corpus,
        evaluations=evaluations,
        golden=GoldenAdminService(),
        snapshots=runtime.snapshots,
        jobs=jobs,
        history=JobHistoryService(
            runtime.session_factory, settings.corpus_dir.parent / "job-history-backups"
        ),
        coordinator=coordinator,
    )
