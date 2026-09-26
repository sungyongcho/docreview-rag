"""Read provider usage totals from the persisted request ledger."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter
from pydantic import Field, StrictBool
from sqlalchemy import select

from app.api.dependencies import AdminDependency
from app.api.errors import translate_runtime_errors
from app.contracts.validation import NonNegativeInt, StrictSchema
from app.db.models import OperatorJob, Run
from app.db.session_factory import SessionFactory
from app.observability.usage import USAGE_KEY, merge_usage, review_usage


class UsageModelResource(StrictSchema):
    """One model's locally recorded token and estimated-cost totals."""

    model_name: str
    provider: str = "unknown"
    local: StrictBool | None = None
    credential_slot: str = "unknown"
    role: str = "unknown"
    estimated_input_tokens: NonNegativeInt = 0
    unreported_input_requests: NonNegativeInt = 0
    unreported_cost_requests: NonNegativeInt = 0
    requests: NonNegativeInt
    input_tokens: NonNegativeInt
    cached_input_tokens: NonNegativeInt
    cache_write_input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    reasoning_tokens: NonNegativeInt
    estimated_cost_usd: Decimal = Field(ge=0, allow_inf_nan=False)


class UsageProviderResource(StrictSchema):
    """One provider/credential group with exact subtotals of its model-role rows."""

    provider: str
    local: StrictBool | None
    credential_slot: str
    requests: NonNegativeInt
    input_tokens: NonNegativeInt
    cached_input_tokens: NonNegativeInt
    cache_write_input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    reasoning_tokens: NonNegativeInt
    estimated_input_tokens: NonNegativeInt
    unreported_input_requests: NonNegativeInt
    unreported_cost_requests: NonNegativeInt
    estimated_cost_usd: Decimal = Field(ge=0, allow_inf_nan=False)
    models: tuple[UsageModelResource, ...]


class UsageResponse(StrictSchema):
    """Locally accounted provider usage without an OpenAI account API call."""

    runs: NonNegativeInt
    requests: NonNegativeInt
    input_tokens: NonNegativeInt
    cached_input_tokens: NonNegativeInt
    cache_write_input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    reasoning_tokens: NonNegativeInt
    estimated_cost_usd: Decimal = Field(ge=0, allow_inf_nan=False)
    latest_run_at: datetime | None
    models: tuple[UsageModelResource, ...]
    providers: tuple[UsageProviderResource, ...] = ()
    estimated_input_tokens: NonNegativeInt = 0
    unreported_input_requests: NonNegativeInt = 0
    unreported_cost_requests: NonNegativeInt = 0


router = APIRouter(prefix="/admin", tags=["admin"])


async def usage_summary(session_factory: SessionFactory) -> UsageResponse:
    """Aggregate review and embedding evidence without provider calls or schema migration."""
    async with session_factory() as session:
        runs = (
            await session.execute(
                select(Run.created_at, Run.request_context["model_calls"].label("model_calls"))
            )
        ).all()
        ledgers = (
            (
                await session.execute(
                    select(OperatorJob.result_refs[USAGE_KEY]).where(
                        OperatorJob.result_refs.op("?")(USAGE_KEY)
                    )
                )
            )
            .scalars()
            .all()
        )
    records = []
    for run in runs:
        records.extend(review_usage({"model_calls": run.model_calls}))
    for ledger in ledgers:
        if not isinstance(ledger, list) or any(not isinstance(row, dict) for row in ledger):
            raise ValueError("Persisted embedding usage ledger is invalid")
        records.extend(ledger)
    models = tuple(
        UsageModelResource.model_validate(
            {**row, "estimated_cost_usd": Decimal(str(row["estimated_cost_usd"]))}
        )
        for row in merge_usage(records)
    )
    grouped = {}
    for model in models:
        grouped.setdefault((model.provider, model.local, model.credential_slot), []).append(model)

    def totals(
        rows: list[UsageModelResource] | tuple[UsageModelResource, ...],
    ) -> dict[str, object]:
        """Compute all header and group totals from the same displayed model-role rows."""
        counts = {
            field: sum(getattr(row, field) for row in rows)
            for field in (
                "requests",
                "input_tokens",
                "cached_input_tokens",
                "cache_write_input_tokens",
                "output_tokens",
                "reasoning_tokens",
                "estimated_input_tokens",
                "unreported_input_requests",
                "unreported_cost_requests",
            )
        }
        return {
            **counts,
            "estimated_cost_usd": sum((row.estimated_cost_usd for row in rows), Decimal(0)),
        }

    providers = tuple(
        (
            UsageProviderResource.model_validate(
                {
                    "provider": key[0],
                    "local": key[1],
                    "credential_slot": key[2],
                    "models": tuple(rows),
                    **totals(rows),
                }
            )
            for key, rows in grouped.items()
        )
    )
    return UsageResponse.model_validate(
        {
            "runs": len(runs),
            "latest_run_at": max((run.created_at for run in runs), default=None),
            "models": models,
            "providers": providers,
            **totals(models),
        }
    )


@router.get("/usage", response_model=UsageResponse)
async def provider_usage(services: AdminDependency) -> UsageResponse:
    """Return locally persisted token and estimated-cost totals."""
    async with translate_runtime_errors():
        return await usage_summary(services.runtime.session_factory)
