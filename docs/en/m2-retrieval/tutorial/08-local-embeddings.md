# M2.10 Tutorial 8 — A local embedding model

**Prerequisite:** Tutorial 7's `uv run pytest tests/retrieval/test_09_bm25.py -q` passes.

Every embedding so far came from an API call. That was a deliberate choice, and this is the checkpoint that revisits it by running a model inside the process instead.

The chapter assumes you have never loaded a transformer yourself. It starts from what an embedding model is, explains why this project waited nine checkpoints before installing one, installs PyTorch with a backend chosen from measurements rather than habit, and ends on the failure mode that a second embedding provider introduces.

## Files this checkpoint touches

| Action | Path | Role |
|---|---|---|
| Modify | `pyproject.toml` | Declares the CPU, CUDA, and ROCm optional extras and their package indexes |
| Regenerated | `uv.lock` | Records the resolved dependency set for the optional local-model backends |
| Modify | `app/config.py` | Adds the `sbert` provider name and its model setting |
| Create | `app/retrieval/sbert.py` | The lazily loaded local embedding provider |
| Modify | `app/retrieval/embeddings.py` | Adds the factory branch that builds the SBERT provider from configuration |
| Modify | `app/retrieval/__main__.py` | Adds `sbert` to the CLI provider choices |
| Modify | `app/retrieval/__init__.py` | Exports the new provider on the public package surface |
| Verify | `tests/retrieval/test_10_sbert.py` | Focused tests covering the provider and its wiring without a real model |

The diagrams and shell commands below are not copied into files. Implementation blocks go into the path named above them, and every method block for `sbert.py` belongs inside the `SentenceTransformerEmbeddingProvider` class.

## If you have never loaded an embedding model

M2.2 described an embedding as text turned into a fixed-length vector. That is what it does. What produces it is a neural network, and which network matters more than any other setting in the retrieval path.

BERT reads a sentence and produces one vector **per token**, not one per sentence. To compare two sentences you would have to decide how to collapse those token vectors into one, and the obvious choices work poorly. Averaging BERT's token vectors gives sentence similarity barely better than averaging word vectors.

**SBERT is BERT fine-tuned so that the collapsed vector is actually meaningful.** The training pairs sentences known to be similar and pushes their vectors together while pushing dissimilar pairs apart. The architecture barely changes; the training objective does. That is the whole idea behind Sentence-BERT.

### The bi-encoder shape

The important structural fact is how the query and the document meet.

#### No file changes — reading the bi-encoder shape

```text
query    ──> [model] ──> vector ─┐
                                 ├─> cosine similarity ─> score
document ──> [model] ──> vector ─┘
```

Each text goes through the model **alone**. They only meet afterwards, as two vectors compared by an arithmetic operation. This is called a **bi-encoder**.

That separation is what makes the whole retrieval path possible. Documents can be embedded once, ahead of time, and stored. At query time only the query passes through the model, and the search becomes a distance computation over stored vectors. Embedding 9,172 chunks is a one-off cost.

Remember the shape. M2.11 replaces exactly this arrangement and the consequences follow directly from it.

## Why the API came first

M2.2 could have loaded a local model. It did not, and the reason is worth stating because it is a packaging decision rather than a modelling one.

A local model drags in PyTorch. That is hundreds of megabytes, a platform-specific build, and a container image several times larger. Taking that on at M2.2 would have meant every checkpoint since carried it, including the ones that had nothing to do with models.

**M2.1 through M2.9 run with no machine-learning dependency at all.** Parsing, chunking, seeding, vector search, lexical search, fusion, and BM25 all work without it. That is not an accident, and it is the reason this chapter comes late.

The rule generalizes: **take a dependency at the checkpoint that needs it, not at the one that first mentions it.**

## Installing PyTorch

### Choosing a backend from measurements

PyTorch ships as several mutually exclusive builds. The obvious instinct is to pick the one matching your GPU. Resist it until the workload is known.

| Workload | Size |
|---|---|
| Reranking (M2.11) | 6-layer MiniLM over roughly 20 candidates per query |
| Embedding backfill | 9,172 chunks, run once |

Both are small. Batches this size are dominated by per-call overhead rather than arithmetic, and an integrated GPU shares system memory so it has no bandwidth advantage either. **The default backend for this project is CPU**, and that is a measured decision rather than a fallback.

There is a second reason on AMD integrated hardware specifically. Support for these chips is arriving but incomplete: convolution databases are not shipped for every target, and the common environment-variable override that people reach for is reported to hard-lock machines rather than work. **A backend that might lock the machine is not a backend.**

### Switching backends with uv

Rather than documenting an install command, the project declares the backends and lets uv resolve one.

#### Modify `pyproject.toml`

```toml
[project.optional-dependencies]
cpu = ["torch>=2.12", "sentence-transformers>=3.0"]
cu130 = ["torch>=2.12", "sentence-transformers>=3.0"]
rocm = ["torch>=2.12", "sentence-transformers>=3.0", "triton-rocm>=3.7"]

[tool.uv]
conflicts = [
    [{ extra = "cpu" }, { extra = "cu130" }, { extra = "rocm" }],
]

[tool.uv.sources]
torch = [
    { index = "pytorch-cpu", extra = "cpu" },
    { index = "pytorch-cu130", extra = "cu130" },
    { index = "pytorch-rocm", extra = "rocm" },
]
triton-rocm = [
    { index = "pytorch-rocm", extra = "rocm" },
]

[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true

[[tool.uv.index]]
name = "pytorch-cu130"
url = "https://download.pytorch.org/whl/cu130"
explicit = true

[[tool.uv.index]]
name = "pytorch-rocm"
url = "https://download.pytorch.org/whl/rocm7.2"
explicit = true
```

**What to look for in the configuration**

- `conflicts` makes uv **reject** two backends at once instead of silently resolving to whichever wins. Two PyTorch builds in one environment is a class of bug that produces confusing import errors much later.
- The ROCm torch wheel requires an exact `triton-rocm` version. Declaring that package directly in the `rocm` extra and routing it to the same official index lets uv find the transitive dependency while `explicit = true` is active.
- `explicit = true` stops these indexes from serving any package not routed to them by `tool.uv.sources`. Without it, an index could shadow an unrelated package from PyPI.
- The backend is not recorded in the lockfile as a single answer; it is chosen per install. That is what lets a laptop and a deployment target differ without editing the project.

#### Run — installing the CPU extra and updating `uv.lock`

```bash
uv sync --extra cpu
```

Confirm which build landed:

#### Run — checking the installed PyTorch build

```bash
uv run python -c "import torch; print(torch.__version__)"
```

A build tagged `+cpu` is the CPU build. A tag naming a compute platform means that build was installed, which is only useful if the matching hardware and drivers are present. **A CUDA build on a machine without CUDA is not an error; it just never uses a GPU while occupying gigabytes.**

## The failure mode this checkpoint introduces

Read this before writing any code, because it is the part that produces wrong answers rather than exceptions.

An embedding vector means nothing on its own. It only has meaning **relative to the model that produced it**. Two models produce vectors of the same width that live in unrelated spaces.

The database stores 384 numbers per chunk. It does not store which model produced them. So this sequence is possible:

#### No file changes — reading how mixed embedding spaces go wrong

```text
1. Embed 9,172 chunks with the API provider     -> 384 numbers per chunk
2. Switch the provider to the local model
3. Embed the query locally                      -> 384 numbers
4. Compare                                      -> a number comes back
```

Step 4 succeeds. Cosine similarity between two 384-dimensional vectors is always computable. **The result is meaningless, and nothing anywhere reports a problem.** Search quality collapses while every test still passes and no log line is emitted.

**Switching embedding providers requires re-embedding the entire corpus.** There is no partial migration and no mixed state that works. The spec says the database embedding set and every query against it must use one provider, and this is what that sentence is protecting against.

The code cannot fully prevent this, but it can refuse the one case it does see: a model whose width does not match the column.

## Implementation

`app/retrieval/sbert.py` is a new module rather than an addition to `app/retrieval/embeddings.py`. The reason is dependency direction. The provider boundary must stay importable with no PyTorch installed, and keeping the model-bearing code in its own file makes that property obvious rather than merely true.

### 1. Construction stays cheap

#### Create `app/retrieval/sbert.py` — module header

```python
"""Local sentence-transformer embeddings behind the shared provider boundary.

``sentence_transformers`` is imported lazily so that installing the project without a
torch backend extra leaves ``app.retrieval`` importable.
"""

import asyncio
from collections.abc import Sequence

from app.retrieval.embeddings import EmbeddingProvider, _texts, validate_embeddings
```

**What to look for in the code**

- The import list is the lesson: `sentence_transformers` is not on it. The module imports only the standard library and M2.2's provider boundary, and that absence is what keeps `import app.retrieval` working on a machine with no torch backend installed.
- `EmbeddingProvider`, `_texts`, and `validate_embeddings` come from `embeddings.py`, so this provider inherits the same input handling and output validation as every other one instead of writing its own.

#### Modify `app/retrieval/sbert.py` — `SentenceTransformerEmbeddingProvider.__init__`

```python
def __init__(
    self,
    *,
    model: str = "sentence-transformers/all-MiniLM-L6-v2",
    dimensions: int = 384,
    batch_size: int = 32,
) -> None:
    if not model:
        raise ValueError("embedding model must be nonempty")
    if dimensions <= 0:
        raise ValueError("embedding dimensions must be positive")
    if batch_size <= 0:
        raise ValueError("embedding batch size must be positive")
    self.model = model
    self.dimensions = dimensions
    self.batch_size = batch_size
    self._encoder: object | None = None
```

**What to look for in the code**

- `_encoder` starts as `None`. Constructing this provider loads **no weights** and touches no disk. Building the object in a factory, a test, or a CLI argument parser must stay free.
- `all-MiniLM-L6-v2` produces exactly 384 dimensions, which is why it is the default. It matches `DIM` and the existing column, so adopting it needs no migration.

#### Run — the tests for this step

```bash
uv run pytest tests/retrieval/test_10_sbert.py -q -k "constructing or rejects_invalid or defaults_match"
```

- `test_constructing_provider_loads_no_model`
- `test_provider_rejects_invalid_construction`
- `test_provider_defaults_match_the_database_column`

### 2. Loading once, and failing usefully

#### Modify `app/retrieval/sbert.py` — `SentenceTransformerEmbeddingProvider._load`

```python
def _load(self) -> object:
    """Import and construct the encoder once, then reuse it."""
    if self._encoder is not None:
        return self._encoder

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is not installed; run one of "
            "`uv sync --extra cpu`, `--extra rocm`, or `--extra cu130`"
        ) from exc

    encoder = SentenceTransformer(self.model)
    reported = encoder.get_sentence_embedding_dimension()
    if reported != self.dimensions:
        raise ValueError(
            f"model {self.model!r} produces {reported} dimensions, "
            f"but this database stores {self.dimensions}"
        )
    self._encoder = encoder
    return encoder
```

**What to look for in the code**

- The import sits **inside the function**. At module scope it would break `import app.retrieval` for anyone who installed the project without a backend extra, which is most people most of the time.
- `ImportError` becomes `RuntimeError` carrying the command that fixes it. A bare `ModuleNotFoundError` tells a reader that something is missing, not what to do about it.
- The width check is the only mismatch this code can actually detect. A model of the wrong width is caught here; a model of the **right** width and the wrong space is not detectable at all, which is why the previous section exists.

#### Run — the tests for this step

```bash
uv run pytest tests/retrieval/test_10_sbert.py -q -k "missing_extra or wrong_dimension"
```

- `test_missing_extra_raises_an_actionable_runtime_error`
- `test_load_rejects_a_model_with_the_wrong_dimension`

### 3. Not blocking the event loop

#### Modify `app/retrieval/sbert.py` — `SentenceTransformerEmbeddingProvider.embed_documents`

```python
async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
    """Encode a batch off the event loop and validate before returning."""
    inputs = _texts(texts)
    if not inputs:
        return []

    encoder = self._load()

    def _encode() -> list[list[float]]:
        """Run the synchronous, CPU-bound forward pass in a worker thread."""
        return encoder.encode(
            inputs,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).tolist()

    vectors = await asyncio.to_thread(_encode)
    return validate_embeddings(
        vectors,
        expected_count=len(inputs),
        dimensions=self.dimensions,
    )
```

**What to look for in the code**

- `encode` is synchronous and compute-bound. Calling it directly inside a coroutine would stall the entire event loop for the duration, freezing every other request in the process. `asyncio.to_thread` moves it to a worker.
- This is the difference the API provider hides. Awaiting a network call yields control; running a model does not yield anything unless you arrange it.
- `validate_embeddings` is the same function the other two providers use. A new provider does not get a new validation path, because a weaker check on one provider is a hole in all of them.
- `normalize_embeddings=True` matches what the deterministic provider already does, keeping the stored vectors on one scale.

#### Run — the tests for this step

```bash
uv run pytest tests/retrieval/test_10_sbert.py -q -k "embed_documents or empty_batch or shared_validation"
```

- `test_embed_documents_reuses_the_model_and_runs_encode_off_loop`
- `test_empty_batch_does_not_load_a_model`
- `test_provider_output_still_passes_through_shared_validation`

### 4. Reaching it through the factory

#### Modify `app/retrieval/embeddings.py` — `get_embedding_provider`

```python
if configured.embedding_provider == "sbert":
    # Imported here, not at module scope: app.retrieval.sbert imports this
    # module for the provider base class and its validation helpers.
    from app.retrieval.sbert import SentenceTransformerEmbeddingProvider

    return SentenceTransformerEmbeddingProvider(
        model=configured.sbert_model,
        dimensions=configured.embed_dim,
    )
```

One naming detail causes more confusion than it should. The distribution installed with `uv sync` is `sentence-transformers`, with a hyphen, and that is the name that belongs in `pyproject.toml` and in any message telling a reader what to install. The module imported in Python is `sentence_transformers`, with an underscore. **A `RuntimeError` that names the import instead of the distribution sends the reader to a package name that does not exist.**

The deferred import here is not about PyTorch. `sbert.py` imports `embeddings.py` for the base class, so importing it back at module scope would be a cycle. Deferring resolves it in the one place that needs it.

The factory branch alone does not let configuration or the CLI accept the value `sbert`. `app/config.py` gains the name in its provider `Literal` and a model setting beside it, `app/retrieval/__main__.py` gains it in `ProviderName` and the `--provider` choices, and `app/retrieval/__init__.py` gains the import and its `__all__` entry. They change together, exactly as the file map above lists them.

#### Run — the tests for this step

```bash
uv run pytest tests/retrieval/test_10_sbert.py -q -k "factory or cli_accepts or public_surface"
```

- `test_factory_builds_configured_sbert_provider_without_loading_model`
- `test_cli_accepts_sbert_provider`
- `test_public_surface_exports_sbert_provider`

## Focused tests and the contracts they protect

#### Run `tests/retrieval/test_10_sbert.py`

```bash
uv run pytest tests/retrieval/test_10_sbert.py -q
```

| Value the test breaks | Contract being protected |
|---|---|
| A model-scope import of `sentence_transformers` | The package imports with no backend installed. |
| Weights loaded in the constructor | Building a provider stays free. |
| A provider whose width differs from `DIM` | Vectors always fit the column. |
| A missing backend reported as `ModuleNotFoundError` | The error names the command that fixes it. |
| A private validation path for this provider | One validation covers every provider. |

The rule for moving on is simple: do not accept M2.10 if `import app.retrieval` requires a backend extra, if constructing a provider downloads anything, or if the corpus was re-embedded without being cleared first.

## What you should be able to explain now

- **What did SBERT change relative to BERT?**
  - **Answer:** Not the architecture but the training objective, which is what makes a single collapsed sentence vector comparable between sentences.
- **What does the bi-encoder shape buy, and what does it cost?**
  - **Answer:** It lets documents be embedded once and stored, making search a distance computation; the cost is that the query and the document never meet inside the model.
- **Why did this project reach checkpoint nine before installing PyTorch?**
  - **Answer:** A dependency is taken at the checkpoint that needs it, and nothing before this one did.
- **Why is `conflicts` needed in the uv configuration?**
  - **Answer:** It rejects two PyTorch backends in one environment instead of silently resolving to one of them.
- **What happens if the corpus is embedded with one provider and queried with another?**
  - **Answer:** Similarity is still computable and no error is raised, so retrieval quality collapses silently; the corpus must be re-embedded.
- **Why does the encoder run in a worker thread?**
  - **Answer:** It is synchronous and compute-bound, so calling it inside a coroutine would block the event loop for every other task in the process.

---

**Next:** [Tutorial 9](09-cross-encoder.md) keeps the model but changes where the query meets the document, which turns retrieval into two stages.
