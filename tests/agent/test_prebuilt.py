"""How the review agent's builder classifies the way one question ended."""

import asyncio

import httpx2
from langchain_core.messages import AIMessage, HumanMessage
import openai
import pytest

from app.agent.prebuilt import ask_review_agent, build_review_agent, unanswered
from app.agent.provider import BudgetExhaustedError
from app.agent.review_middleware import ReviewContext
from app.tools.registry import ToolRegistry
from tests.support.models import ScriptedChatModel

QUESTION = "What was revenue?"


class CountError(RuntimeError):
    """A failure of the caller's own model wrapper."""


def ask(model: ScriptedChatModel, **options):
    """Ask one question of a tool-less review agent built on ``model``."""
    agent = build_review_agent(model, [], ToolRegistry())
    return asyncio.run(
        ask_review_agent(agent, QUESTION, ReviewContext((2024,), locale="en"), **options)
    )


def incomplete(reason: str | None) -> AIMessage:
    """Return a reply the provider cut off for ``reason``."""
    details = None if reason is None else {"reason": reason}
    return AIMessage(
        content="", response_metadata={"status": "incomplete", "incomplete_details": details}
    )


@pytest.mark.parametrize(
    ("messages", "status", "text"),
    [
        ([HumanMessage(QUESTION)], "no_answer", "without a model reply"),
        ([AIMessage(content="Revenue rose.")], "no_answer", "without a valid final_answer"),
        ([incomplete("max_output_tokens")], "budget_exceeded", "output-token ceiling"),
        ([incomplete(None)], "budget_exceeded", "output-token ceiling"),
        ([incomplete("content_filter")], "provider_error", "content_filter"),
    ],
)
def test_unanswered_reads_the_last_model_reply(messages, status, text):
    """A run without an answer is classified by how its last model turn ended."""
    found, failure = unanswered(messages)

    assert found == status
    assert text in failure


def test_text_only_reply_ends_as_no_answer():
    """A model that answers in prose instead of final_answer leaves no accepted answer."""
    outcome = ask(ScriptedChatModel.from_replies(AIMessage(content="Revenue rose.")))

    assert (outcome.status, outcome.answer) == ("no_answer", None)
    assert outcome.failure is not None and "final_answer" in outcome.failure


def test_budget_failure_keeps_its_message():
    """An exhausted budget is reported with the text the budget wrote."""
    model = ScriptedChatModel.from_replies(
        failures={1: BudgetExhaustedError("model budget of 1 turn is spent")}
    )

    outcome = ask(model)

    assert (outcome.status, outcome.failure) == (
        "budget_exceeded",
        "model budget of 1 turn is spent",
    )


def test_provider_failure_is_reported_without_its_message():
    """A provider error names its type only, so no provider payload reaches the report."""
    error = openai.APIConnectionError(
        message="secret-bearing detail", request=httpx2.Request("POST", "https://api.invalid")
    )

    outcome = ask(ScriptedChatModel.from_replies(failures={1: error}))

    assert outcome.status == "provider_error"
    assert outcome.failure is not None and "secret-bearing" not in outcome.failure
    assert "APIConnectionError" in outcome.failure


def test_any_other_failure_is_a_redacted_tool_error():
    """An unexpected exception still ends the question with a reason, minus its message."""
    outcome = ask(ScriptedChatModel.from_replies(failures={1: KeyError("private detail")}))

    assert outcome.status == "tool_error"
    assert outcome.failure is not None and "private detail" not in outcome.failure
    assert "KeyError" in outcome.failure


def test_propagated_failure_types_reach_the_caller():
    """A caller that reports its own wrapper's failure receives the exception itself."""
    model = ScriptedChatModel.from_replies(failures={1: CountError("count refused")})

    with pytest.raises(CountError, match="count refused"):
        ask(model, propagate=(CountError,))

    assert ask(ScriptedChatModel.from_replies(failures={1: CountError("x")})).status == (
        "tool_error"
    )
