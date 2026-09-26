"""Local model connection and working OpenAI limit controls."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal, Self

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.composition import AdminServices
from app.api.dependencies import AdminDependency
from app.api.errors import ApiProblemError, translate_runtime_errors, unavailable
from app.llm.local.connection import (
    ConnectionSource,
    LocalConnectionError,
    LocalConnectionManager,
    LocalProtocol,
    validate_base_url,
)
from app.llm.openai_limits import (
    CEILING_ENV_KEYS,
    OpenAICallLimits,
    OpenAILimitsError,
    OpenAILimitsManager,
)


class LocalConnectionRequest(BaseModel):
    """A candidate endpoint entered in the developer connection settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    base_url: str = Field(min_length=1, max_length=2048)
    protocol: LocalProtocol = "auto"

    @field_validator("base_url")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        """Reject credentials and non-HTTP addresses before any server request."""
        return validate_base_url(value)


class LocalModelPrepareRequest(BaseModel):
    """Name an installed model on the already selected server, never an arbitrary endpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    model: str = Field(min_length=1, max_length=256)


class LocalConnectionResponse(BaseModel):
    """Private settings state and safe model metadata for the developer UI."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    base_url: str | None
    initial_base_url: str
    protocol: LocalProtocol
    source: ConnectionSource
    error: str | None
    local: dict[str, Any]
    servers: tuple[LocalServerResource, ...]
    selected_server_id: str | None


class LocalServerResource(BaseModel):
    """A named private endpoint, including the runtime-resolved Default entry."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    name: str
    base_url: str
    protocol: LocalProtocol
    is_default: bool


class OpenAILimitsRequest(BaseModel):
    """Working per-call caps for Dev; each value must stay at or below the ceiling."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    max_input_tokens: int = Field(ge=1, le=100_000)
    max_output_tokens: int = Field(ge=1, le=4_000)
    max_cost_usd: Decimal = Field(gt=0, le=1)


class OpenAILimitsResponse(OpenAICallLimits):
    """Effective caps, their ceiling and where to raise the ceiling outside the web."""

    ceiling_env_keys: dict[str, str]
    file_path: str


class LocalServerRequest(LocalConnectionRequest):
    """Register and connect a named server without editing environment configuration."""

    name: str = Field(min_length=1, max_length=80)


class LocalServerSelectionRequest(BaseModel):
    """Select one registered server or the built-in Default identifier."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    server_id: str = Field(min_length=1, max_length=80)


class LocalDiagnosticsRequest(BaseModel):
    """Choose the active connection, a registered server, or one unsaved draft to inspect."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    server_id: str | None = Field(default=None, min_length=1, max_length=80)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    protocol: LocalProtocol = "auto"

    @field_validator("base_url")
    @classmethod
    def validate_endpoint(cls, value: str | None) -> str | None:
        """Reject secret-bearing addresses before a diagnostic metadata probe."""
        return validate_base_url(value) if value is not None else None

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        """Require one unambiguous target so a draft cannot override a selected identifier."""
        if self.server_id is not None and self.base_url is not None:
            raise ValueError("Choose a registered server or a draft URL, not both.")
        return self


class LocalDiagnosticCheck(BaseModel):
    """One nonsecret status and its predefined remediation identifiers."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: Literal["configuration", "connection", "models"]
    status: Literal["passed", "failed", "blocked", "unknown"]
    code: str
    remediation: tuple[str, ...]


class LocalDiagnosticsResponse(BaseModel):
    """Metadata-only diagnostic evidence without raw errors, paths, or credentials."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    checked_at: str
    server_id: str | None
    server_name: str
    protocol: LocalProtocol
    reachable: bool | None
    available: bool
    model_count: int | None
    answer_model_count: int | None
    models: tuple[dict[str, Any], ...]
    checks: tuple[LocalDiagnosticCheck, ...]


router = APIRouter(prefix="/admin", tags=["admin"])


def _local_connection(dependencies: AdminServices) -> LocalConnectionManager:
    """Require an enabled developer connection manager, including on SSH admin routes."""
    connection = dependencies.runtime.local_connection
    if connection is None or not connection.enabled:
        raise ApiProblemError(
            status_code=403,
            code="disabled_in_prod",
            message="Local LLM settings are available only in Dev.",
        )
    return connection


async def _local_connection_state(dependencies: AdminServices) -> dict[str, Any]:
    """Read the active endpoint and model information for developer settings."""
    return await _local_connection(dependencies).state()


async def _update_local_connection(
    dependencies: AdminServices,
    action: Literal["disconnect", "add", "select"],
    base_url: str = "",
    protocol: LocalProtocol = "auto",
    *,
    name: str = "",
    server_id: str = "",
) -> dict[str, Any]:
    """Apply one explicit configuration action and translate safe persistence failures."""
    connection = _local_connection(dependencies)
    try:
        if action == "disconnect":
            return await connection.disconnect()
        if action == "add":
            return await connection.add_server(name, base_url, protocol)
        return await connection.select_server(server_id)
    except LocalConnectionError as error:
        raise unavailable(error.code, str(error)) from error


def _openai_limits(dependencies: AdminServices) -> OpenAILimitsManager:
    """Require the Dev-only per-call cap manager; production keeps the ceiling."""
    limits = dependencies.runtime.openai_limits
    if limits is None or not limits.enabled:
        raise ApiProblemError(
            status_code=403,
            code="disabled_in_prod",
            message="OpenAI per-call caps are adjustable only in Dev.",
        )
    return limits


def _openai_limits_payload(
    dependencies: AdminServices, limits: OpenAILimitsManager
) -> dict[str, Any]:
    """Add the environment keys and file path the web tells the user about."""
    return {
        **limits.state().model_dump(),
        "ceiling_env_keys": dict(CEILING_ENV_KEYS),
        "file_path": str(limits.path),
    }


def _openai_limits_state(dependencies: AdminServices) -> dict[str, Any]:
    """Read effective and ceiling per-call caps without changing them."""
    return _openai_limits_payload(dependencies, _openai_limits(dependencies))


async def _update_openai_limits(
    dependencies: AdminServices,
    *,
    max_input_tokens: int,
    max_output_tokens: int,
    max_cost_usd: Decimal,
) -> dict[str, Any]:
    """Persist working caps below the ceiling and translate safe failures."""
    limits = _openai_limits(dependencies)
    try:
        await limits.save(
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
            max_cost_usd=max_cost_usd,
        )
    except OpenAILimitsError as error:
        if error.code in {"openai_limits_above_ceiling", "openai_limits_invalid"}:
            raise ApiProblemError(status_code=422, code=error.code, message=str(error)) from error
        raise unavailable(error.code, str(error)) from error
    return _openai_limits_payload(dependencies, limits)


async def _reset_openai_limits(dependencies: AdminServices) -> dict[str, Any]:
    """Delete the saved caps so the ceiling applies again."""
    limits = _openai_limits(dependencies)
    try:
        await limits.reset()
    except OpenAILimitsError as error:
        raise unavailable(error.code, str(error)) from error
    return _openai_limits_payload(dependencies, limits)


async def _prepare_local_model(dependencies: AdminServices, model: str) -> dict[str, Any]:
    """Prepare the selected server's installed model under the developer-only guard."""
    try:
        return await _local_connection(dependencies).prepare_model(model)
    except LocalConnectionError as error:
        raise unavailable(error.code, str(error)) from error


async def _diagnose_local_connection(
    dependencies: AdminServices,
    *,
    server_id: str | None = None,
    base_url: str | None = None,
    protocol: LocalProtocol = "auto",
) -> dict[str, Any]:
    """Probe metadata for one explicit target without changing server selection or settings."""
    return await _local_connection(dependencies).diagnose(
        server_id=server_id, base_url=base_url, protocol=protocol
    )


@router.get("/local-llm/connection", response_model=LocalConnectionResponse)
async def local_connection_state(services: AdminDependency) -> dict[str, Any]:
    """Return private connection settings without changing the selected endpoint."""
    async with translate_runtime_errors():
        return await _local_connection_state(services)


@router.post("/local-llm/disconnect", response_model=LocalConnectionResponse)
async def disconnect_local_llm(services: AdminDependency) -> dict[str, Any]:
    """Save explicit disconnection so environment defaults cannot reactivate it."""
    async with translate_runtime_errors():
        return await _update_local_connection(services, "disconnect")


@router.post("/local-llm/servers", response_model=LocalConnectionResponse)
async def register_local_server(
    request: LocalServerRequest, services: AdminDependency
) -> dict[str, Any]:
    """Register and select a verified named server while preserving prior choices on failure."""
    async with translate_runtime_errors():
        return await _update_local_connection(
            services, "add", request.base_url, request.protocol, name=request.name
        )


@router.post("/local-llm/select", response_model=LocalConnectionResponse)
async def select_local_server(
    request: LocalServerSelectionRequest, services: AdminDependency
) -> dict[str, Any]:
    """Verify and select a saved endpoint or Default without accepting a new URL."""
    async with translate_runtime_errors():
        return await _update_local_connection(services, "select", server_id=request.server_id)


@router.post("/local-llm/prepare", response_model=LocalConnectionResponse)
async def prepare_local_model(
    request: LocalModelPrepareRequest, services: AdminDependency
) -> dict[str, Any]:
    """Load one installed model without generating an answer or changing connection settings."""
    async with translate_runtime_errors():
        return await _prepare_local_model(services, request.model)


@router.post("/local-llm/diagnostics", response_model=LocalDiagnosticsResponse)
async def diagnose_local_server(
    request: LocalDiagnosticsRequest, services: AdminDependency
) -> dict[str, Any]:
    """Inspect bounded metadata without modifying the active connection or loading a model."""
    async with translate_runtime_errors():
        return await _diagnose_local_connection(
            services,
            server_id=request.server_id,
            base_url=request.base_url,
            protocol=request.protocol,
        )


@router.get("/openai/limits", response_model=OpenAILimitsResponse)
async def openai_limits_state(services: AdminDependency) -> dict[str, Any]:
    """Return the effective OpenAI per-call caps and the ceiling they may not exceed."""
    async with translate_runtime_errors():
        return _openai_limits_state(services)


@router.post("/openai/limits", response_model=OpenAILimitsResponse)
async def save_openai_limits(
    request: OpenAILimitsRequest, services: AdminDependency
) -> dict[str, Any]:
    """Save lower working caps for Dev; raising the ceiling stays a .env change."""
    async with translate_runtime_errors():
        return await _update_openai_limits(
            services,
            max_input_tokens=request.max_input_tokens,
            max_output_tokens=request.max_output_tokens,
            max_cost_usd=request.max_cost_usd,
        )


@router.post("/openai/limits/reset", response_model=OpenAILimitsResponse)
async def reset_openai_limits(services: AdminDependency) -> dict[str, Any]:
    """Remove the saved working caps so the ceiling applies again."""
    async with translate_runtime_errors():
        return await _reset_openai_limits(services)
