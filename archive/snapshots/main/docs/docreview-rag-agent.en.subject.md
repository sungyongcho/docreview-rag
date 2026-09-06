# DocReview RAG Agent

Summary:
This project is about building a document-grounded LLM workflow that can ingest
structured documents, retrieve evidence, execute bounded tools, produce cited review
reports, and evaluate its own regressions.

Version: 1.1

---

## Contents

I. Introduction

II. General Instructions

III. Mandatory Part

IV. Evaluation Requirements

V. README Requirements

VI. Additional Mandatory Requirements

VII. Submission and Peer-Evaluation

VIII. Appendix

---

## Chapter I

## Introduction

Many LLM demonstrations answer questions about documents.

Most of them are not review systems.

RAG, or Retrieval-Augmented Generation, is a pattern where a system first retrieves
relevant external knowledge and then uses that retrieved evidence to generate an answer.
The model is not expected to know the answer from its parameters alone. It must answer
from the documents that were found.

This changes the problem. A RAG system is not only a prompt. It is a pipeline made of
document parsing, chunking, indexing, embedding, retrieval, citation mapping, generation,
and evaluation. If any part of that pipeline is weak, the final answer can look fluent
while still being unsupported.

For this project, RAG is the evidence layer. The workflow must retrieve source material,
keep track of where it came from, and let later steps decide whether that material
supports the requested review. Retrieval is allowed to return candidates. It is not
allowed to magically become truth.

A review system must be able to say where an answer came from, what evidence was
retrieved, which tool made which decision, what the model did, and whether the result
regressed compared to a known set of cases.

In this project, you will build a small but inspectable document review workflow.
The goal is not to create a generic chatbot. The goal is to create a backend system
that can defend its conclusions with citations, logs, and evaluations.

You are expected to learn and make design decisions. The subject gives you the
constraints and the expected behavior. It does not give you an implementation order.

---

## Chapter II

## General Instructions

- Your project must be implemented as a FastAPI backend service.
- Your project must expose an HTTP API.
- Your API must use typed request and response schemas.
- Your project must use a persistent relational database.
- Your project must use PostgreSQL with pgvector.
- Your project must support vector retrieval over document chunks.
- Your project must be runnable locally from a clean checkout with Docker Compose.
- Your project must include an asynchronous background worker for ingestion and review runs.
- Your project must include tests.
- Your project must include a reproducible evaluation suite.
- Your project must include public or synthetic documents only.
- Your project must not require private notes, private resumes, private emails, or
  confidential company material.
- Your project must not hard-code API keys or secrets.
- Your project must not silently invent citations.
- Your project must not present unsupported model output as document-grounded truth.
- Your project must not hide the core retrieval, citation, storage, or evaluation logic
  behind a black-box RAG framework.
- Your project must use LangGraph for the bounded review workflow.
- Your project must use LangChain for at least one inspectable LLM-facing component,
  such as prompt templates, chat model integration, message schemas, output parsing, or
  small runnable composition.
- Your project must not use LangChain or LangGraph as a replacement for understanding
  your own ingestion, retrieval, citation, storage, and evaluation code.

Your service should not crash under ordinary invalid inputs. If a request cannot be
processed, it must return a structured error response and store enough information to
debug the failure.

You may use an LLM provider of your choice. You must isolate provider-specific code so
that the rest of the system does not depend on one vendor's SDK shape.

LangGraph must orchestrate the review workflow. The state transitions, tools, inputs,
outputs, retries, and failure states must be visible in your code and stored in your
database.

LangChain must be used as a learning tool for model-facing application code, not as a
black box. For example, using LangChain to define prompt templates, structured output
parsers, provider adapters, or small runnables is valid. Using a high-level retrieval QA
chain that hides chunk selection, citation mapping, and scoring is not valid for the
mandatory part.

---

## Chapter III

## Mandatory Part

| Field | Requirement |
| --- | --- |
| Project name | `DocReview RAG Agent` |
| Repository | `docreview-rag-agent` |
| Main interface | FastAPI HTTP API |
| Runtime | Local reproducible Docker Compose environment |
| Database | PostgreSQL with pgvector |
| Background processing | Async worker required for ingestion and review runs |
| Workflow orchestration | LangGraph required |
| LLM application layer | LangChain required in an inspectable, limited role |
| Tests | Required |
| Evaluation suite | Required |
| Description | Build a document-grounded review workflow with citations, bounded tools, traces, and regression checks |

### 1. Corpus and Ingestion

Your system must ingest a small document corpus.

Each source document must have a stable identity. Each citation target must be stable
enough to be used in a golden evaluation set.

Your ingestion layer must:

- parse documents into sections or equivalent citation units;
- chunk content for retrieval;
- preserve enough metadata to map each chunk back to its source;
- store documents and chunks in the database;
- avoid duplicate records when ingestion is run more than once;
- execute ingestion through the asynchronous worker;
- expose ingestion status through the API and through stored run records.

You may use the provided synthetic datasets, create your own synthetic corpus, or use
public documents with clear attribution.

### 2. Retrieval

Your system must retrieve evidence for a user question or review item.

The retrieval layer must:

- embed chunks;
- perform top-k vector retrieval;
- return document id, chunk id, section or citation id, snippet, and score;
- support deterministic retrieval settings for evaluation;
- expose retrieval results through an API endpoint;
- make it possible to inspect why a citation was attached to an answer;
- support hybrid lexical and vector search, with documented scoring behavior;
- support reranking with documented tradeoffs and evaluation coverage.

A retrieved chunk is not automatically proof. Your workflow must still decide whether
the evidence supports, contradicts, partially supports, or does not address the claim.

### 3. Review Workflow

Your system must implement at least one bounded review workflow with LangGraph.

The workflow must not be a free-form chat loop. It must be represented as an explicit
graph with typed state. At minimum, it must include:

- a step that retrieves candidate evidence;
- a step that checks whether the evidence supports the requested review item;
- a step that produces a structured report;
- a failure path for missing evidence, provider errors, or invalid input;
- execution through an asynchronous worker, with run status persisted while the workflow is in progress.

Each graph node must call ordinary Python functions or tools whose behavior can be
tested outside of LangGraph. Conditional edges, retries, and terminal states must be
clear enough to explain during peer-evaluation.

LangChain must appear in the workflow or LLM boundary in a way that teaches the library
without hiding your system. Acceptable uses include prompt templates, chat model calls,
message objects, structured output parsing, or small runnable chains around a single
LLM step.

Each tool or workflow step must have a clear input and output contract. Tool execution
must be stored so that a reviewer can reconstruct the sequence of actions taken during
a run.

The final report must be machine-readable. Every factual conclusion that claims support
from the corpus must include citations. Unsupported or uncertain conclusions must be
marked as such instead of being forced into a confident answer.

### 4. Persistence and Traceability

Your database must store the important state of the system.

At minimum, it must represent:

- documents;
- chunks;
- review runs;
- tool calls or workflow steps;
- final reports;
- evaluation results;
- logs or trace events.

Trace records must include enough information to debug a run after it has completed.
For example: request id, run id, model name, retrieval top-k, retrieved hit count,
latency, estimated token usage or cost, tool sequence, and error details.

Your system must also store prompt or model version metadata, provider name, and enough
configuration to explain which prompt, model, retrieval settings, and workflow version
produced a report.

### 5. API Surface

Your API must make the system usable without a frontend.

At minimum, expose endpoints that allow an evaluator to:

- check service health;
- list or inspect documents;
- trigger or inspect ingestion;
- run retrieval against a query;
- start a review run;
- inspect a stored run and its tool calls;
- run the evaluation suite or read its latest result;
- inspect worker-backed ingestion or review job status.

The exact route names are up to you. They must be documented.

### 6. Evaluation Suite

Your project must include a golden set.

The evaluation suite must measure at least:

- whether expected citation targets appear in retrieved results;
- whether claim or checklist labels match expected labels;
- whether unsupported claims are refused or marked correctly;
- whether a new run regressed compared to the previous accepted result.

The evaluation output must be stored or written as a report that can be read without
running the whole application in debug mode.

You must include at least one written failure analysis. It should describe a case where
retrieval or answer generation failed, why it failed, and what design change would
reduce that failure.

### 7. Reliability

Your project must include automated tests for the core behavior.

At minimum, tests must cover:

- document parsing or ingestion;
- citation-preserving chunk creation;
- retrieval behavior on known queries;
- workflow/tool execution on at least one happy path and one unsupported case;
- evaluation scoring;
- API contract behavior.

Tests that require live LLM calls must be clearly separated from deterministic tests.
The deterministic test suite must be runnable without spending money.

### 8. Runtime, Worker, and Deployment Shape

Your project must include a Docker Compose setup that starts the required local services.

At minimum, the compose environment must include:

- the FastAPI application;
- PostgreSQL with pgvector enabled;
- an asynchronous worker process;
- any required local service dependencies;
- a documented way to seed the demo corpus and run evaluations.

Ingestion and review runs must be represented as jobs or run records whose state can be
inspected while work is pending, running, completed, or failed. Worker failures must be
stored as structured errors rather than disappearing into console output.

### 9. Operational Guardrails

Your project must include:

- prompt or model version tracking;
- provider fallback strategy;
- a local trace viewer for stored trace records;
- cost or token budget logging;
- prompt-injection test cases;
- a documented security and data-boundary note explaining why only public or synthetic
  data is used.

---

## Chapter IV

## Evaluation Requirements

During evaluation, you should be able to demonstrate the following from a fresh checkout:

- the Docker Compose environment starts the application, database, and worker locally;
- the database initializes correctly;
- seed documents can be ingested;
- a retrieval query returns cited snippets;
- a review run returns a structured report;
- worker-backed run status can be inspected;
- the run's tool sequence can be inspected;
- logs or traces show latency and model/retrieval metadata;
- the evaluation suite produces a readable regression result;
- tests pass without requiring private credentials.

The project is incomplete if it only works as a live demo and cannot be tested.

The project is incomplete if it answers with citations that cannot be traced back to
stored chunks.

The project is incomplete if the evaluator cannot tell the difference between retrieved
evidence, model reasoning, tool output, and final report output.

---

## Chapter V

## README Requirements

Your README must be written for a technical recruiter and an engineer.

It must include:

- what the project does;
- what it deliberately does not do;
- setup instructions;
- Docker Compose service overview;
- how to run tests;
- how to run evaluations;
- example API requests or commands;
- sample JSON output;
- architecture notes;
- database model overview;
- retrieval and citation strategy;
- LangGraph workflow and tool strategy;
- LangChain usage and framework boundary;
- observability strategy;
- worker and job-status strategy;
- known limitations;
- future improvements.

Do not describe the project as production software unless it is deployed, monitored,
used by real users, and operated like production software.

Good wording:

```text
Built a public LLM/RAG workflow project with FastAPI, PostgreSQL/pgvector, Docker,
document ingestion, retrieval evaluation, bounded tool execution, citations, and
observability-style logs.
```

Bad wording:

```text
Production LLM agent platform.
```

---

## Chapter VI

## Additional Mandatory Requirements

The following requirements are mandatory. They are included to make the project credible
as a public LLM/RAG/agent engineering portfolio project, not as later polish.

Your project must include:

- asynchronous worker-backed ingestion and review execution;
- hybrid lexical and vector search;
- reranking with documented tradeoffs and evaluation coverage;
- prompt and model version tracking;
- a local trace viewer that makes stored trace records easy to inspect;
- at least one advanced LangGraph behavior such as conditional routing, retry edges,
  resumable runs, or a human-review gate;
- a baseline pytest-based evaluation suite, plus a documented comparison path for Ragas,
  promptfoo, DeepEval, or an equivalent evaluation framework;
- provider fallback strategy;
- cost or token budget enforcement;
- prompt-injection test cases;
- a deployment recipe that explains how the local Docker Compose setup maps to a
  deployable service layout;
- an architecture diagram.

None of these requirements may hide the core behavior. Retrieval, citation mapping,
storage, workflow state, evaluation scoring, and traceability must remain inspectable in
the project code.

---

## Chapter VII

## Submission and Peer-Evaluation

Only files committed to the repository are evaluated.

Do not commit secrets, local databases, generated caches, or private documents.

Before submission, make sure a peer can:

- clone the repository;
- read the subject and README;
- start the service;
- ingest the demo corpus;
- run one retrieval query;
- run one review workflow;
- inspect worker-backed job status;
- inspect one stored run;
- inspect stored traces through the local trace viewer;
- run tests;
- run evaluations;
- read the architecture diagram;
- understand one documented failure case.

During peer-evaluation, you must be able to explain your design choices. You should be
prepared to answer:

- Why did you choose your chunking strategy?
- How do you map chunks back to stable citations?
- What happens when retrieval returns irrelevant evidence?
- What happens when the LLM claims something not found in the documents?
- Why did you use LangGraph for your workflow shape?
- Which LangChain components did you use, and what did you deliberately keep outside it?
- Which parts are deterministic and which parts depend on a model provider?
- How do you estimate or log cost?
- How do you know a change did not regress retrieval?
- Which test would fail if citations were broken?
- What is the most important limitation of your current design?

---

## Chapter VIII

## Appendix

### Suggested Dataset Direction

The repository may contain multiple candidate datasets. Prefer a small synthetic corpus
for the first complete version. A small corpus with precise golden answers is more useful
than a large corpus that cannot be evaluated.

The provided `sample1` dataset is suitable for a first version because it contains a
compact synthetic company-policy corpus and golden cases.

The provided `sample2` dataset is suitable for a harder version because it contains more
documents, more labels, and more cross-document reasoning cases.

### Claim Labels

Your workflow may use different names, but it must distinguish these cases:

- supported by the documents;
- contradicted by the documents;
- partially supported by the documents;
- not found in the documents;
- not enough information to decide.

### Citation Rule

A citation must point to stored evidence. A citation must not point to a prompt, a model
message, or a generated summary unless that generated summary is itself stored and
explicitly treated as derived output.

### Final Goal

The final project should make this obvious in under two minutes:

- it is not a chatbot demo;
- it has a real backend;
- it retrieves document evidence;
- it produces citations;
- it executes bounded tools;
- it stores traces;
- it has evaluations;
- it has tests;
- it is safe to discuss honestly in interviews.
