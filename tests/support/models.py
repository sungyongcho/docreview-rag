"""Stand-ins for the models the agent paths call: chat models, tool providers and OpenAI.

Each stand-in replays a script, records every request before answering it, and can
fail a chosen request instead, so a test can tell what was sent from what came back:

- :class:`ScriptedToolProvider` answers ``run_agent``'s provider boundary with
  :func:`turn` values;
- :class:`ScriptedChatModel` answers LangChain and LangGraph with ``AIMessage`` replies;
- :class:`FakeOpenAIClient` stands in for the OpenAI SDK client the tool provider
  receives, and :class:`OpenAIClientFactory` for the SDK class a component builds itself;
- :class:`FakeOpenAIEndpoint` serves the OpenAI HTTP API to the real SDK, for code
  whose behaviour depends on the SDK's own request handling;
- :class:`CountingEmbeddings` is an embedding model that counts its requests.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
from types import SimpleNamespace
from typing import Any, Self, override

import httpx2
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
import openai
from pydantic import Field

from app.agent.provider import DeterministicToolProvider, ProviderTurn
from app.retrieval.embedding.provider import DeterministicEmbeddingProvider


def turn(**changes: Any) -> ProviderTurn:
    """Build one provider turn with optional field replacements."""
    values: dict[str, Any] = {
        "output_text": "",
        "tool_calls": (),
        "input_tokens": 10,
        "output_tokens": 5,
    }
    values.update(changes)
    return ProviderTurn(**values)


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """One request a scripted tool provider received, snapshotted when it arrived."""

    instructions: str
    input_items: tuple[dict[str, Any], ...]
    tools: tuple[dict[str, Any], ...]


class ScriptedToolProvider(DeterministicToolProvider):
    """Offline tool-calling provider that replays turns and records every request.

    It keeps the production deterministic provider's identity and zero pricing and
    adds what tests observe: ``requests`` holds every request in arrival order, copied
    before the loop can compact a later exchange, and ``failures`` maps a 1-based
    request number to an exception raised instead of the next turn, standing in for a
    provider error or an application budget refusal at that request.
    """

    def __init__(
        self,
        turns: Sequence[ProviderTurn] = (),
        *,
        failures: Mapping[int, BaseException] | None = None,
    ) -> None:
        super().__init__(turns)
        self.failures = dict(failures or {})
        self.requests: list[ProviderRequest] = []

    @override
    async def turn(
        self,
        instructions: str,
        input_items: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        *,
        max_output_tokens: int,
    ) -> ProviderTurn:
        """Record the request, then raise its scripted failure or return the next turn."""
        self.requests.append(
            ProviderRequest(instructions, tuple(dict(item) for item in input_items), tuple(tools))
        )
        failure = self.failures.get(len(self.requests))
        if failure is not None:
            raise failure
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


OPENAI_BASE_URL = "https://api.openai.com/v1"


class ScriptedResponses:
    """The ``responses`` endpoint of :class:`FakeOpenAIClient`.

    ``calls`` holds the keyword arguments of every ``create`` call in order;
    ``failures`` maps a 1-based call number to an exception raised instead of a reply.
    """

    def __init__(
        self, replies: Sequence[object], failures: Mapping[int, BaseException] | None
    ) -> None:
        self.replies = list(replies)
        self.failures = dict(failures or {})
        self.calls: list[dict[str, Any]] = []

    async def create(self, **request: Any) -> object:
        """Record the request, then raise its scripted failure or return the next reply."""
        self.calls.append(request)
        failure = self.failures.get(len(self.calls))
        if failure is not None:
            raise failure
        return self.replies.pop(0)


class FakeOpenAIClient:
    """OpenAI SDK client stand-in whose Responses endpoint replays scripted replies.

    Replies are objects shaped like SDK responses (attribute access only, as the
    adapters read them). ``close_count`` shows whether its owner released it.
    """

    def __init__(
        self,
        *replies: object,
        failures: Mapping[int, BaseException] | None = None,
        base_url: str = OPENAI_BASE_URL,
    ) -> None:
        self.base_url = base_url
        self.responses = ScriptedResponses(replies, failures)
        self.close_count = 0

    async def close(self) -> None:
        """Count one release of the client's connection pool."""
        self.close_count += 1

    async def __aenter__(self) -> Self:
        """Enter the client as ``async with AsyncOpenAI(...)`` does."""
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Close the client on exit, as the SDK does."""
        await self.close()


class OpenAIClientFactory:
    """Stand-in for the ``AsyncOpenAI`` class, for code that builds its own client.

    Patch it over the class the code under test constructs. Every construction
    records its keyword arguments in ``constructed`` and returns a new
    :class:`FakeOpenAIClient` with this factory's script, kept in ``clients``.
    """

    def __init__(
        self, *replies: object, failures: Mapping[int, BaseException] | None = None
    ) -> None:
        self.replies = replies
        self.failures = failures
        self.constructed: list[dict[str, Any]] = []
        self.clients: list[FakeOpenAIClient] = []

    def __call__(self, **options: Any) -> FakeOpenAIClient:
        """Record the constructor arguments and hand out a scripted client."""
        self.constructed.append(options)
        client = FakeOpenAIClient(*self.replies, failures=self.failures)
        self.clients.append(client)
        return client


def response_with_usage(input_tokens: int, output_tokens: int, **fields: object) -> object:
    """An SDK-shaped Responses reply with no output and the given token usage."""
    values: dict[str, object] = {"id": "resp-1", "status": "completed", "output_text": ""}
    values.update(fields)
    return SimpleNamespace(
        output=(),
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        **values,
    )


COUNT_PATH = "/v1/responses/input_tokens"
RESPONSES_PATH = "/v1/responses"
EMBEDDINGS_PATH = "/v1/embeddings"
EMBEDDING_DIMENSIONS = 384


class FakeOpenAIEndpoint:
    """Serve the OpenAI HTTP API to the real SDK and record every request body.

    Input-token counts answer from ``counts``, Responses from ``replies`` and
    embeddings with a unit vector billing the next of ``embedding_tokens`` (one token
    once they run out). ``failures`` maps ``(path, n)``, the n-th request to a path,
    to an HTTP response or an exception raised in place of the scripted answer. Every
    request must carry ``api_key`` as its bearer token.
    """

    def __init__(
        self,
        *,
        api_key: str,
        counts: Sequence[int] = (),
        replies: Sequence[dict[str, Any]] = (),
        embedding_tokens: Sequence[int] = (),
        failures: Mapping[tuple[str, int], httpx2.Response | Exception] | None = None,
    ) -> None:
        self.api_key = api_key
        self.counts = list(counts)
        self.replies = list(replies)
        self.embedding_tokens = list(embedding_tokens)
        self.failures = dict(failures or {})
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        """Record the request, then fail it or answer it from the script."""
        path = request.url.path
        assert request.headers["authorization"] == f"Bearer {self.api_key}"
        self.requests.append((path, json.loads(request.content)))
        failure = self.failures.get((path, len(self.bodies(path))))
        if isinstance(failure, Exception):
            raise failure
        if failure is not None:
            return failure
        if path == COUNT_PATH:
            tokens = self.counts.pop(0)
            return httpx2.Response(
                200, json={"object": "response.input_tokens", "input_tokens": tokens}
            )
        if path == EMBEDDINGS_PATH:
            tokens = self.embedding_tokens.pop(0) if self.embedding_tokens else 1
            return httpx2.Response(
                200,
                json={
                    "object": "list",
                    "model": "text-embedding-3-large",
                    "data": [
                        {
                            "object": "embedding",
                            "index": 0,
                            "embedding": [1.0] * EMBEDDING_DIMENSIONS,
                        }
                    ],
                    "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
                },
            )
        assert path == RESPONSES_PATH
        return httpx2.Response(200, json=self.replies.pop(0))

    def bodies(self, path: str) -> list[dict[str, Any]]:
        """Bodies sent to one endpoint, in order."""
        return [body for sent, body in self.requests if sent == path]

    def client(self) -> openai.DefaultAsyncHttpxClient:
        """An SDK HTTP client whose transport is this endpoint."""
        return openai.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(self))

    def sdk(self) -> openai.AsyncOpenAI:
        """A real SDK client, with retries off, that talks only to this endpoint."""
        return openai.AsyncOpenAI(api_key=self.api_key, max_retries=0, http_client=self.client())


class CountingEmbeddings(DeterministicEmbeddingProvider):
    """Embedding model that returns constant vectors and counts every request."""

    def __init__(self, dimensions: int = 4) -> None:
        self.dimensions = dimensions
        self.query_calls = 0
        self.document_calls = 0

    @override
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one constant vector per text, counting the batch."""
        self.document_calls += 1
        return [[0.0] * self.dimensions for _ in texts]

    @override
    async def embed_query(self, text: str) -> list[float]:
        """Return one constant vector, counting the call."""
        del text
        self.query_calls += 1
        return [0.0] * self.dimensions
