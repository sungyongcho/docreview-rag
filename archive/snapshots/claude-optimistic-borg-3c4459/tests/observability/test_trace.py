"""Provider results adapted into strict observability traces."""

from decimal import Decimal

from app.llm.schemas import AnswerDecision, ProviderMetadata, ProviderResult, SchemaRejected
from app.observability.trace import step_trace_from_provider_result


def provider_metadata(**overrides):
    """Build one trace-ready provider metadata value with optional replacements."""
    values = {
        "provider": "openai",
        "model_name": "gpt-4.1-mini",
        "api_url": "https://api.openai.com/v1/responses",
        "input_tokens": 11,
        "output_tokens": 3,
        "estimated_cost_usd": Decimal("0.0000092"),
        "request_time_ms": 4.5,
        "retries": 1,
        "request_ids": ("req_1", "req_2"),
        "llm_output": "not json",
        "raw_outputs": ("{}", "not json"),
    }
    values.update(overrides)
    return ProviderMetadata(**values)


def test_provider_refusal_mapping_keeps_trace_metadata_and_typed_reason():
    """Map a provider refusal into a trace without losing its typed reason."""
    result = ProviderResult[AnswerDecision](
        status="schema_rejected",
        parsed=None,
        refusal=SchemaRejected(errors=("label is required",)),
        metadata=provider_metadata(),
    )

    trace = step_trace_from_provider_result(result, step=1, node="grade")

    assert trace.llm_output == "not json"
    assert trace.input_tokens == 11
    assert trace.output_tokens == 3
    assert trace.retries == 1
    # The provider already charged this against its budget; the trace copies it.
    assert trace.estimated_cost_usd == Decimal("0.0000092")
    assert trace.error == (
        '{"refusal":{"attempts":2,"errors":["label is required"],'
        '"status":"schema_rejected"},"status":"schema_rejected"}'
    )


def test_successful_provider_result_records_no_error():
    """Leave the trace error empty when the provider returned parsed output."""
    result = ProviderResult[AnswerDecision](
        status="ok",
        parsed=AnswerDecision(
            label="NOT_IN_DOCS",
            answer="NOT_IN_DOCS",
            citation_chunk_ids=(),
            reason="The filing does not discuss it.",
        ),
        refusal=None,
        metadata=provider_metadata(
            retries=0,
            request_ids=("req_1",),
            llm_output="{}",
            raw_outputs=("{}",),
        ),
    )

    trace = step_trace_from_provider_result(result, step=2, node="check")

    assert trace.error is None
    assert trace.step == 2
    assert trace.node == "check"
