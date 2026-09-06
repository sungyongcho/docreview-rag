"""Strict prompt, budget, judgment, decision, and provider-result schemas."""

from decimal import Decimal

from pydantic import ValidationError
import pytest

from app.llm.schemas import (
    AnswerDecision,
    BudgetExceeded,
    ChunkRelevance,
    Prompt,
    ProviderBudget,
    ProviderMetadata,
    ProviderRefusal,
    ProviderResult,
    RelevanceJudgment,
    SchemaRejected,
    TokenPricing,
)


def metadata():
    """Build valid provider metadata for one completed call."""
    return ProviderMetadata(
        provider="deterministic",
        model_name="deterministic-mock",
        api_url="deterministic://local",
        input_tokens=10,
        output_tokens=5,
        estimated_cost_usd=Decimal("0"),
        request_time_ms=1.0,
        retries=0,
        request_ids=("req-1",),
        llm_output="{}",
        raw_outputs=("{}",),
    )


def supported_decision():
    """Build a supported answer decision carrying one citation."""
    return AnswerDecision(
        label="SUPPORTED",
        answer="Research expense increased.",
        citation_chunk_ids=(7,),
        reason="The cited chunk contains the statement.",
    )


def test_prompt_is_strict_frozen_and_forbids_unknown_fields():
    """Freeze a prompt and refuse any field the schema does not declare."""
    prompt = Prompt(system="Return structured evidence.", user="What changed?")

    with pytest.raises(ValidationError):
        Prompt(system="Return structured evidence.", user=7)
    with pytest.raises(ValidationError):
        Prompt(system="Return structured evidence.", user="What changed?", extra=True)
    with pytest.raises(ValidationError):
        prompt.user = "mutated"


@pytest.mark.parametrize("field", ["system", "user"])
def test_prompt_rejects_whitespace_only_text(field):
    """Reject a prompt whose system or user text is only whitespace."""
    values = {"system": "system", "user": "user"}
    values[field] = "   "

    with pytest.raises(ValidationError):
        Prompt(**values)


def test_token_pricing_uses_exact_decimal_arithmetic():
    """Price tokens in exact decimals so no cost drifts through binary floats."""
    pricing = TokenPricing(
        input_per_million_usd=Decimal("2"),
        output_per_million_usd=Decimal("10"),
    )

    assert pricing.estimate(100, 20) == Decimal("0.0004")
    with pytest.raises(ValueError):
        pricing.estimate(-1, 0)


@pytest.mark.parametrize(
    ("changes", "expected_error"),
    [
        ({"max_input_tokens": True}, ValidationError),
        ({"max_output_tokens": 0}, ValidationError),
        ({"max_cost_usd": -Decimal("0.01")}, ValidationError),
        ({"unknown": 1}, ValidationError),
    ],
)
def test_provider_budget_requires_explicit_strict_limits_and_pricing(changes, expected_error):
    """Require explicit strict limits and pricing on every budget."""
    values = {
        "max_input_tokens": 1_000,
        "max_output_tokens": 100,
        "max_cost_usd": Decimal("0.10"),
        "pricing": TokenPricing(
            input_per_million_usd=Decimal("0"),
            output_per_million_usd=Decimal("0"),
        ),
    }
    values.update(changes)

    with pytest.raises(expected_error):
        ProviderBudget(**values)


def test_relevance_judgment_rejects_coercion_and_duplicate_chunks():
    """Reject coerced values and repeated chunk ids in one judgment."""
    with pytest.raises(ValidationError):
        ChunkRelevance(chunk_id=1, relevant=1, reason="Relevant")

    grade = ChunkRelevance(chunk_id=1, relevant=True, reason="Exact evidence")
    with pytest.raises(ValidationError):
        RelevanceJudgment(grades=(grade, grade))


def test_supported_decision_requires_unique_citations_and_non_absent_answer():
    """Require unique citations and a real answer on a supported decision."""
    decision = supported_decision()

    assert decision.label == "SUPPORTED"
    with pytest.raises(ValidationError):
        AnswerDecision(
            label="SUPPORTED",
            answer="Supported.",
            citation_chunk_ids=(),
            reason="No citation was supplied.",
        )
    with pytest.raises(ValidationError):
        AnswerDecision(
            label="SUPPORTED",
            answer="Supported.",
            citation_chunk_ids=(2, 2),
            reason="Duplicate citation.",
        )


def test_not_in_docs_decision_requires_literal_answer_and_no_citations():
    """Require the literal absent answer and no citations when nothing is supported."""
    decision = AnswerDecision(
        label="NOT_IN_DOCS",
        answer="NOT_IN_DOCS",
        citation_chunk_ids=(),
        reason="The retrieved evidence does not support the claim.",
    )

    assert decision.citation_chunk_ids == ()
    with pytest.raises(ValidationError):
        AnswerDecision(
            label="NOT_IN_DOCS",
            answer="Maybe absent.",
            citation_chunk_ids=(),
            reason="Ambiguous answer.",
        )
    with pytest.raises(ValidationError):
        AnswerDecision(
            label="NOT_IN_DOCS",
            answer="NOT_IN_DOCS",
            citation_chunk_ids=(3,),
            reason="Absent labels cannot cite support.",
        )


def test_schema_rejection_is_typed_and_requires_final_errors():
    """Carry the final validation errors on a typed schema rejection."""
    rejection = SchemaRejected(errors=("label: Field required [missing]",))

    assert rejection.status == "schema_rejected"
    assert rejection.attempts == 2
    with pytest.raises(ValidationError):
        SchemaRejected(errors=())


def test_budget_refusal_rejects_negative_evidence():
    """Reject negative usage evidence on a budget refusal."""

    with pytest.raises(ValidationError):
        BudgetExceeded(
            which="input_tokens",
            used=-1,
            limit=10,
            attempts=1,
        )


def test_provider_metadata_keeps_final_raw_output_and_retry_count_consistent():
    """Keep the final raw output and the retry count consistent with each other."""
    values = metadata().model_dump()
    values.update(
        retries=1,
        raw_outputs=("invalid", "valid"),
        llm_output="valid",
    )
    result = ProviderMetadata.model_validate(values)

    assert result.retries == 1
    with pytest.raises(ValidationError):
        ProviderMetadata.model_validate({**values, "llm_output": "invalid"})
    with pytest.raises(ValidationError):
        ProviderMetadata.model_validate({**values, "provider": "   "})


def test_provider_result_requires_exactly_one_output_or_matching_refusal():
    """Carry exactly one output or one matching refusal, never both."""
    output = supported_decision()
    success = ProviderResult[AnswerDecision](
        status="ok",
        parsed=output,
        refusal=None,
        metadata=metadata(),
    )
    refusal = ProviderRefusal(
        status="provider_refused",
        message="The provider refused the request.",
        attempts=1,
    )

    assert success.parsed == output
    with pytest.raises(ValidationError):
        ProviderResult[AnswerDecision](
            status="provider_error",
            parsed=None,
            refusal=refusal,
            metadata=metadata(),
        )
    with pytest.raises(ValidationError):
        ProviderResult[AnswerDecision](
            status="ok",
            parsed=None,
            refusal=None,
            metadata=metadata(),
        )
