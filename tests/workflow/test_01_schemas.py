"""M4 strict structured-output, budget, refusal, and result schema tests."""

from decimal import Decimal

from pydantic import ValidationError
import pytest

from tests.support import need


def metadata(W):
    return W.ProviderMetadata(
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


def supported_decision(W):
    return W.AnswerDecision(
        label="SUPPORTED",
        answer="Research expense increased.",
        citation_chunk_ids=(7,),
        reason="The cited chunk contains the statement.",
    )


def test_prompt_is_strict_frozen_and_forbids_unknown_fields(W):
    need(W, "Prompt")
    prompt = W.Prompt(system="Return structured evidence.", user="What changed?")

    with pytest.raises(ValidationError):
        W.Prompt(system="Return structured evidence.", user=7)
    with pytest.raises(ValidationError):
        W.Prompt(system="Return structured evidence.", user="What changed?", extra=True)
    with pytest.raises(ValidationError):
        prompt.user = "mutated"


@pytest.mark.parametrize("field", ["system", "user"])
def test_prompt_rejects_whitespace_only_text(W, field):
    need(W, "Prompt")
    values = {"system": "system", "user": "user"}
    values[field] = "   "

    with pytest.raises(ValidationError):
        W.Prompt(**values)


def test_token_pricing_uses_exact_decimal_arithmetic(W):
    need(W, "TokenPricing")
    pricing = W.TokenPricing(
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
def test_provider_budget_requires_explicit_strict_limits_and_pricing(W, changes, expected_error):
    need(W, "ProviderBudget", "TokenPricing")
    values = {
        "max_input_tokens": 1_000,
        "max_output_tokens": 100,
        "max_cost_usd": Decimal("0.10"),
        "pricing": W.TokenPricing(
            input_per_million_usd=Decimal("0"),
            output_per_million_usd=Decimal("0"),
        ),
    }
    values.update(changes)

    with pytest.raises(expected_error):
        W.ProviderBudget(**values)


def test_relevance_judgment_rejects_coercion_and_duplicate_chunks(W):
    need(W, "ChunkRelevance", "RelevanceJudgment")
    with pytest.raises(ValidationError):
        W.ChunkRelevance(chunk_id=1, relevant=1, reason="Relevant")

    grade = W.ChunkRelevance(chunk_id=1, relevant=True, reason="Exact evidence")
    with pytest.raises(ValidationError):
        W.RelevanceJudgment(grades=(grade, grade))


def test_supported_decision_requires_unique_citations_and_non_absent_answer(W):
    need(W, "AnswerDecision")
    decision = supported_decision(W)

    assert decision.label == "SUPPORTED"
    with pytest.raises(ValidationError):
        W.AnswerDecision(
            label="SUPPORTED",
            answer="Supported.",
            citation_chunk_ids=(),
            reason="No citation was supplied.",
        )
    with pytest.raises(ValidationError):
        W.AnswerDecision(
            label="SUPPORTED",
            answer="Supported.",
            citation_chunk_ids=(2, 2),
            reason="Duplicate citation.",
        )


def test_not_in_docs_decision_requires_literal_answer_and_no_citations(W):
    need(W, "AnswerDecision")
    decision = W.AnswerDecision(
        label="NOT_IN_DOCS",
        answer="NOT_IN_DOCS",
        citation_chunk_ids=(),
        reason="The retrieved evidence does not support the claim.",
    )

    assert decision.citation_chunk_ids == ()
    with pytest.raises(ValidationError):
        W.AnswerDecision(
            label="NOT_IN_DOCS",
            answer="Maybe absent.",
            citation_chunk_ids=(),
            reason="Ambiguous answer.",
        )
    with pytest.raises(ValidationError):
        W.AnswerDecision(
            label="NOT_IN_DOCS",
            answer="NOT_IN_DOCS",
            citation_chunk_ids=(3,),
            reason="Absent labels cannot cite support.",
        )


def test_schema_rejection_is_typed_and_requires_final_errors(W):
    need(W, "SchemaRejected")
    rejection = W.SchemaRejected(errors=("label: Field required [missing]",))

    assert rejection.status == "schema_rejected"
    assert rejection.attempts == 2
    with pytest.raises(ValidationError):
        W.SchemaRejected(errors=())


def test_budget_refusal_rejects_negative_evidence(W):
    need(W, "BudgetExceeded")

    with pytest.raises(ValidationError):
        W.BudgetExceeded(
            which="input_tokens",
            used=-1,
            limit=10,
            attempts=1,
        )


def test_provider_metadata_keeps_final_raw_output_and_retry_count_consistent(W):
    need(W, "ProviderMetadata")
    values = metadata(W).model_dump()
    values.update(
        retries=1,
        raw_outputs=("invalid", "valid"),
        llm_output="valid",
    )
    result = W.ProviderMetadata.model_validate(values)

    assert result.retries == 1
    with pytest.raises(ValidationError):
        W.ProviderMetadata.model_validate({**values, "llm_output": "invalid"})
    with pytest.raises(ValidationError):
        W.ProviderMetadata.model_validate({**values, "provider": "   "})


def test_provider_result_requires_exactly_one_output_or_matching_refusal(W):
    need(W, "ProviderResult", "ProviderRefusal")
    output = supported_decision(W)
    success = W.ProviderResult[W.AnswerDecision](
        status="ok",
        parsed=output,
        refusal=None,
        metadata=metadata(W),
    )
    refusal = W.ProviderRefusal(
        status="provider_refused",
        message="The provider refused the request.",
        attempts=1,
    )

    assert success.parsed == output
    with pytest.raises(ValidationError):
        W.ProviderResult[W.AnswerDecision](
            status="provider_error",
            parsed=None,
            refusal=refusal,
            metadata=metadata(W),
        )
    with pytest.raises(ValidationError):
        W.ProviderResult[W.AnswerDecision](
            status="ok",
            parsed=None,
            refusal=None,
            metadata=metadata(W),
        )
