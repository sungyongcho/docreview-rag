import time

from arq.connections import RedisSettings
from sqlalchemy import update

from app.config import get_settings
from app.db.models import Run, Trace
from app.db.session import Session
from app.llm.provider import get_provider
from app.observability.cost import est_cost_usd
from app.retrieval.embeddings import get_embedder
from app.retrieval.rerank import Reranker
from app.workflow.graph import build_graph


async def startup(ctx):
    settings = get_settings()
    ctx["embedder"] = get_embedder(settings)
    ctx["reranker"] = Reranker(settings.rerank_model)
    # ctx["provider"] = get_provider(settings)


async def review_job(ctx, run_id: str, claim: str):
    settings = get_settings()
    provider = get_provider(settings)
    async with Session() as session:
        await session.execute(
            update(Run).where(Run.id == run_id).values(status="running")
        )
        await session.commit()
        node_path, report, error = [], None, None
        t0 = time.perf_counter()
        try:
            graph = build_graph(
                session, ctx["embedder"], ctx["reranker"], provider
            )
            initial = {
                "claim": claim,
                "query": claim,
                "evidence": [],
                "graded_sufficient": None,
                "report": None,
                "error": None,
                "retries": 0,
                "retrieve_attempts": 0,
            }
            async for chunk in graph.astream(initial):
                for node, upd in chunk.items():
                    node_path.append(node)
                    if upd and upd.get("report"):
                        report = upd["report"]
            await session.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(
                    status="done",
                    node_path=node_path,
                    report=report.model_dump() if report else None,
                )
            )
        except Exception as e:
            error = str(e)
            await session.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(status="failed", error=error)
            )

        latency_ms = int((time.perf_counter() - t0) * 1000)
        session.add(
            Trace(
                run_id=run_id,
                model_name=provider.model_name,
                prompt_version=settings.prompt_version,
                latency_ms=latency_ms,
                input_tokens=provider.input_tokens,
                output_tokens=provider.output_tokens,
                est_cost_usd=est_cost_usd(
                    provider.model_name, provider.input_tokens, provider.output_tokens
                ),
                tool_sequence=node_path,
                error=error,
            )
        )
        await session.commit()


class WorkerSettings:
    functions = [review_job]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
