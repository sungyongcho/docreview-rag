"""Role-scoped OpenAI model policy with pinned prices and reasoning settings."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Literal

from app.llm.schemas import TokenPricing

type OpenAIModelRole = Literal[
    "agent",
    "review",
    "decomposition",
    "translation",
    "embedding",
]
type ReasoningEffort = Literal["low", "medium"]

POLICY_REVISION = "2026-09-10"


@dataclass(frozen=True, slots=True)
class OpenAIModelSelection:
    """Validated model, role, pricing, and request settings."""

    role: OpenAIModelRole
    model: str
    reasoning_effort: ReasoningEffort | None
    pricing: TokenPricing
    dimensions: int | None = None


class OpenAIModelPolicyError(ValueError):
    """Raised before client construction for a model outside its role policy."""


_TERRA = TokenPricing(
    input_per_million_usd=Decimal("2.00"),
    cached_input_per_million_usd=Decimal("0.20"),
    cache_write_input_per_million_usd=Decimal("2.50"),
    output_per_million_usd=Decimal("12.00"),
)
_LUNA = TokenPricing(
    input_per_million_usd=Decimal("0.20"),
    cached_input_per_million_usd=Decimal("0.02"),
    cache_write_input_per_million_usd=Decimal("0.25"),
    output_per_million_usd=Decimal("1.20"),
)
_EMBEDDING_LARGE = TokenPricing(
    input_per_million_usd=Decimal("0.13"),
    cached_input_per_million_usd=Decimal("0.13"),
    cache_write_input_per_million_usd=Decimal("0.13"),
    output_per_million_usd=Decimal("0"),
)

_DEFAULTS: MappingProxyType[OpenAIModelRole, str] = MappingProxyType(
    {
        "agent": "gpt-5.6-luna",
        "review": "gpt-5.6-luna",
        "decomposition": "gpt-5.6-luna",
        "translation": "gpt-5.6-luna",
        "embedding": "text-embedding-3-large",
    }
)
_ALLOWED: MappingProxyType[OpenAIModelRole, tuple[str, ...]] = MappingProxyType(
    {
        "agent": ("gpt-5.6-luna", "gpt-5.6-terra"),
        "review": ("gpt-5.6-luna", "gpt-5.6-terra"),
        "decomposition": ("gpt-5.6-luna", "gpt-5.6-terra"),
        "translation": ("gpt-5.6-luna", "gpt-5.6-terra"),
        "embedding": ("text-embedding-3-large",),
    }
)
_REASONING: MappingProxyType[OpenAIModelRole, ReasoningEffort | None] = MappingProxyType(
    {
        "agent": "medium",
        "review": "medium",
        "decomposition": "medium",
        "translation": "low",
        "embedding": None,
    }
)


def resolve_openai_model(
    role: OpenAIModelRole,
    model: str | None = None,
) -> OpenAIModelSelection:
    """Resolve and validate one role-specific OpenAI model selection."""
    selected = _DEFAULTS[role] if model is None else model.strip()
    if not selected or selected not in _ALLOWED[role]:
        allowed = ", ".join(_ALLOWED[role])
        raise OpenAIModelPolicyError(
            f"OpenAI model {model!r} is not allowed for role {role!r}; allowed: {allowed}"
        )
    if selected == "gpt-5.6-terra":
        pricing = _TERRA
    elif selected == "gpt-5.6-luna":
        pricing = _LUNA
    else:
        pricing = _EMBEDDING_LARGE
    return OpenAIModelSelection(
        role=role,
        model=selected,
        reasoning_effort=_REASONING[role],
        pricing=pricing,
        dimensions=384 if role == "embedding" else None,
    )


def openai_policy_snapshot() -> dict[str, object]:
    """Return the non-secret policy projection used by readiness and documentation."""
    roles: dict[str, object] = {}
    for role in _DEFAULTS:
        selection = resolve_openai_model(role)
        roles[role] = {
            "default": selection.model,
            "allowed": list(_ALLOWED[role]),
            "reasoning_effort": selection.reasoning_effort,
            "dimensions": selection.dimensions,
        }
    return {"revision": POLICY_REVISION, "roles": roles}
