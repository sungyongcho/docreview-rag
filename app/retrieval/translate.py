"""Fail-closed query translation through the existing structured LLM boundary."""

from typing import Annotated, Self

from pydantic import Field, StrictStr
from pydantic.functional_validators import model_validator

from app.llm import LLMProvider, Prompt, ProviderBudget, StrictSchema
from app.retrieval.language import QueryLanguage, detect_query_language

TRANSLATE_SYSTEM_PROMPT = (
    "You translate retrieval queries about United States SEC 10-K filings into English. "
    "Return the English query and the language it came from. Keep tickers, product names, "
    "process nodes, fiscal years, and numbers exactly as they appear in the input, and do "
    "not answer the question or add words the input does not contain."
)


class QueryTranslationError(RuntimeError):
    """One translation request refused, failed validation, or stayed non-English."""


class QueryTranslation(StrictSchema):
    """One structured translation of a query into the corpus language."""

    translated_query: Annotated[StrictStr, Field(min_length=1)]
    source_language: QueryLanguage

    @model_validator(mode="after")
    def reject_blank_translation(self) -> Self:
        """Reject a whitespace-only translation instead of passing it downstream."""
        if not self.translated_query.strip():
            raise ValueError("translated_query must not be blank")
        return self


async def translate_query(
    query: str,
    *,
    llm_provider: LLMProvider,
    provider_budget: ProviderBudget,
) -> QueryTranslation:
    """Translate one query into English, or raise rather than return the original.

    The provider is injected, never read from ``Settings``. A translation arm costs
    money and adds a network hop to the query path, so it can only be switched on by
    a caller that already holds a provider — a configuration flag could turn it on
    everywhere, including inside a request that never asked for it.

    Unlike ``decompose_query``, this call does not fall back to the input on failure.
    Decomposition is an optimization over a query the retriever can already run; a
    failed translation would leave the Korean query to be scored as if it had been
    translated, and the measured number would then describe an arm that never ran.

    Raises
    ------
    ValueError
        If ``query`` is blank.
    QueryTranslationError
        If the provider refuses, exhausts its budget, fails schema validation after
        one repair, or returns a query that still contains Hangul.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    prompt = Prompt(system=TRANSLATE_SYSTEM_PROMPT, user=query)
    result = await llm_provider.complete(prompt, QueryTranslation, provider_budget)
    if result.status != "ok" or result.parsed is None:
        raise QueryTranslationError(f"query translation failed: {result.status}")
    translation = result.parsed
    if detect_query_language(translation.translated_query) != "en":
        raise QueryTranslationError("translated query is not English")
    return translation
