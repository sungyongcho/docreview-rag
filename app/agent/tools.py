"""Typed tool boundary shared by the agent loop and the MCP server."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import re
from typing import Any

from pydantic import BaseModel

from app.agent.types import AgentCitation

TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
RESERVED_TOOL_NAMES = frozenset({"final_answer"})

type EvidenceExtractor = Callable[[Any], tuple[AgentCitation, ...]]


def safe_runtime_error(error: Exception, action: str) -> str:
    """Return a stable public error without copying exception detail or secrets.

    Parameters
    ----------
    error : Exception
        Caught failure whose message may embed credentials or provider payloads.
    action : str
        Short description of the boundary that failed.

    Returns
    -------
    str
        Exception type name and the failed action, with no message text.

    Notes
    -----
    Every surface that reports a caught failure to a model or an MCP client shares
    this projection, so redaction cannot drift between the loop and the server.
    """
    return f"{type(error).__name__}: {action} failed"


@dataclass(frozen=True, slots=True)
class Tool[ParamsT: BaseModel]:
    """One callable capability with a validated parameter schema.

    ``run`` receives the already-validated parameters model and returns any
    JSON-serializable payload. ``evidence_ids`` optionally extracts complete
    immutable chunk identities, so the loop validates more than a forgeable id.
    """

    name: str
    description: str
    parameters: type[ParamsT]
    run: Callable[[ParamsT], Awaitable[Any]]
    evidence_ids: EvidenceExtractor | None = None

    def __post_init__(self) -> None:
        """Reject tools whose identity or schema cannot be published."""
        if TOOL_NAME.fullmatch(self.name) is None:
            raise ValueError("tool name must be snake_case ascii")
        if self.name in RESERVED_TOOL_NAMES:
            raise ValueError(f"tool name {self.name!r} is reserved for the agent loop")
        if not self.description.strip():
            raise ValueError("tool description must not be blank")
        if not isinstance(self.parameters, type) or not issubclass(self.parameters, BaseModel):
            raise ValueError("tool parameters must be a Pydantic model class")
