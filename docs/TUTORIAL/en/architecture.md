# Architecture

DocReview prepares SEC and DART filings through one source-preserving pipeline. The [Quick Start](quickstart.md) prepares its first two reports; [retrieval testing](retrieval.md) checks the evidence before the [first answer](answers.md).

## Common corpus contract {#contracts}

`schemas/manifest.schema.json` is generated from the Python `Manifest` contract. A corpus has four separate collections:

- **Corpus identity:** a stable identifier and display name, independent of its local directory.
- **Document references:** shared filing identity, dates, language, issuer aliases, and explicit SEC or DART metadata.
- **Source artifacts:** corpus-relative paths, exact byte hashes, encoding, and acquisition provenance. DART archive and canonical text are distinct artifacts.
- **Processing selections:** named sets of exact primary artifacts. A selection does not duplicate the document catalog.

Reading an artifact checks its confined path and exact bytes before decoding. An unknown acquisition timestamp is recorded as unknown rather than inferred from a file modification time.

## Shared processing {#processing}

Both adapters return the same source-linked filing structure. Common processing retains headings, paragraphs, tables, cells, row/column spans, and units. Small tables remain intact. Larger tables become row groups with repeated headers and units; oversized rows split at cells and oversized narrative cells split at sentences.

The target is 2,048 tokens over **context plus body**. The hard maximum is 8,192 tokens and the default character bound is 12,000, matching the default evidence budget. A model with a smaller input window uses its own tokenizer and tighter maximum. Content that cannot fit at a valid boundary raises an explicit error.

Each fragment retains its actual enclosing source span, original header cells, and the separate source spans of associated captions. Normalized cell-text intervals are not presented as HTML character offsets. Fragments remain independent retrieval units.

## Storage and identity {#storage}

| Entity | Responsibility |
|---|---|
| Corpus and processing selections | Define which source artifacts an operation processes |
| Document | Store normalized filing identity |
| Source artifact | Identify acquired bytes and their origin |
| Parsed structure and current-parse reference | Retain structural output separately from filing identity |
| Chunk | Store source-linked evidence, context, fragment metadata, and stable identity |
| Embedding | Bind a vector to exact indexed text, provider, model, dimensions, and tokenizer |
| Lexical statistics | Support PostgreSQL lexical retrieval and BM25 |
| Job | Record queue, progress, cancellation, retry, and interruption |
| Evaluation and snapshot | Record measured results and immutable index evidence |
| Run and trace | Explain answer execution, usage, and failures |

A display ordinal is not a chunk identity. Reordering unchanged chunks preserves their database identities and reusable vectors. Embedding writes verify the current input again after the provider returns.

Snapshots compare the exact evaluated index fingerprint and read all copied state in one repeatable-read transaction. Later live-index changes do not change a saved snapshot.

## CLI, web, and execution {#execution}

CLI and web submit the same preparation jobs. API schemas generate the web's wire types. Jobs use `queued`, `running`, `succeeded`, `failed`, `cancelled`, and `interrupted`; preparation state refreshes after a job reaches a terminal state.

DEV reads only `OPENAI_API_KEY_LOCAL`; production reads only `OPENAI_API_KEY_PROD`. Browser conversations, acquired source files, and server-side indexes are separate stores. Normal setup preserves compatible data; [destructive reset](cli.md#shutdown-and-selective-cleanup) is a separate operation.
