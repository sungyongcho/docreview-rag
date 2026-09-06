"""Public contracts and production entry points for the agent milestone."""

from app.agent.builtin_tools import build_default_registry
from app.agent.decompose import (
    QueryDecomposition,
    decompose_query,
    make_decomposed_retriever,
    merge_ranked_lists,
)
from app.agent.eval import category_metrics, run_decomposition_comparison
from app.agent.loop import FINAL_ANSWER_NAME, build_instructions, final_answer_spec, run_agent
from app.agent.mcp_server import build_mcp_server, serve_stdio
from app.agent.provider import (
    DeterministicToolProvider,
    OpenAIToolProvider,
    ProviderTurn,
    ToolCallingProvider,
)
from app.agent.registry import ToolRegistry
from app.agent.tools import Tool
from app.agent.types import (
    AgentAnswer,
    AgentBudget,
    AgentCitation,
    AgentResult,
    AgentStep,
    Observation,
    StepUsage,
    ToolCall,
)

__all__ = [
    "FINAL_ANSWER_NAME",
    "AgentAnswer",
    "AgentBudget",
    "AgentCitation",
    "AgentResult",
    "AgentStep",
    "DeterministicToolProvider",
    "Observation",
    "OpenAIToolProvider",
    "ProviderTurn",
    "QueryDecomposition",
    "StepUsage",
    "Tool",
    "ToolCall",
    "ToolCallingProvider",
    "ToolRegistry",
    "build_default_registry",
    "build_instructions",
    "build_mcp_server",
    "category_metrics",
    "decompose_query",
    "final_answer_spec",
    "make_decomposed_retriever",
    "merge_ranked_lists",
    "run_agent",
    "run_decomposition_comparison",
    "serve_stdio",
]
