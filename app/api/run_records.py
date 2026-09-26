"""Read stored review runs, their traces and evaluation results without running any work."""

from collections.abc import Sequence
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import translate_runtime_errors
from app.api.schemas import EvalResultResource
from app.db.models import EvalResult, Run, Trace
from app.db.session_factory import SessionFactory
from app.observability.persistence import record_to_step, records_to_report
from app.observability.types import JsonObject, RunReport, StepTrace


async def _trace_rows(session: AsyncSession, run_id: str) -> tuple[Trace, ...]:
    """Read this run's traces in recorded step order."""
    rows = await session.scalars(select(Trace).where(Trace.run_id == run_id).order_by(Trace.step))
    return tuple(rows)


class RunRecords:
    """Load persisted runs, their ordered traces and evaluation results.

    Each read opens its own session and turns a database failure into a typed API error,
    so a stored record is only projected back out and never re-executes workflow code.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get_run(self, run_id: str) -> RunReport | None:
        """Load one run and ordered traces without executing workflow code."""
        async with translate_runtime_errors():
            async with self._session_factory() as session:
                run = await session.get(Run, run_id)
                if run is None:
                    return None
                traces = await _trace_rows(session, run_id)
                return records_to_report(run, traces)

    async def get_traces(self, run_id: str) -> Sequence[StepTrace] | None:
        """Load ordered traces only when their parent run exists."""
        async with translate_runtime_errors():
            async with self._session_factory() as session:
                run = await session.get(Run, run_id)
                if run is None:
                    return None
                traces = await _trace_rows(session, run_id)
                return tuple(
                    record_to_step(trace, request_context=run.request_context) for trace in traces
                )

    async def list_eval_results(self, limit: int) -> Sequence[EvalResultResource]:
        """Load newest evaluation records through their strict public schema."""
        statement = select(EvalResult).order_by(EvalResult.created_at.desc(), EvalResult.id.desc())
        async with translate_runtime_errors():
            async with self._session_factory() as session:
                rows = tuple(await session.scalars(statement.limit(limit)))
        return tuple(
            EvalResultResource(
                result_id=row.id,
                suite=row.suite,
                # JSONB deserializes to JSON values; the ORM annotation is wider.
                config=cast("JsonObject", row.config),
                metrics={name: float(value) for name, value in row.metrics.items()},
                raw_artifact_path=row.raw_artifact_path,
                created_at=row.created_at,
            )
            for row in rows
        )
