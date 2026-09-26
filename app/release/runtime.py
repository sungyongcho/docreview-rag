"""Compose providers and the database-backed review runtime."""

from __future__ import annotations

from app.api.review.runtime import RuntimeApiServices
from app.config import Settings
from app.llm.local.connection import build_local_runtime
from app.llm.openai import OpenAILLMProvider
from app.llm.openai_limits import OpenAILimitsManager
from app.release.config import ReleaseSettings
from app.release.secrets import install_secret_redaction
from app.retrieval.embedding.provider import get_embedding_provider


def build_runtime_services(settings: ReleaseSettings) -> RuntimeApiServices:
    """Compose runtime services without activating a provider from key presence alone."""
    if settings.service_mode != "runtime":
        raise ValueError("runtime services require DOCREVIEW_MODE=runtime")
    providers = {}
    budgets = {}
    secrets: list[str] = []
    if settings.openai_api_key is not None:
        api_key = settings.openai_api_key.get_secret_value()
        provider = OpenAILLMProvider(model_name=settings.openai_model, api_key=api_key)
        providers["openai"] = provider
        budgets["openai"] = settings.provider_budget()
        secrets.append(api_key)
    # The ceiling is known without a key, so Dev can inspect and lower it before enabling OpenAI.
    openai_limits = OpenAILimitsManager(
        settings.provider_budget(), enabled=settings.environment != "prod"
    )
    local_connection, local_budget = build_local_runtime(
        environment=settings.environment,
        base_url=settings.local_llm_base_url,
        protocol=settings.local_llm_protocol,
        source=settings.local_llm_source,
        api_key=settings.local_llm_api_key.get_secret_value()
        if settings.local_llm_api_key
        else None,
        max_input_tokens=settings.local_llm_max_input_tokens,
        max_output_tokens=settings.local_llm_max_output_tokens,
    )
    if local_budget is not None:
        budgets["local"] = local_budget
        if settings.local_llm_api_key is not None:
            secrets.append(settings.local_llm_api_key.get_secret_value())
    install_secret_redaction(tuple(secrets))
    corpus_settings = Settings.model_validate(
        {
            "environment": settings.environment,
            "openai_api_key_dev": settings.openai_api_key_dev,
            "openai_api_key_prod": settings.openai_api_key_prod,
        }
    )
    return RuntimeApiServices(
        embedding_provider=get_embedding_provider(corpus_settings),
        llm_providers=providers,
        provider_budgets=budgets,
        local_connection=local_connection,
        openai_limits=openai_limits,
        allow_local_engine=settings.environment != "prod",
        local_timeout_s=settings.local_llm_timeout_s,
        secret_values=tuple(secrets),
        credential_slot=settings.openai_key_slot,
        bm25_k1=corpus_settings.bm25_k1,
        bm25_b=corpus_settings.bm25_b,
        bm25_idf=corpus_settings.bm25_idf,
        intent_classifier_enabled=True,
        query_routing_enabled=True,
        allow_custom_prompt_policy=settings.admin_enabled,
        allow_snapshot_query=settings.admin_enabled,
    )
