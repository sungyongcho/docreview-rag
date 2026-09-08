/**
 * Help mode content: one topic per explained control, keyed by the `data-help`
 * attribute of the element it explains. Ids are `<screen>.<name>` and the screen
 * part matches `HelpScreen`, so a renamed hook fails the coverage tests.
 */

import { LOCAL_ENGINE_VISIBLE } from "./build-mode";
import type { Capabilities } from "./types";

export type HelpCapability = Exclude<keyof Capabilities, "environment">;
export interface HelpAccess { capabilities?: Capabilities | null; publicPreview?: boolean }
export interface HelpGuide { summary: string; steps: readonly string[] }

export type HelpScreen =
  | "build"
  | "build.jobs"
  | "build.documents"
  | "review"
  | "measure.playground"
  | "measure.golden"
  | "measure.runs"
  | "measure.compare"
  | "measure.presets"
  | "measure.snapshots"
  | "system";

export interface HelpTopic {
  id: string;
  title: string;
  body: string[];
  tune?: string;
  seeAlso?: string[];
  /** true when the element lives inside collapsed details or only exists on live builds */
  optional?: boolean;
  /** The actual capability required to use this control; omitted for public browsing. */
  capability?: HelpCapability;
  requiredCapabilities?: readonly HelpCapability[];
  availableInPreview?: boolean;
  publicContent?: { capabilities: readonly HelpCapability[]; body: string[]; guide: HelpGuide };
  guide?: HelpGuide;
}

/** Match effective UI permissions, with a hard local-operation boundary in production. */
function capabilityAllowed(capability: HelpCapability, access: HelpAccess): boolean {
  if (access.publicPreview && capability !== "can_compare_published_snapshots") return false;
  if ((capability === "can_configure_local_llm" || capability === "can_use_operations") && access.capabilities?.environment !== "dev") return false;
  return access.capabilities?.[capability] === true;
}

export function developmentHelpTopic(topic: HelpTopic): boolean {
  return !!topic.capability && topic.capability !== "can_compare_published_snapshots";
}

/** Use one topic policy for search, recommendations, details, links, and page help. */
export function accessibleHelpTopic(topic: HelpTopic, access: HelpAccess = {}): HelpTopic | null {
  if (access.publicPreview && topic.availableInPreview === false) return null;
  if (topic.capability && !capabilityAllowed(topic.capability, access)) return null;
  if (topic.requiredCapabilities?.some((capability) => !capabilityAllowed(capability, access))) return null;
  const visible = topic.publicContent?.capabilities.some((capability) => !capabilityAllowed(capability, access))
    ? { ...topic, body: topic.publicContent.body, tune: undefined, guide: topic.publicContent.guide } : topic;
  return access.publicPreview ? { ...visible, guide: { summary: visible.guide?.summary ?? visible.body[0], steps: ["Open the related control.", "Read the available values or recorded results.", "This preview is read-only; questions and server changes are not executed."] } } : visible;
}

/** Attach the owning workspace permission while preserving narrower per-control requirements. */
function restrictedTopics(topics: HelpTopic[], capability: HelpCapability, parent?: HelpCapability): HelpTopic[] {
  return topics.map((topic) => ({ ...topic, capability: topic.capability ?? capability, requiredCapabilities: [...(topic.requiredCapabilities ?? []), ...(topic.capability && topic.capability !== capability ? [capability] : []), ...(parent ? [parent] : [])] }));
}

export const HELP_SCREEN_TITLES: Record<HelpScreen, string> = {
  build: "Build · Pipeline",
  "build.jobs": "Build · Jobs",
  "build.documents": "Build · Documents",
  review: "Ask",
  "measure.playground": "Measure · Playground",
  "measure.golden": "Measure · Golden Tests",
  "measure.runs": "Measure · Runs",
  "measure.compare": "Measure · Compare",
  "measure.snapshots": "Measure · Snapshots",
  "measure.presets": "Measure · Presets",
  system: "System",
};

/**
 * The retrieval profile fields as rendered by `ProfileFields`, prefixed per screen so
 * Playground and Runs each own their ids. `optional` marks fields that sit inside a
 * collapsed disclosure on that screen.
 */
function profileFieldTopics(prefix: string, optional: boolean): HelpTopic[] {
  const id = (field: string) => `${prefix}.${field}`;
  const extra = optional ? { optional } : {};
  return [
    {
      id: id("strategy"),
      title: "Strategy",
      body: [
        "Vector searches embeddings only, Lexical searches the PostgreSQL full-text index only, and Hybrid runs both lanes and fuses their ranks with reciprocal rank fusion (RRF).",
        "Native scores never cross lanes: fusion uses ranks alone, so a vector cosine and a BM25 score are never compared directly.",
        "Reranking and language routing apply to Hybrid only; the other two strategies disable those controls.",
      ],
      tune: "Start with Hybrid. Drop to Lexical when exact tickers, numbers or Korean tokens matter most, or to Vector when the question is paraphrased and no keyword overlap is expected.",
      seeAlso: [id("lexical_ranker"), id("rrf_k"), id("reranker")],
      ...extra,
    },
    {
      id: id("lexical_ranker"),
      title: "Lexical ranker",
      body: [
        "ts_rank_cd is PostgreSQL's cover-density ranking: it rewards query terms that appear close together but carries no inverse document frequency, so common words weigh as much as rare ones.",
        "BM25 scores from the term statistics rebuilt after every ingest (Build step 4) and damps frequent terms with IDF.",
        "Korean chunks are indexed as bigrams; under ts_rank_cd the grams a question's own particles contribute swamp the ranking, which is why the Korean preset uses BM25.",
      ],
      tune: "Prefer BM25 for Korean corpora and whenever term rarity should count. ts_rank_cd is the baseline to compare against, not the target.",
      seeAlso: [id("bm25_k1"), id("bm25_b"), id("bm25_idf")],
      ...extra,
    },
    {
      id: id("k"),
      title: "k",
      body: [
        "k is how many fused hits the profile returns: the evidence the answer model reads, and the cutoff that recall@k, hit rate and MRR are scored at.",
        "candidate_k must be at least k; the fused pool is sliced to k after fusion or, with a reranker, after rescoring.",
      ],
      tune: "Raise k to give the model more evidence at the cost of longer prompts and more distractors. Changing k changes what evaluation numbers mean, so keep it fixed across runs you intend to compare.",
      seeAlso: [id("candidate_k")],
      ...extra,
    },
    {
      id: id("candidate_k"),
      title: "candidate_k",
      body: [
        "Each lane retrieves candidate_k chunks and fusion keeps a pool of that size before the top k are returned.",
        "A larger pool lets a chunk that ranks low in one lane still surface when the other lane agrees, and gives a reranker more to rescore.",
        "The same pool is what Ask exposes as candidates, so pinned or excluded chunks come from here.",
      ],
      tune: "Increase it (the Korean preset uses 30, Accuracy 50) when relevant chunks are missed at fusion time; every extra candidate costs retrieval and reranking latency.",
      seeAlso: [id("k"), id("reranker")],
      ...extra,
    },
    {
      id: id("rrf_k"),
      title: "RRF k",
      body: [
        "In reciprocal rank fusion each lane adds 1 / (rrf_k + rank) for every chunk it ranks, and the sums are sorted.",
        "The default of 60 flattens the curve so a chunk near the top of both lanes beats one that is first in only one lane.",
      ],
      tune: "Lower values make the first few ranks of a single lane dominate; higher values make fusion behave more like counting how many lanes agree. Compare with Preview retrieval before changing it for a session.",
      seeAlso: [id("strategy"), id("candidate_k")],
      ...extra,
    },
    {
      id: id("bm25_k1"),
      title: "BM25 k1",
      body: [
        "k1 controls term-frequency saturation: how much a term that appears repeatedly in a chunk keeps adding score.",
        "Near zero, presence is almost binary; the default 1.2 lets repeated mentions count with diminishing returns.",
      ],
      tune: "Raise k1 when repeated mentions should signal relevance (narrative sections); lower it when a table repeating a token should not outrank a single precise sentence. Only BM25 reads it.",
      seeAlso: [id("bm25_b"), id("lexical_ranker")],
      ...extra,
    },
    {
      id: id("bm25_b"),
      title: "BM25 b",
      body: [
        "b sets how strongly chunk length normalises the score, from 0 (no normalisation) to 1 (full normalisation against the average chunk length).",
        "Chunks are already cut to a target size, so b moves scores less than it would for whole filings, but long table chunks still benefit from it.",
      ],
      tune: "Lower b when long chunks are being unfairly penalised; keep the default 0.75 otherwise. Only BM25 reads it.",
      seeAlso: [id("bm25_k1"), id("bm25_idf")],
      ...extra,
    },
    {
      id: id("bm25_idf"),
      title: "BM25 IDF",
      body: [
        "Lucene computes ln(1 + (N - df + 0.5) / (df + 0.5)) and never goes negative.",
        "Robertson computes ln((N - df + 0.5) / (df + 0.5)), which turns negative for a term that appears in more than half of all chunks, so that term subtracts from the score.",
      ],
      tune: "Stay on Lucene unless you want corpus-wide boilerplate terms to actively penalise a chunk; Robertson can push otherwise good matches below zero.",
      seeAlso: [id("bm25_k1"), id("lexical_ranker")],
      ...extra,
    },
    {
      id: id("reranker"),
      title: "Reranker",
      body: [
        "Cross encoder loads cross-encoder/ms-marco-MiniLM-L-6-v2 locally and reads the question and each candidate chunk together, which is slower but sharper than comparing two separate embeddings.",
        "It rescores the whole fused pool of candidate_k chunks, then the top k are returned; the score stage becomes reranker and the component rankings stay untouched.",
        "It needs the optional torch extra installed on the API host and is available for Hybrid only.",
      ],
      tune: "Turn it on (as the Accuracy preset does) when fusion gets the right chunk into the pool but not into the top k. Expect CPU latency per candidate; the model was trained on English MS MARCO, so gains on Korean text are not guaranteed.",
      seeAlso: [id("candidate_k"), id("k")],
      ...extra,
    },
    {
      id: id("route_by_language"),
      title: "Route by language",
      body: [
        "Lexical retrieval runs one lane per corpus language taken from the session filters, each parsed with that language's tokenizer.",
        "With routing on, a lane runs only when the question visibly contains that script: Hangul for ko, Latin letters for en. A pure-English question then skips the Korean bigram lane instead of matching stray grams.",
        "Vector lanes are not routed; embeddings already match across languages.",
      ],
      tune: "Enable it for mixed corpora and Korean sessions (the Korean preset does). Leave it off when questions are transliterated or when a lane skipped by script would be the only one that can answer.",
      seeAlso: [id("strategy"), id("lexical_ranker")],
      ...extra,
    },
  ];
}

const BUILD: HelpTopic[] = [
  {
    id: "build.runtime",
    title: "Runtime strip",
    body: [
      "Expand the compact runtime summary to inspect API, database, schema, data directory access, and answer model readiness.",
      "A problem turns into a notice with its fix: the command line to run, or Operations buttons (Start database, Plan and Apply migrations, Rebuild app) when a local operator is attached.",
      "Refresh re-reads readiness and the administrator corpus snapshot; the public build shows a read-only label instead.",
    ],
    seeAlso: ["build.next-step", "system.status"],
  },
  {
    id: "build.next-step",
    title: "Next step",
    body: [
      "This callout always names the first stage that needs you: the first stage in action or failed state, a running job with its progress, or a blocked stage with the reason.",
      "Selecting the recommended step opens its execution panel. Review its inputs, then use the action button to start the work.",
    ],
    seeAlso: ["build.stage.filings", "build.stage.evaluate"],
  },
  {
    id: "build.stage.filings",
    title: "1 · Filings",
    body: [
      "Downloads SEC 10-K and DART business reports into data/corpus. Everything downstream cites these files by SHA-256, and re-running only fetches what is missing.",
      "The numbers show filings on disk versus filings listed in the manifests, per registry.",
      "Change… picks the registry, tickers or stock codes, and fiscal years; EDGAR needs SEC_USER_AGENT and DART needs DART_API_KEY in .env.",
    ],
    seeAlso: ["build.stage.index"],
  },
  {
    id: "build.stage.index",
    title: "2 · Parse & chunk",
    body: [
      "Reads each filing, splits it into citable text and table chunks, and loads them into PostgreSQL. Chunk boundaries decide what can be cited, so every answer must point to a chunk from this step.",
      "Ingest all manifests upserts documents from each manifest in order and recomputes BM25 automatically; a manifest row shows entries, files on disk and documents already ingested.",
    ],
    tune: "Run it again after downloading more filings; the numbers line names how many listed filings are not ingested yet. Run Backfill embeddings afterwards.",
    seeAlso: ["build.stage.embeddings", "build.stage.lexical"],
  },
  {
    id: "build.stage.embeddings",
    title: "3 · Embeddings",
    body: [
      "Turns every chunk into a vector so questions can match by meaning, not only by exact words. Vector search is what lets a Korean question find an English filing.",
      "Rows carry the embedding model identity, so switching models marks old vectors stale until you backfill; pending is the count still needing vectors.",
    ],
    tune: "Until pending reaches zero the readiness chip reports lexical only: chunks without a vector are invisible to the vector lane, so hybrid answers lean on the lexical index and Ask blocks the Vector strategy.",
    seeAlso: ["build.stage.ask", "measure.playground.strategy"],
  },
  {
    id: "build.stage.lexical",
    title: "4 · Lexical index (BM25)",
    body: [
      "Keyword statistics for exact terms, tickers, numbers and Korean bigram tokens: term frequencies, chunk lengths and per-lexeme document frequencies.",
      "Hybrid retrieval fuses this index with embeddings through RRF. It is recomputed after every ingest; rebuild by hand only if the statistics were reset.",
    ],
    seeAlso: ["measure.playground.lexical_ranker", "build.stage.index"],
  },
  {
    id: "build.stage.ask",
    title: "5 · Ask",
    body: [
      "Retrieves evidence for a question across both indexes, then lets the model answer only from it. Unsupported answers end as NOT_IN_DOCS.",
      "Retrieval quality, not the model, decides most outcomes; the number shown is how many chunks are searchable right now.",
    ],
    seeAlso: ["review.composer", "build.stage.answer_model"],
  },
  {
    id: "build.stage.answer_model", capability: "can_edit_prompt_policy",
    title: "6 · Answer model",
    body: [
      "The LLM that writes the answer and checks every citation. It is optional: without it, Ask still returns evidence.",
      LOCAL_ENGINE_VISIBLE
        ? "In dev, OPENAI_API_KEY_LOCAL in .env is used; OPENAI_API_KEY_PROD when MODE=prod. Connect a model server in Settings › Local LLM; available models are discovered automatically."
        : "In dev, OPENAI_API_KEY_LOCAL in .env is used; OPENAI_API_KEY_PROD when MODE=prod.",
      "The model never sees the corpus directly, only the evidence from step 5, and provider failures are shown as failures rather than disguised as NOT_IN_DOCS.",
    ],
    tune: LOCAL_ENGINE_VISIBLE ? "Local model connections apply immediately from Settings › Local LLM. After changing an OpenAI key, restart the selected local mode and Re-check." : "After changing an OpenAI key, restart the service and Re-check.",
    seeAlso: ["review.readiness", "system.status"],
  },
  {
    id: "build.stage.evaluate", capability: "can_run_evaluation",
    title: "7 · Evaluate",
    body: [
      "Scores retrieval against golden questions so you can trust, or fix, the steps above. Recall@k, hit rate and MRR measure retrieval only, not answer factuality.",
      "The numbers count evaluation results and frozen snapshots. Run quick evaluation queues a run on the current index; the public build compares published snapshots instead.",
    ],
    seeAlso: ["measure.runs.mode", "measure.snapshots.freeze"],
  },
];

const REVIEW: HelpTopic[] = [

  {
    id: "review.scope",
    title: "Corpus scope",
    body: [
      "Auto resolves the registry from the question: explicit issuer filters win, then issuer aliases found in the text (NVIDIA, 삼성전자), then the script of the question.",
      "SEC or DART pins the registry; a question that names an issuer outside the pinned corpus is rejected with a scope conflict instead of silently searching the wrong filings.",
    ],
    tune: "Pin the scope when aliases are ambiguous or when a Korean question should search English 10-Ks. The Korean preset keeps the selected corpus and explicit language filters.",
    seeAlso: ["review.filters", "review.preset"],
  },
  {
    id: "review.preset", publicContent: {"capabilities": ["can_change_custom_retrieval"], "body": ["Compare the built-in retrieval presets and inspect their effective settings."], "guide": {"summary": "Compare the built-in retrieval presets and inspect their effective settings.", "steps": ["Open the related control.", "Read the available values or recorded results.", "Open the full guide for details."]}},
    title: "Retrieval preset",
    body: [
      "Balanced is hybrid retrieval with ts_rank_cd, k 5, candidate_k 20 and rrf_k 60. Korean adds BM25, candidate_k 30 and route by language. Accuracy adds BM25, candidate_k 50 and the cross-encoder reranker.",
      "Custom exposes every field and is editable on the local operator build only; a public build keeps the built-in presets.",
      "A result applied from Measure (Use selected set or Use for review) switches the session to Custom with that run's profile.",
    ],
    tune: "Try a preset in Measure › Playground on the same question before committing a session to it.",
    seeAlso: ["measure.playground.strategy", "review.snapshot"],
  },
  {
    id: "review.filters",
    title: "Filters",
    optional: true,
    body: [
      "Open Review settings → Filters to narrow evidence by company, fiscal year, report type, section, and language before ranking.",
      "The settings button counts active filter values. Language choices also determine which lexical search lanes run.",
    ],
    seeAlso: ["review.scope", "measure.playground.route_by_language"],
  },
  {
    id: "review.snapshot", capability: "can_query_snapshot",
    title: "Snapshot chip",
    body: [
      "Shown when the session queries a frozen evaluation snapshot instead of the live corpus, after Use for review in Measure › Snapshots.",
      "Retrieval then reads the snapshot's own chunk, embedding and BM25 tables, so answers stay reproducible while the live corpus changes. Snapshot queries need the local operator build.",
    ],
    tune: "Clear it with × to return to the live corpus.",
    seeAlso: ["measure.snapshots.list"],
    optional: true,
  },
  {
    id: "review.readiness", publicContent: {"capabilities": ["can_build_snapshot"], "body": ["Read published corpus availability. Public document counts describe published filings, not private runtime totals."], "guide": {"summary": "Read published corpus availability. Public document counts describe published filings, not private runtime totals.", "steps": ["Open the related control.", "Read the available values or recorded results.", "Open the full guide for details."]}},
    title: "Readiness chip",
    body: [
      "Summarises what the corpus can do right now: empty, embeddings pending (lexical only), vector only when BM25 is not built, or the filing count with hybrid ready.",
      "Clicking it opens Build › Pipeline, where the Next step callout names the stage that fixes the state.",
    ],
    seeAlso: ["build.stage.embeddings", "build.stage.lexical"],
  },
  {
    id: "review.composer", availableInPreview: false,
    title: "Question",
    body: [
      "Enter sends, Shift+Enter adds a line. The last six turns of the conversation travel with the question so follow-ups keep their context.",
      "Every answer must cite retrieved chunks; when the corpus has no direct support the verdict is Not in documents and related evidence is shown without an answer.",
    ],
    seeAlso: ["review.send", "review.evidence"],
  },
  {
    id: "review.send", availableInPreview: false,
    title: "Send",
    body: [
      "Disabled while a review runs, while the API is down or still being checked, when the corpus is empty, or when Vector retrieval is selected but embeddings are pending.",
      "The request preview shows effective preset differences, filters, prompt composition, and the next request payload. Retrieved evidence is only available after execution starts.",
      "Provider calls are rate- and cost-limited; when the daily budget is spent, evidence still loads and the banner says when answers resume.",
    ],
    seeAlso: ["review.readiness", "build.stage.answer_model"],
  },
  {
    id: "review.run-trace", publicContent: {"capabilities": ["can_edit_run_limits"], "body": ["Read the recorded stages, measurements, and failure details without changing execution limits."], "guide": {"summary": "Read the recorded stages, measurements, and failure details without changing execution limits.", "steps": ["Open the related control.", "Read the available values or recorded results.", "Open the full guide for details."]}}, availableInPreview: false,
    title: "Run trace",
    body: [
      "What the run actually did: its identifier, how many provider requests it made, tokens in and out, elapsed seconds, and the node path it took.",
      "When a run stops early this is also where the reason lives. A budget failure names the exhausted resource with its limit and the observed value; a provider failure names the status, the attempts and the exception; a node failure names the step and its message.",
      "The run identifier is the handle for correlating a failure with the server-side step traces at /runs/{id}/traces.",
      "Execution performance shows recorded stage and model durations, attempts, and local provider timing when available. Missing values remain Not collected; elapsed time is not an estimated completion time.",
    ],
    tune: "The wall clock, iteration and token ceilings are under RAG settings › Run limits above the input. Evidence size is in Evidence. Trace buttons open the relevant panel or System status for connection failures.",
    seeAlso: ["review.send", "system.status"],
    optional: true,
  },
  {
    id: "review.evidence", availableInPreview: false,
    title: "Evidence, pins and exclusions",
    body: [
      "Each answer lists its candidate chunks as collapsed cards titled by filing section, with the document id, a table badge and the character span; pinned cards start open and ten cards show per page.",
      "Pin chunks that must be cited and exclude chunks that mislead, then Use selected evidence re-runs the citation check on that selection using the candidate token from the first pass.",
    ],
    seeAlso: ["measure.playground.candidate_k"],
    optional: true,
  },
  { id: "review.rag", publicContent: {"capabilities": ["can_edit_prompt_policy"], "body": ["Open Review settings to inspect this conversation and adjust its available filters."], "guide": {"summary": "Open Review settings to inspect this conversation and adjust its available filters.", "steps": ["Open the related control.", "Read the available values or recorded results.", "Open the full guide for details."]}}, title: "Review settings", body: ["Open one conversation panel for Filters and the Search, Evidence, and Run limits sections permitted in this environment. Running requests retain their original settings."], optional: true },
  { id: "review.retrieval", capability: "can_change_custom_retrieval", requiredCapabilities: ["can_edit_prompt_policy"], title: "Custom retrieval", body: ["Customize the current conversation here without leaving the chat. Conversation candidate pools are limited to 100 and must be at least k."], optional: true },
  { id: "review.evidence-policy", capability: "can_edit_prompt_policy", title: "Evidence sent to the model", body: ["Controls conversation history and evidence size. These are separate from the limits for the complete run."], optional: true },
  { id: "review.run-limits", capability: "can_edit_run_limits", requiredCapabilities: ["can_edit_prompt_policy"], title: "Run limits", body: ["Iteration, token and wall-clock limits apply across the complete run, including retries. Zero blocks a resource; wall clock is measured in seconds."], optional: true },
  ...restrictedTopics(profileFieldTopics("review.retrieval", true), "can_change_custom_retrieval", "can_edit_prompt_policy"),
];

const PLAYGROUND: HelpTopic[] = [
  {
    id: "measure.playground.question",
    title: "Question",
    body: [
      "One query run through the explicit retrieval profile below, with no effect on any review session. Preview retrieval persists nothing; Preview review records a run and its provider usage like a real review.",
      "Use the same question across profile changes so the component rankings and fused results are comparable.",
    ],
    seeAlso: ["measure.playground.preview_retrieval"],
  },
  ...profileFieldTopics("measure.playground", false),
  {
    id: "measure.playground.preview_retrieval",
    title: "Preview retrieval",
    body: [
      "Calls /admin/retrieval/preview with the question and profile and shows the score stage, each lane's ranking and the fused results. Query embedding can call the configured provider.",
    ],
    seeAlso: ["measure.playground.rankings", "measure.playground.results"],
  },
  {
    id: "measure.playground.preview_review",
    title: "Preview review",
    body: [
      "Runs retrieval and then the answer model once through /admin/review/preview, returning the report label, answer and citations.",
      "It records provider usage like a real review, so use it to check the verdict after retrieval already looks right.",
    ],
    seeAlso: ["measure.playground.review", "system.usage"],
  },
  {
    id: "measure.playground.rankings",
    title: "Component rankings",
    body: [
      "One column per lane, listing chunk ids in that lane's own order before fusion; vector · ko-style columns appear when a language lane produced ranks.",
      "A chunk high in both columns wins fusion; a chunk in only one column needs a low rrf_k to stay on top.",
    ],
    seeAlso: ["measure.playground.rrf_k", "measure.playground.route_by_language"],
    optional: true,
  },
  {
    id: "measure.playground.results",
    title: "Fused results",
    body: [
      "The top k chunks after RRF, or after the reranker when one is on, each with its citation, document and character span.",
      "The score stage in the heading says which of the two produced the final order.",
    ],
    seeAlso: ["measure.playground.k", "measure.playground.reranker"],
    optional: true,
  },
  {
    id: "measure.playground.review",
    title: "Review preview",
    body: [
      "The report label (SUPPORTED or NOT_IN_DOCS), the generated answer and the citations the model made, or the provider failure when the answer could not be produced.",
    ],
    seeAlso: ["measure.playground.preview_review"],
    optional: true,
  },
];

const GOLDEN: HelpTopic[] = [
  {
    id: "measure.golden.suite",
    title: "Golden suite",
    body: [
      "Suites pair a registry with a question language, including the SEC EN, KO and mixed _v2_astra suites. Each case holds a question, an expected label and answer spans located by document id, character offsets and source SHA-256.",
      "Absent cases (expected NOT_IN_DOCS) have no spans and are not scored; only positive cases feed the metrics.",
    ],
    seeAlso: ["measure.runs.suite"],
  },
  {
    id: "measure.golden.questions",
    title: "Golden questions",
    body: [
      "The canonical JSON file is read-only and identified by its SHA-256. Create a draft to edit questions or spans, validate it, then publish it; published revisions are immutable.",
      "After a run is selected in Runs, the Eval, First rank and RR columns show whether each case hit within k and at which rank.",
    ],
    seeAlso: ["measure.runs.results", "measure.golden.revision"],
  },
  {
    id: "measure.golden.revision", capability: "can_edit_golden",
    title: "Golden revision",
    body: [
      "The selected dataset file is the revision the table and a queued run use. Built-in files are read-only; create a draft to edit questions.",
    ],
    seeAlso: ["measure.runs.revision"],
    optional: true,
  },
];

const RUNS: HelpTopic[] = [
  {
    id: "measure.runs.suite",
    title: "Golden suite",
    body: [
      "The suite decides the registry, the question language and the corpus language the run filters on; a Korean-question suite over SEC filings exercises cross-lingual retrieval.",
    ],
    seeAlso: ["measure.golden.suite"],
  },
  {
    id: "measure.runs.revision",
    title: "Golden revision",
    body: [
      "Canonical JSON is the read-only default. Pick a revision to score against edited questions; its SHA-256 becomes part of the result identity, so runs on different revisions are not comparable.",
    ],
    seeAlso: ["measure.golden.revision", "measure.compare.overview"],
  },
  {
    id: "measure.runs.mode",
    title: "Run mode",
    body: [
      "Quick evaluates the profile against the current populated index, writes an artifact under data/eval_runs and picks a baseline automatically: the latest result with the same suite, golden SHA-256, corpus fingerprint and k.",
      "Matrix builds isolated corpora for each chunk target and runs lexical and hybrid with each lexical ranker (ts_rank_cd, BM25) plus one vector arm through the CLI runner, persisting one result per arm.",
    ],
    tune: "Use Quick to tune a profile on the corpus you serve; use Matrix when the chunk size itself is the question, since two runs that chunked differently are two experiments, not a baseline and a regression.",
    seeAlso: ["measure.runs.chunk_targets", "measure.runs.profile"],
  },
  {
    id: "measure.runs.chunk_targets",
    title: "Chunk targets",
    body: [
      "Target text characters per chunk for each isolated Matrix corpus, space- or comma-separated; 500 1200 builds two corpora.",
    ],
    tune: "Keep the list short: every target re-parses and re-embeds the suite's filings.",
    seeAlso: ["measure.runs.mode"],
    optional: true,
  },
  {
    id: "measure.runs.profile",
    title: "Retrieval profile",
    body: [
      "The run uses the current review's retrieval profile; the summary shows strategy, lexical ranker, k and reranker. Expand it to change any field for this run.",
      "k here is also the scoring cutoff, so results with a different k cannot be compared.",
    ],
    seeAlso: ["measure.runs.k", "review.preset"],
  },
  ...profileFieldTopics("measure.runs", true),
  {
    id: "measure.runs.queue",
    title: "Queue evaluation",
    body: [
      "Posts the request to /admin/evaluations/runs; a single worker runs jobs in order and the Results list updates as the job moves through golden validation, queries, artifact and persistence.",
      "It is locked until the corpus is ready (Build steps 2–4 done) and on the public build.",
    ],
    seeAlso: ["measure.runs.results", "build.stage.evaluate"],
  },
  {
    id: "measure.runs.results",
    title: "Results",
    body: [
      "One row per job with its suite, mode, status and message. A succeeded quick run that found a compatible baseline offers Compare; a matrix run lists one result per arm.",
      "Start from the evaluation runs list. New evaluation opens setup; queueing adds a job. Select its row to inspect progress and settings, then metrics and cases after success.",
    ],
    seeAlso: ["measure.runs.result_detail", "measure.compare.overview"],
  },
  {
    id: "measure.runs.use_selected",
    title: "Use selected set",
    body: [
      "Copies the selected result's retrieval profile into the active review as a Custom preset, sets the corpus scope and language from the suite, and opens Ask.",
    ],
    seeAlso: ["review.preset", "measure.snapshots.freeze"],
  },
  {
    id: "measure.runs.result_detail",
    title: "Result details",
    body: [
      "recall@k is the share of unique gold spans covered by a top-k hit, where a hit covers a span when at least half of the span lies inside the chunk from the same source file.",
      "hit rate@k is the share of cases with at least one covering hit; MRR averages 1 / first relevant rank. The config block records the profile and identity the numbers depend on.",
    ],
    seeAlso: ["measure.runs.k", "measure.golden.questions"],
  },
];

const COMPARE: HelpTopic[] = [
  {
    id: "measure.compare.overview",
    title: "Compare",
    body: [
      "Candidate versus baseline for one quick run: each metric shows the candidate value and its delta, computed from the two stored artifacts without running retrieval again.",
      "Two results compare only when they share the suite, the golden and corpus identity, and k; otherwise the request is rejected.",
      "Open it with Compare on a succeeded quick run in Runs; the Build Evaluate card queues a quick run on a live build and opens Snapshots on a public one, it does not open this tab.",
    ],
    seeAlso: ["measure.runs.results", "measure.snapshots.compare"],
  },
  {
    id: "measure.compare.cases",
    title: "Case changes",
    body: [
      "Per-case transitions between the two runs, such as miss to hit or a rank moving up or down, so a metric delta can be traced to the questions that caused it.",
    ],
    seeAlso: ["measure.golden.questions"],
    optional: true,
  },
];

const SNAPSHOTS: HelpTopic[] = [
  {
    id: "measure.snapshots.freeze", capability: "can_build_snapshot", requiredCapabilities: ["can_run_evaluation"],
    title: "Save result as snapshot",
    body: [
      "In Result details, enter a snapshot label and choose Save result as snapshot. It freezes current documents, chunks, embeddings and BM25 with the selected result for later reuse.",
      "Snapshots preserve the recorded dataset identity and search settings in this database. They start private and are removed by an execution data reset.",
    ],
    seeAlso: ["measure.runs.results", "measure.snapshots.list"],
    optional: true,
  },
  {
    id: "measure.snapshots.list", publicContent: {"capabilities": ["can_build_snapshot", "can_query_snapshot", "can_run_evaluation"], "body": ["Browse published snapshots and inspect their labels, document counts, datasets, and recorded results."], "guide": {"summary": "Browse published snapshots and inspect their labels, document counts, datasets, and recorded results.", "steps": ["Open the related control.", "Read the available values or recorded results.", "Open the full guide for details."]}},
    title: "Snapshots",
    body: [
      "Filter snapshots by dataset file and search by filename or snapshot name. Each row shows recorded settings and creation time; View source evaluation opens its original run. Use for review selects its saved search state.",
    ],
    seeAlso: ["review.snapshot", "measure.snapshots.compare"],
  },
  {
    id: "measure.snapshots.compare", capability: "can_compare_published_snapshots",
    title: "Compare stored results",
    body: [
      "Compares the baseline and candidate snapshots from their stored artifacts only; no retrieval and no provider request runs.",
      "When the two snapshots come from different suites or golden revisions a warning appears and every metric delta is hidden as n/a; only cases both snapshots contain are listed.",
    ],
    seeAlso: ["measure.snapshots.comparison", "measure.compare.overview"],
  },
  {
    id: "measure.snapshots.comparison", capability: "can_compare_published_snapshots",
    title: "Snapshot comparison",
    body: [
      "Metric deltas, the number of common cases, and each case's baseline and candidate rank with its transition and rank delta.",
    ],
    seeAlso: ["measure.runs.result_detail"],
  },
];

const BUILD_JOBS: HelpTopic[] = [
  {
    id: "build.jobs.center",
    title: "Job Center",
    body: [
      "Every long operation runs as a persisted job, so a page reload never loses one. Six states: queued and running are live, succeeded, failed and cancelled are terminal, and interrupted means the application restarted mid-flight.",
      "Interrupted work is never resumed automatically, because a half-finished ingest cannot be safely continued from an unknown point. Retry it explicitly; failed and interrupted jobs offer that button, cancelled ones do not.",
      "The detail pane names the error code, a sentence explaining it, the message the job wrote, and the request it was given.",
    ],
    tune: "Cancel only reaches a job that is still queued or running. A stuck job usually means the worker died, which shows as worker_error.",
    seeAlso: ["build.next-step", "build.runtime"],
  },
];

const SYSTEM: HelpTopic[] = [

  {
    id: "system.status", publicContent: {"capabilities": ["can_edit_prompt_policy"], "body": ["Inspect available service health and published corpus readiness. Private inventory totals are withheld."], "guide": {"summary": "Inspect available service health and published corpus readiness. Private inventory totals are withheld.", "steps": ["Open the related control.", "Read the available values or recorded results.", "Open the full guide for details."]}},
    title: "System status",
    body: [
      "The /ready payload as a page: overall status and mode, database and schema state, corpus counters (documents, chunks, embedded, pending, BM25) and the model policy per role.",
      "Review capability names the active answer model or says disabled; the health badge in the top bar summarises the same check.",
    ],
    seeAlso: ["build.runtime", "build.stage.answer_model"],
  },
  {
    id: "system.local-policy", capability: "can_configure_local_llm",
    title: "Local model policy",
    body: [
      "What the local engine serves when a session selects it: answers and citation checks, query translation, intent classification and casual replies.",
      "Changing the local answer server does not change the embedding provider. Stored vectors retain the identity of the model that produced them.",
      "The panel refreshes automatically every 30 seconds while visible, showing connection state, installed models and their capabilities. Unavailable selections cannot receive questions.",
    ],
    tune: "Open Settings › Local LLM and choose Default, or Add a server for another endpoint. Run connection diagnostics before connecting. Failed connection changes preserve the working server. Choose an answer model above the conversation input; connecting does not run a question.",
    seeAlso: ["system.status", "build.stage.answer_model"],
    optional: true,
  },
  {
    id: "system.operations", capability: "can_use_operations", requiredCapabilities: ["can_edit_prompt_policy"],
    title: "Operations",
    body: [
      "Runs allowlisted verification and service commands through the local operator (rag-dev) without opening a shell; output streams into Latest run.",
      "The tab appears only when NEXT_PUBLIC_OPERATOR_BASE_URL and its token are configured for this build.",
      "Cards are grouped by category (Inspect, Verify, Service) with read-only commands first; the filter choice is remembered in this browser.",
    ],
    seeAlso: ["build.runtime"],
    optional: true,
  },
  {
    id: "system.api", capability: "can_run_evaluation", requiredCapabilities: ["can_edit_prompt_policy"],
    title: "API inspector",
    body: [
      "Posts a raw EvaluationRequest to /admin/evaluations/runs and shows the typed response, for reproducing a run outside the form. Live builds only, and disabled while the runtime is not healthy.",
    ],
    seeAlso: ["measure.runs.queue"],
    optional: true,
  },
  {
    id: "system.usage", capability: "can_edit_prompt_policy",
    title: "Usage",
    body: [
      "Provider usage aggregated from locally persisted run traces: requests, input, cached and output tokens, reasoning tokens and the estimated cost per model. It does not query the provider's billing.",
    ],
    seeAlso: ["measure.playground.preview_review"],
    optional: true,
  },
  { id: "system.runtime", publicContent: {"capabilities": ["can_edit_prompt_policy"], "body": ["Read the service request, token, and cost allowances without exposing private server settings."], "guide": {"summary": "Read the service request, token, and cost allowances without exposing private server settings.", "steps": ["Open the related control.", "Read the available values or recorded results.", "Open the full guide for details."]}}, title: "Runtime and allowance details", body: ["Development shows API, database and Operations endpoints here. Deployment shows read-only rate, token and cost allowances."], optional: true },
];

export const HELP_TOPICS: Record<HelpScreen, readonly HelpTopic[]> = {
  build: restrictedTopics(BUILD, "can_build_snapshot"),
  "build.jobs": restrictedTopics(BUILD_JOBS, "can_build_snapshot"),
  "build.documents": [
    { id: "build.documents.filters", title: "Document filters", body: ["Search by company code or name. Choose a fiscal year and expand Filters for source, language, report type and readiness. Remove an applied chip to broaden the list."] },
    { id: "build.documents.list", title: "Document inventory", body: ["Select a document to open its source information and search readiness. Drag the divider on a wide screen to adjust the list width; use Back to documents on a narrow screen."] },
    { id: "build.documents.detail", publicContent: {"capabilities": ["can_build_snapshot"], "body": ["Inspect the original source, citations, and search coverage for a published document."], "guide": {"summary": "Inspect the original source, citations, and search coverage for a published document.", "steps": ["Open the related control.", "Read the available values or recorded results.", "Open the full guide for details."]}}, title: "Document details", body: ["Inspect original source information, chunk coverage and the next preparation step. Public visitors can only inspect filings in published snapshots."], optional: true },
  ],
  review: REVIEW,
  "measure.playground": restrictedTopics(PLAYGROUND, "can_run_evaluation"),
  "measure.golden": restrictedTopics(GOLDEN, "can_run_evaluation"),
  "measure.runs": restrictedTopics(RUNS, "can_run_evaluation"),
  "measure.compare": restrictedTopics(COMPARE, "can_run_evaluation"),
  "measure.snapshots": SNAPSHOTS,
  "measure.presets": [{ id: "measure.presets.manage", title: "Retrieval presets", body: ["Manage reusable search settings separately from the four evaluation steps. Select a preset in a conversation to apply it; saving a preset does not start an evaluation."] }],
  system: SYSTEM.filter((topic) => LOCAL_ENGINE_VISIBLE || topic.id !== "system.local-policy"),
};

const MEASURE_SCREENS: ReadonlySet<string> = new Set(["playground", "golden", "runs", "compare", "snapshots", "presets"]);

/** Map the shell's view and tab to a help screen; null where no topics exist (Build › Documents and Jobs). */
export function helpScreen(view: "review" | "build" | "measure" | "system", tab: string): HelpScreen | null {
  if (view === "review") return "review";
  if (view === "system") return "system";
  if (view === "build") return tab === "pipeline" ? "build" : tab === "jobs" ? "build.jobs" : tab === "documents" ? "build.documents" : null;
  return MEASURE_SCREENS.has(tab) ? `measure.${tab}` as HelpScreen : null;
}

/** Find a topic on any screen, for See also links that point across screens. */
export function findHelpTopic(id: string): HelpTopic | null {
  for (const topics of Object.values(HELP_TOPICS)) {
    const topic = topics.find((item) => item.id === id);
    if (topic) return topic;
  }
  return null;
}
