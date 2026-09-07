"""Secret-safe record mapping and transaction-neutral run persistence."""

import asyncio
from decimal import Decimal
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, Trace
from app.observability.persistence import (
    REDACTED,
    persist_run_report,
    records_to_report,
    redact_sensitive_text,
    report_to_records,
)
from tests.observability.support import run_report, step_trace


def test_record_mapping_round_trips_every_field():
    """Rebuild the exact report from its records, so no column can be dropped one-way."""
    report = run_report(steps=[step_trace(), step_trace(step=2, node="check")])

    run, traces = report_to_records(report)
    rebuilt = records_to_report(run, traces)

    assert rebuilt == report


def test_persistence_mapping_preserves_provenance_and_redacts_secrets():
    """Preserve run provenance while redacting secrets on the way to storage."""
    secret = "sk-test-secret-123456"
    report = run_report(
        status="schema_rejected",
        system_prompt=f"Use evidence. API_KEY={secret}",
        report={"reason": f"provider rejected Bearer {secret}"},
        steps=[
            step_trace(
                api_url=f"https://example.test/responses?api_key={secret}",
                llm_output=f'{{"raw":"{secret}","kept":"evidence"}}',
                error=f"Authorization: Bearer {secret}",
            )
        ],
    )

    run, traces = report_to_records(report, secret_values=[secret])

    trace = traces[0]
    assert run.run_id == report.run_id
    assert run.status == "schema_rejected"
    assert run.node_path == ["retrieve", "grade"]
    assert "Use evidence." in run.system_prompt
    assert "evidence" in trace.llm_output
    assert secret not in run.system_prompt
    assert secret not in repr(run.report)
    assert secret not in trace.api_url
    assert secret not in trace.llm_output
    assert trace.error is not None and secret not in trace.error
    assert REDACTED in run.system_prompt
    assert REDACTED in trace.llm_output


def test_redaction_covers_quoted_assignments_and_rejects_key_collisions():
    """Redact quoted secret assignments and reject colliding redaction keys."""

    assert redact_sensitive_text('password="alpha beta"') == "password=[REDACTED]"
    assert redact_sensitive_text("secret='alpha beta'") == "secret=[REDACTED]"
    assert (
        redact_sensitive_text(
            "pair abcdef123 abcdef",
            secret_values=["abcdef", "abcdef123"],
        )
        == "pair [REDACTED] [REDACTED]"
    )

    collision = run_report(report={"api_key=foo": "first", "api_key=bar": "second"})
    with pytest.raises(ValueError, match="duplicate JSON key"):
        report_to_records(collision)


def test_redaction_reaches_json_credentials_and_stops_at_the_query_boundary():
    """Redact secrets written as JSON and keep the rest of a URL readable."""

    assert redact_sensitive_text('{"access_token": "abc123def"}') == '{"access_token": [REDACTED]}'
    assert redact_sensitive_text("{'password': 'hunter2'}") == "{'password': [REDACTED]}"
    assert (
        redact_sensitive_text('headers={"Authorization": "Basic YWxpY2U6c2VjcmV0"}')
        == 'headers={"Authorization": [REDACTED]}'
    )
    # An authorization header is one value, not a scheme plus a separate secret.
    assert redact_sensitive_text("Authorization: Bearer abc.def-ghi") == "Authorization: [REDACTED]"
    assert (
        redact_sensitive_text("https://api.test/v1/responses?api_key=sk-abcdefgh12&model=mini")
        == "https://api.test/v1/responses?api_key=[REDACTED]&model=mini"
    )
    # Open DART names its credential `crtfc_key`, which no other pattern here matches.
    assert (
        redact_sensitive_text(
            "https://opendart.fss.or.kr/api/list.json?crtfc_key=abc123&corp_code=x"
        )
        == "https://opendart.fss.or.kr/api/list.json?crtfc_key=[REDACTED]&corp_code=x"
    )


def test_credential_keys_in_a_report_have_their_values_replaced_wholesale():
    """Replace whatever a credential-shaped report key holds, not just matching text."""
    report = run_report(
        report={
            "openai_api_key": "abc123def",
            "nested": {"password": "hunter2", "label": "SUPPORTED"},
        }
    )

    run, _ = report_to_records(report)

    assert run.report == {
        "openai_api_key": REDACTED,
        "nested": {"password": REDACTED, "label": "SUPPORTED"},
    }


def test_equal_length_secrets_redact_in_one_stable_pass():
    """Replace every explicit secret in one pass, independent of the order supplied."""
    # "REDACT" occurs inside the replacement text, so a second sequential replacement
    # would rewrite what the first one produced.
    secrets = ["ABCDEF", "REDACT"]

    assert redact_sensitive_text("ABCDEF", secret_values=secrets) == REDACTED
    assert redact_sensitive_text("ABCDEF", secret_values=list(reversed(secrets))) == REDACTED


def test_persistence_flushes_without_committing_or_live_services():
    """Flush a run report without committing or reaching any live service."""

    class RecordingSession:
        """Record what persistence adds and flushes, without a database."""

        def __init__(self):
            self.added = []
            self.added_many = []
            self.flushed = False

        def add(self, value):
            """Record one added instance."""
            self.added.append(value)

        def add_all(self, values):
            """Record a batch of added instances."""
            self.added_many.extend(values)

        async def flush(self):
            """Mark that the session was flushed."""
            self.flushed = True

    session = RecordingSession()
    persisted = asyncio.run(persist_run_report(cast(AsyncSession, session), run_report()))

    assert persisted is session.added[0]
    assert isinstance(persisted, Run)
    assert len(session.added_many) == 1
    assert isinstance(session.added_many[0], Trace)
    assert session.flushed


def test_local_timing_round_trips_through_existing_jsonb_context() -> None:
    """Preserve new optional timing fields without changing old trace rows or run context."""
    from app.llm.schemas import LocalModelTiming
    from app.observability.persistence import record_to_step

    timing = LocalModelTiming(attempt=2, load_duration_ms=1.5, eval_count=3)
    report = run_report(steps=[step_trace().model_copy(update={"local_timings": (timing,)})])
    run, traces = report_to_records(report)
    assert records_to_report(run, traces).steps[0].local_timings == (timing,)
    assert record_to_step(traces[0], request_context=run.request_context).local_timings == (timing,)
    assert record_to_step(traces[0]).local_timings == ()
    assert run.request_context["trace_local_timings"]["1"] == [
        {"attempt": 2, "load_duration_ms": 1.5, "eval_count": 3}
    ]


def test_sent_requests_round_trip_through_existing_jsonb_context() -> None:
    """A step refused before its call keeps zero requests through storage without a new column."""
    from app.observability.persistence import record_to_step, stored_step_requests

    refused = step_trace(
        step=2,
        requests=0,
        input_tokens=0,
        output_tokens=0,
        estimated_cost_usd=Decimal("0"),
        request_time_ms=0.0,
        llm_output="",
        error="input_tokens: used=0 limit=2000",
    )
    report = run_report(
        status="budget_exceeded",
        report={"reason": {"code": "budget_exceeded"}},
        steps=[step_trace(), refused],
    )
    run, traces = report_to_records(report)

    assert run.total_requests == 1
    context = run.request_context
    assert context is not None
    assert context["trace_requests"] == {"2": 0}
    restored = records_to_report(run, traces)
    assert [step.requests for step in restored.steps] == [1, 0]
    assert restored.total_requests == 1
    assert record_to_step(traces[1]).requests == 1
    assert stored_step_requests({"trace_requests": {"2": True}}, step=2, retries=0) == 1
    assert "trace_requests" not in (report_to_records(run_report())[0].request_context or {})
