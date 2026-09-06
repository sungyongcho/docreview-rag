from langgraph.graph import END, START, StateGraph

from app.llm.provider import LLMProvider
from app.llm.schemas import ClaimReport
from app.retrieval.embeddings import Embedder
from app.retrieval.rerank import Reranker
from app.workflow.nodes import (
    check_claim,
    grade_evidence,
    reformulate_query,
    retrieve_evidence,
)
from app.workflow.state import ReviewState

MAX_RETRIES = 2
MAX_RETRIEVE_ATTEMPTS = 2


def route_after_grade(state: ReviewState) -> str:
    if state["graded_sufficient"]:
        return "check"
    if state["retrieve_attempts"] < MAX_RETRIEVE_ATTEMPTS:
        return "reformulate"
    return "handle_missing"


def route_after_check(state: ReviewState) -> str:
    if state.get("error"):
        return "check" if state["retries"] < MAX_RETRIES else "handle_error"
    return END


def handle_missing_node(state: ReviewState) -> dict:
    return {
        "report": ClaimReport(
            label="NOT_IN_DOCS",
            citations=[],
            rationale="No relevant evidence retrieved.",
        )
    }


def handle_error_node(state: ReviewState) -> dict:
    return {
        "report": ClaimReport(
            label="NOT_IN_DOCS",
            citations=[],
            rationale=f"Provider failed after retries: {state['error']}",
        )
    }


def build_graph(session, embedder: Embedder, reranker: Reranker, provider: LLMProvider):
    async def retrieve_node(state: ReviewState) -> dict:
        evidence = await retrieve_evidence(session, state["query"], embedder, reranker)
        return {
            "evidence": evidence,
            "retrieve_attempts": state["retrieve_attempts"] + 1,
        }

    def grade_node(state: ReviewState) -> dict:
        return {
            "graded_sufficient": grade_evidence(
                state["claim"], state["evidence"], provider
            )
        }

    def reformulate_node(state: ReviewState) -> dict:
        return {"query": reformulate_query(state["claim"], provider)}

    def check_node(state: ReviewState) -> dict:
        try:
            report = check_claim(state["claim"], state["evidence"], provider)
            return {"report": report, "error": None}
        except Exception as e:
            return {"error": str(e), "retries": state["retries"] + 1}

    g = StateGraph(ReviewState)
    g.add_node("retrieve", retrieve_node)
    g.add_node("grade", grade_node)
    g.add_node("reformulate", reformulate_node)
    g.add_node("check", check_node)
    g.add_node("handle_missing", handle_missing_node)
    g.add_node("handle_error", handle_error_node)

    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", route_after_grade)
    g.add_edge("reformulate", "retrieve")
    g.add_conditional_edges("check", route_after_check)
    g.add_edge("handle_missing", END)
    g.add_edge("handle_error", END)

    return g.compile()


if __name__ == "__main__":
    import argparse
    import asyncio

    from app.config import get_settings
    from app.db.session import Session
    from app.llm.provider import get_provider
    from app.retrieval.embeddings import get_embedder

    async def main():
        p = argparse.ArgumentParser()
        p.add_argument("--claim", required=True)
        a = p.parse_args()

        settings = get_settings()
        embedder = get_embedder(settings)
        reranker = Reranker(settings.rerank_model)
        provider = get_provider(settings)

        async with Session() as session:
            graph = build_graph(session, embedder, reranker, provider)
            initial = {
                "claim": a.claim,
                "query": a.claim,
                "evidence": [],
                "graded_sufficient": None,
                "report": None,
                "error": None,
                "retries": 0,
                "retrieve_attempts": 0,
            }
            report = None
            print("--- node path ---")
            async for chunk in graph.astream(initial):
                for node, update in chunk.items():
                    print(f"  → {node}")
                    if update and update.get("report"):
                        report = update["report"]

        print(f"\nLABEL     : {report.label}")
        print(f"CITATIONS : {report.citations}")
        print(f"RATIONALE : {report.rationale}")

    asyncio.run(main())
