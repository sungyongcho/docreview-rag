# LLM / RAG / Agent Side Project

**Purpose:** create one public, recruiter-readable project that proves direct LLM/RAG/agent workflow ability without overstating commercial production experience.

This project exists to close the current screen gap for roles that ask for:

- LLM-backed product workflows
- RAG pipelines
- agent/tool execution
- eval harnesses
- observability-style logs
- FastAPI / PostgreSQL / Docker ownership

Gomoku remains the deeper AI systems proof. This project should provide the direct LLM/RAG/agent proof.

---

## Project Identity

```text
Repo: docreview-rag-agent
Project name: DocReview RAG Agent
Subtitle: A document-grounded LLM/RAG review workflow with citations, bounded tools, evals, and observability.
```

---

## Working Concept

Build a small **AI workflow review assistant** for structured documents.

The system ingests documents, indexes them, retrieves evidence, runs bounded checks, calls explicit tools, and produces a structured review report with citations and eval results.

This should not be a generic chatbot.

Good framing:

```text
An LLM workflow and evaluation platform for document-grounded review tasks.
```

Bad framing:

```text
A chatbot over PDFs.
```

---

## MVP User Story

As a technical reviewer, I can:

1. Upload or seed a small set of documents.
2. Ask a review question or run a predefined review checklist.
3. See retrieved evidence with citations.
4. See an LLM-generated structured report.
5. See tool calls, latency, retrieval stats, and evaluation results.
6. Re-run the evaluation suite and compare regressions.

---

## Non-Negotiable Scope

Backend:

- FastAPI service with typed request/response models.
- PostgreSQL with pgvector or equivalent vector search.
- Relational tables for documents, chunks, runs, tool calls, eval results, and logs.
- Async background worker for ingestion and/or review runs.
- Docker Compose for API, database, worker, and seed data.

RAG:

- Document parser.
- Chunking strategy with metadata.
- Embedding pipeline.
- Retrieval endpoint with deterministic top-k settings.
- Citation output with source document, chunk ID, and snippet.

Agent/tool workflow:

- At least one bounded agentic workflow.
- Explicit tools, not hidden magic.
- Use LangGraph for stateful workflow orchestration if it stays simple and inspectable.
- Keep retrieval, citations, storage, evals, and tool bodies implemented directly in plain Python.
- Tool examples:
  - retrieve evidence
  - check claim support
  - extract structured fields
  - compare answer against policy/checklist
  - create final report
- Retry and failure states.
- Guardrails for unsupported claims.

Evaluations:

- Golden question set.
- Retrieval precision / hit-rate checks.
- Answer quality checks with deterministic rubrics where possible.
- Regression report.
- At least one written failure analysis.

Observability-style logging:

- request ID
- run ID
- latency
- model name
- estimated tokens / cost
- retrieval top-k
- retrieval hit count
- tool call sequence
- error trace

Tests:

- ingestion tests
- retrieval tests
- agent/tool execution tests
- eval scoring tests
- API contract tests

Docs:

- Public README with architecture, setup, demo, tradeoffs, limitations, and screenshots or sample output.
- Architecture diagram is useful, but not required before the backend/evals are credible.

---

## Suggested Tech Stack

Primary:

- Python
- FastAPI
- Pydantic
- PostgreSQL
- pgvector
- SQLAlchemy or SQLModel
- Alembic
- Docker Compose
- pytest

LLM/RAG:

- OpenAI, Mistral, Anthropic, or another provider through a small provider abstraction.
- Core RAG should be implemented directly: parsing, chunking, embeddings, retrieval, citations, and evals.
- Use LangGraph for bounded workflow orchestration, not as a black-box replacement for the system.
- LangChain primitives are acceptable when needed by LangGraph, but the app should not become a generic LangChain demo.
- LlamaIndex is optional only if it clearly improves document parsing/indexing; do not add it just for keyword coverage.
- Keep provider calls, prompts, structured outputs, and error handling easy to inspect.

Recommended framework stance:

```text
The retrieval, storage, citation, and evaluation layers are implemented directly with FastAPI, PostgreSQL/pgvector, and pytest. LangGraph is used only for bounded review workflow orchestration, so the system remains inspectable and avoids hiding core RAG behavior behind framework abstractions.
```

High-leverage add-ons:

- Langfuse or a local Langfuse-style trace table for LLM observability, latency, token/cost tracking, and prompt/run inspection.
- Ragas or promptfoo only after baseline pytest-based evals exist.
- Hybrid search or reranking as a documented extension, not a blocker for MVP.
- MCP as a later extension if exposing tools/resources through a standard protocol becomes useful.

Frontend:

- Optional.
- If added, keep it simple: run list, document list, report view, logs view.
- Do not spend time on UI polish before backend, evals, and docs are finished.

---

## Repository Shape

```text
llm-rag-agent-workflow/
├── README.md
├── docker-compose.yml
├── .env.example
├── app/
│   ├── main.py
│   ├── api/
│   ├── core/
│   ├── db/
│   ├── ingestion/
│   ├── retrieval/
│   ├── agents/
│   ├── evals/
│   └── observability/
├── tests/
│   ├── test_ingestion.py
│   ├── test_retrieval.py
│   ├── test_agent_workflow.py
│   ├── test_evals.py
│   └── test_api_contracts.py
├── data/
│   ├── seed/
│   └── golden/
└── docs/
    ├── architecture.md
    ├── eval-report.md
    └── failure-analysis.md
```

---

## Demo Dataset

Use public or self-authored documents only.

Do not use:

- private job-search notes
- private resumes
- private company data
- personal emails
- confidential PDFs

Good dataset options:

- public technical documentation snippets
- public API docs
- self-authored policy/checklist documents
- small synthetic product requirement docs
- public open-source project docs

---

## Milestones

### Milestone 1 - Skeleton

- FastAPI app boots.
- PostgreSQL + pgvector boots in Docker Compose.
- Basic document and chunk schema.
- Healthcheck endpoint.
- First API contract test.

### Milestone 2 - Ingestion / Retrieval

- Seed documents.
- Chunk and embed documents.
- Store chunks and metadata.
- Retrieval endpoint returns snippets and citations.
- Retrieval tests pass.

### Milestone 3 - Workflow

- Implement a bounded review workflow with LangGraph or a similarly explicit state graph.
- Keep each workflow node/tool as a normal Python function with typed inputs and outputs.
- Store runs, steps, tool calls, and outputs.
- Return a structured report with citations.
- Add retry/failure handling and unsupported-claim guardrails.
- Agent/tool tests pass.

### Milestone 4 - Evaluations

- Golden question set.
- Retrieval and answer-quality evals.
- Regression report generation.
- Failure analysis document.
- Optional Ragas/promptfoo comparison after the baseline eval path is working.

### Milestone 5 - Public Polish

- README with setup and demo.
- Architecture notes.
- Framework decision note explaining why core RAG is direct and LangGraph is used only for workflow orchestration.
- Sample screenshots or sample JSON output.
- Resume/project-page wording ready.

---

## Resume Wording After Completion

Use truthful wording:

```text
Built a public LLM/RAG workflow project with FastAPI, PostgreSQL/pgvector, Docker, document ingestion, retrieval evaluation, bounded tool execution, and observability-style logs.
```

If LangGraph is implemented cleanly:

```text
Built a public LLM/RAG workflow project with FastAPI, PostgreSQL/pgvector, Docker, document ingestion, retrieval evaluation, and a bounded LangGraph tool workflow with citations and observability-style logs.
```

Do not say:

```text
Production LLM agent platform
```

unless it is deployed, used by real users, and operated like a production system.

---

## Success Criteria

This project is successful if a recruiter or engineer can see in under two minutes that:

- it is not a chatbot demo
- it has a real backend
- it has retrieval and citations
- it has tool execution
- it has evals
- it has logs/traces
- it is Dockerized
- it has tests
- it is safe and truthful to discuss in interviews
