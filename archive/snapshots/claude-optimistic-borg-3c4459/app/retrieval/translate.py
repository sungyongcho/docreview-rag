"""Fail-closed query translation through the existing structured LLM boundary."""

from typing import Annotated, Self

from pydantic import Field, StrictStr
from pydantic.functional_validators import model_validator

from app.llm.provider import LLMProvider
from app.llm.schemas import Prompt, ProviderBudget, StrictSchema
from app.retrieval.language import QueryLanguage, detect_query_language, detect_query_languages

# One prompt per corpus language: a translated arm always translates INTO the
# language the target corpus is written in.
TRANSLATE_SYSTEM_PROMPTS: dict[str, str] = {
    "en": (
        "You translate retrieval queries about United States SEC 10-K filings into "
        "English. Return the English query and the language it came from. Keep tickers, "
        "product names, process nodes, fiscal years, and numbers exactly as they appear "
        "in the input, and do not answer the question or add words the input does not "
        "contain."
    ),
    "ko": (
        "You translate retrieval queries about Korean DART annual reports (사업보고서) "
        "into Korean. Return the Korean query and the language it came from. Keep "
        "tickers, product names, process nodes, fiscal years, and numbers exactly as "
        "they appear in the input, and do not answer the question or add words the "
        "input does not contain."
    ),
}


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
    target_language: str = "en",
) -> QueryTranslation:
    """Translate one query into the corpus language through an injected provider.

    Translation fails closed instead of returning the original query, so an evaluation
    cannot label an untranslated retrieval path as translated.

    Raises
    ------
    ValueError
        If ``query`` is blank or ``target_language`` is unsupported.
    QueryTranslationError
        If the provider refuses, exhausts its budget, fails schema validation after
        one repair, misreports the source language, or returns a query that is not
        in the target language.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    system = TRANSLATE_SYSTEM_PROMPTS.get(target_language)
    if system is None:
        raise ValueError(f"unsupported translation target: {target_language!r}")
    prompt = Prompt(system=system, user=query)
    result = await llm_provider.complete(prompt, QueryTranslation, provider_budget)
    if result.status != "ok" or result.parsed is None:
        raise QueryTranslationError(f"query translation failed: {result.status}")
    translation = result.parsed
    # Both directions are checked against the local detector rather than trusted from
    # the response. ``source_language`` is reported beside every measured number, so a
    # provider that misreads its own input would put an unverifiable claim into the
    # run artifact while the score still looked clean.
    source_language = detect_query_language(query)
    if translation.source_language != source_language:
        raise QueryTranslationError(
            f"translated query reports source {translation.source_language!r}, "
            f"but the input is {source_language!r}"
        )
    if detect_query_language(translation.translated_query) != target_language:
        raise QueryTranslationError(
            f"translated query is not in the target language {target_language!r}"
        )
    return translation


class RoutedQuery(StrictSchema):
    """One structured rewrite targeting an exact corpus language lane."""

    translated_query: Annotated[StrictStr, Field(min_length=1)]
    target_language: QueryLanguage

    @model_validator(mode="after")
    def reject_blank_routed_query(self) -> Self:
        """Reject a whitespace-only query variant."""
        if not self.translated_query.strip():
            raise ValueError("translated_query must not be blank")
        return self


async def route_query(
    query: str,
    *,
    target_language: QueryLanguage,
    llm_provider: LLMProvider,
    provider_budget: ProviderBudget,
) -> RoutedQuery:
    """Rewrite one raw query into a corpus lane through the strict provider boundary."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    system = TRANSLATE_SYSTEM_PROMPTS[target_language]
    prompt = Prompt(
        system=(
            f"{system} The input may already contain {target_language} or mixed scripts. "
            "Preserve every issuer name, ticker, number, fiscal year, and product name."
        ),
        user=query,
    )
    result = await llm_provider.complete(prompt, RoutedQuery, provider_budget)
    if result.status != "ok" or result.parsed is None:
        raise QueryTranslationError(f"query routing failed: {result.status}")
    routed = result.parsed
    if routed.target_language != target_language:
        raise QueryTranslationError("query routing returned the wrong target language")
    if target_language not in detect_query_languages(routed.translated_query):
        raise QueryTranslationError("routed query does not contain the target language")
    return routed
