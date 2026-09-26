"""Provider results adapted into strict observability traces."""

from decimal import Decimal
import json

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
        "requests": 2,
        "request_ids": ("req_1", "req_2"),
        "llm_output": "not json",
        "raw_outputs": ("{}", "not json"),
    }
    values.update(overrides)
    return ProviderMetadata(**values)


def test_provider_results_map_to_traces_with_canonical_refusal_json_or_no_error():
    """Copy provider metadata into the trace, with canonical refusal JSON or no error."""
    refused = step_trace_from_provider_result(
        ProviderResult[AnswerDecision](
            status="schema_rejected",
            parsed=None,
            refusal=SchemaRejected(errors=("label is required",)),
            metadata=provider_metadata(),
        ),
        step=1,
        node="grade",
    )

    assert refused.llm_output == "not json"
    assert refused.input_tokens == 11
    assert refused.output_tokens == 3
    assert refused.retries == 1
    # The provider already charged this against its budget; the trace copies it.
    assert refused.estimated_cost_usd == Decimal("0.0000092")
    assert refused.error is not None
    assert json.loads(refused.error) == {
        "status": "schema_rejected",
        "refusal": {
            "status": "schema_rejected",
            "attempts": 2,
            "errors": ["label is required"],
        },
    }

    succeeded = step_trace_from_provider_result(
        ProviderResult[AnswerDecision](
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
                requests=1,
                request_ids=("req_1",),
                llm_output="{}",
                raw_outputs=("{}",),
            ),
        ),
        step=2,
        node="check",
    )

    assert succeeded.error is None
    assert succeeded.step == 2
    assert succeeded.node == "check"
