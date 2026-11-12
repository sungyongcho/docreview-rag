"""Builders shared by the agent tests."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast, override

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.provider import DeterministicToolProvider, ProviderTurn


def turn(**changes):
    """Build one provider turn with optional field replacements."""
    values = {
        "output_text": "",
        "tool_calls": (),
        "input_tokens": 10,
        "output_tokens": 5,
    }
    values.update(changes)
    return ProviderTurn(**values)


class FakeSession:
    """Duck-typed async session capturing chunk lookups and its own lifecycle."""

    def __init__(self, chunk=None):
        self.chunk = chunk
        self.requested_ids = []
        self.transaction_open = False
        self.rollback_count = 0
        self.closed = False

    async def __aenter__(self):
        """Enter the session context the way an AsyncSession does."""
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Roll back any open read transaction and close, mirroring AsyncSession."""
        if self.transaction_open:
            await self.rollback()
        self.closed = True

    async def get(self, model, chunk_id):
        """Record the requested chunk id and return the staged row."""
        del model
        self.requested_ids.append(chunk_id)
        self.transaction_open = True
        return self.chunk

    async def scalars(self, statement):
        """Answer the current-evidence check: the staged chunk is current evidence."""
        del statement
        self.transaction_open = True
        return [] if self.chunk is None else [self.chunk.id]

    def in_transaction(self):
        """Report whether this fake session currently holds a transaction."""
        return self.transaction_open

    async def rollback(self):
        """Close the transaction and count the rollback."""
        self.transaction_open = False
        self.rollback_count += 1


class FakeSessionFactory:
    """Session factory recording every session it hands out."""

    def __init__(self, chunk=None):
        self.chunk = chunk
        self.sessions = []

    def __call__(self) -> AsyncSession:
        """Produce one fresh fake session per call, the way a sessionmaker does."""
        session = FakeSession(self.chunk)
        self.sessions.append(session)
        # The duck-typed fake stands in for the AsyncSession a SessionFactory returns.
        return cast(AsyncSession, session)


class RecordingToolProvider(DeterministicToolProvider):
    """Observe requests at the provider boundary without production recording state."""

    def __init__(self, turns):
        super().__init__(turns)
        self.requests = []

    async def turn(self, instructions, input_items, tools, *, max_output_tokens):
        """Snapshot replay items before the loop can compact a later exchange."""
        self.requests.append(
            (instructions, tuple(dict(item) for item in input_items), tuple(tools))
        )
        return await super().turn(
            instructions, input_items, tools, max_output_tokens=max_output_tokens
        )


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """One request a scripted chat model received: its messages and bound options."""

    messages: list[BaseMessage]
    kwargs: dict[str, Any]


class ScriptedChatModel(GenericFakeChatModel):
    """Network-free LangChain chat model that replays scripted replies.

    Every request is recorded before it is answered, so ``requests`` counts what
    was actually sent. ``failures`` maps a 1-based request number to an exception
    raised instead of a reply, standing in for a request whose outcome is unknown.
    """

    requests: list[ModelRequest] = Field(default_factory=list)
    failures: dict[int, Exception] = Field(default_factory=dict)

    @classmethod
    def from_replies(
        cls, *replies: AIMessage, failures: dict[int, Exception] | None = None
    ) -> ScriptedChatModel:
        """Build a model that answers with ``replies`` in order."""
        return cls(messages=iter(replies), failures=failures or {})

    @override
    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        """Send tool schemas with each request like a real model; replies stay scripted."""
        del tool_choice
        return self.bind(tools=[convert_to_openai_tool(tool) for tool in tools], **kwargs)

    @override
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Record the request, then raise its scripted failure or return the next reply."""
        self.requests.append(ModelRequest(list(messages), dict(kwargs)))
        failure = self.failures.get(len(self.requests))
        if failure is not None:
            raise failure
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
