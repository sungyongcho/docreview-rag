"""Secret-safe provider identities and migration-free persisted usage aggregation."""

from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import ipaddress
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OperatorJob

USAGE_KEY = "provider_usage"
LEDGER_KIND = "embedding_usage"
UsageSink = Callable[[dict[str, object]], Awaitable[None]]
_ACTIVE_USAGE: ContextVar[UsageSink | None] = ContextVar("embedding_usage_sink", default=None)
_FIELDS = (
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


def provider_identity(
    *,
    api_url: str | None = None,
    provider: str | None = None,
    local: bool | None = None,
    credential_slot: str | None = None,
) -> dict[str, JsonValue]:
    """Classify recorded provenance while exposing only allowlisted credential slot names."""
    known = {
        "openai",
        "openai_responses",
        "openai_embeddings",
        "openai_compatible",
        "ollama",
        "sbert",
        "deterministic",
        "external_api",
        "local",
        "unknown",
    }
    selected = provider if isinstance(provider, str) and provider in known else None
    local = local if type(local) is bool else None
    credential_slot = credential_slot if isinstance(credential_slot, str) else None
    try:
        parsed = urlparse(api_url or "")
        hostname = (parsed.hostname or "").lower()
        path = parsed.path.lower()
    except ValueError:
        hostname, path = "", ""
        parsed = urlparse("")
    inferred_local = None
    if parsed.scheme == "local":
        selected = selected or ("ollama" if hostname == "ollama" else "openai_compatible")
        inferred_local = True
    elif parsed.scheme == "deterministic":
        selected = "deterministic"
        inferred_local = True
    if hostname and parsed.scheme not in {"local", "deterministic"}:
        inferred_local = hostname in {
            "localhost",
            "host.docker.internal",
            "ollama",
            "host.containers.internal",
        }
        try:
            address = ipaddress.ip_address(hostname)
            inferred_local = address.is_loopback or address.is_private
        except ValueError:
            pass
    if selected is None:
        if hostname == "api.openai.com":
            selected = "openai_embeddings" if "embedding" in path else "openai_responses"
        elif "/api/" in path and ("chat" in path or "generate" in path or "embed" in path):
            selected = "ollama"
        elif hostname:
            selected = "openai_compatible" if "/v1/" in path else "external_api"
        else:
            selected = "unknown"
    if local is None:
        local = True if selected in {"sbert", "deterministic", "local"} else inferred_local
    slots = {
        "dev": "OPENAI_API_KEY_LOCAL",
        "prod": "OPENAI_API_KEY_PROD",
        "OPENAI_API_KEY_LOCAL": "OPENAI_API_KEY_LOCAL",
        "OPENAI_API_KEY_PROD": "OPENAI_API_KEY_PROD",
        "explicit": "explicit",
        "none": "none",
        "unknown": "unknown",
    }
    return {
        "provider": selected,
        "local": local,
        "credential_slot": slots.get(credential_slot or "unknown", "unknown"),
    }


@contextmanager
def observe_embedding_usage(sink: UsageSink) -> Iterator[None]:
    """Bind usage to this async request without changing a shared provider instance."""
    token = _ACTIVE_USAGE.set(sink)
    try:
        yield
    finally:
        _ACTIVE_USAGE.reset(token)


async def emit_embedding_usage(record: dict[str, object]) -> None:
    """Await the active durable sink before continuing a charged provider operation."""
    sink = _ACTIVE_USAGE.get()
    if sink is not None:
        await sink(record)


def usage_record(
    *,
    identity: Mapping[str, object],
    model_name: str,
    role: str,
    requests: int = 1,
    input_tokens: int | None = None,
    estimated_input_tokens: int = 0,
    estimated_cost_usd: Decimal | None = None,
    **counts: int,
) -> dict[str, object]:
    """Separate reported values, local estimates, and unavailable usage explicitly."""
    record = {**identity, "model_name": model_name, "role": role, **{key: 0 for key in _FIELDS}}
    record.update({key: value for key, value in counts.items() if key in _FIELDS})
    record.update(
        requests=requests,
        input_tokens=input_tokens or 0,
        estimated_input_tokens=estimated_input_tokens,
        unreported_input_requests=requests if input_tokens is None else 0,
        unreported_cost_requests=requests if estimated_cost_usd is None else 0,
        estimated_cost_usd=str(estimated_cost_usd or Decimal(0)),
    )
    return record


def merge_usage(records: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Sum canonical identity/model/role rows, retaining explicit unavailable counters."""
    grouped = {}
    for record in records:
        provider = record.get("provider")
        local = record.get("local")
        slot = record.get("credential_slot")
        identity = provider_identity(
            provider=provider if isinstance(provider, str) else None,
            local=local if isinstance(local, bool) else None,
            credential_slot=slot if isinstance(slot, str) else None,
        )
        key = (
            identity["provider"],
            identity["local"],
            identity["credential_slot"],
            str(record.get("model_name", "unknown")),
            str(record.get("role", "unknown")),
        )
        row = grouped.setdefault(
            key,
            {
                **identity,
                "model_name": key[3],
                "role": key[4],
                **{field: 0 for field in _FIELDS},
                "estimated_cost_usd": Decimal(0),
            },
        )
        for field in _FIELDS:
            value = record.get(field, 0)
            if type(value) is not int or value < 0:
                raise ValueError("Persisted usage has invalid token or request counts")
            row[field] += value
        try:
            cost = Decimal(str(record.get("estimated_cost_usd", "0")))
        except InvalidOperation as error:
            raise ValueError("Persisted usage has invalid cost") from error
        if not cost.is_finite() or cost < 0:
            raise ValueError("Persisted usage has invalid cost")
        row["estimated_cost_usd"] += cost
    return [
        {**row, "estimated_cost_usd": str(row["estimated_cost_usd"])}
        for _, row in sorted(grouped.items(), key=lambda item: str(item[0]))
    ]


async def persist_embedding_usage(session: AsyncSession, record: dict[str, object]) -> None:
    """Record CLI backfill usage in a terminal archived ledger without any schema addition."""
    now = datetime.now(UTC)
    async with session.begin():
        session.add(
            OperatorJob(
                job_id=f"embedding-usage-{uuid4().hex}",
                domain="corpus",
                kind=LEDGER_KIND,
                request_json={"origin": "cli_backfill", "executable": False},
                status="succeeded",
                stage="usage_recorded",
                current=1,
                total=1,
                message="Recorded embedding provider usage; this ledger entry cannot be executed.",
                result_refs={USAGE_KEY: [record], "__history_archived": True},
                created_at=now,
                started_at=now,
                finished_at=now,
                updated_at=now,
            )
        )


def recorded_model_calls(run_context: Mapping[str, object] | None) -> list[dict[str, Any]]:
    """Read current call records; an explicit empty list records a provider-free run."""
    calls = (run_context or {}).get("model_calls")
    if not isinstance(calls, list):
        raise ValueError("recorded model calls must be a list")
    if any(not isinstance(call, dict) for call in calls):
        raise ValueError("recorded model calls must be objects")
    return calls


def review_usage(run_context: Mapping[str, object] | None) -> list[dict[str, object]]:
    """Project each recorded call once, including routing and unsent provider denials."""
    return [
        usage_record(
            identity=provider_identity(
                provider=call["provider"],
                local=call["local"],
                credential_slot=call["credential_slot"],
            ),
            model_name=call["model"],
            role=call["node"] or "unknown",
            requests=call["attempts"],
            input_tokens=call["input_tokens"],
            cached_input_tokens=call["cached_input_tokens"],
            cache_write_input_tokens=call["cache_write_input_tokens"],
            output_tokens=call["output_tokens"],
            reasoning_tokens=call["reasoning_tokens"],
            estimated_cost_usd=Decimal(call["estimated_cost_usd"]),
        )
        for call in recorded_model_calls(run_context)
    ]
