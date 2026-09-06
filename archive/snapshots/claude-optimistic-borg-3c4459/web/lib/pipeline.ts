import { LOCAL_ENGINE_VISIBLE } from "./build-mode";
import { CANNED_CORPUS } from "./canned";
import type { CorpusCounts, ManifestSummary, OperatorJob, Readiness } from "./types";
import type { RuntimeHealthKind } from "./use-runtime-health";

export type StageId = "filings" | "index" | "embeddings" | "lexical" | "ask" | "answer_model" | "evaluate";
export type StageStatus = "done" | "action" | "running" | "queued" | "failed" | "blocked" | "readonly" | "unknown";
export type StageActionKind = "acquire" | "ingest_all" | "embed" | "bm25" | "ask" | "recheck" | "evaluate" | "compare";

export interface StageAction {
  label: string;
  kind: StageActionKind;
}

export interface Stage {
  id: StageId;
  order: number;
  title: string;
  description: string;
  why: string;
  status: StageStatus;
  /** Short qualifier shown next to the status pill, e.g. "54%", "Queued #2", "after step 2". */
  statusDetail: string;
  /** Real values the stage owns, rendered joined by " · ". */
  numbers: string[];
  /** The next action in one sentence; empty when the stage is done. */
  hint: string;
  action: StageAction | null;
  jobKinds: readonly string[];
  job: OperatorJob | null;
  progress: number | null;
  blockedBy: StageId | null;
}

export interface Pipeline {
  stages: Stage[];
  /** First stage that needs the operator: `action` or `failed`. */
  next: Stage | null;
  /** Stages 1–4 are done, so retrieval runs against a complete index. */
  corpusReady: boolean;
  readOnly: boolean;
  /** `pending`: a live build with neither readiness nor the administrator snapshot yet. */
  source: "admin" | "readiness" | "fixture" | "pending";
}

export interface PipelineInput {
  live: boolean;
  healthKind: RuntimeHealthKind;
  readiness: Readiness | null;
  /** `/admin/corpus.status` once loaded in live mode; `null` falls back to readiness or the fixture. */
  corpus: CorpusCounts | null;
  manifests: ManifestSummary[];
  /** Ingested documents per registry, from `/admin/documents/facets`. */
  registryCounts: Record<string, number>;
  jobs: OperatorJob[];
  evaluationResults: number;
  snapshots: number;
}

export const STAGE_ORDER: readonly StageId[] = ["filings", "index", "embeddings", "lexical", "ask", "answer_model", "evaluate"];

interface StageCopy {
  title: string;
  description: string;
  why: string;
  jobKinds: readonly string[];
}

export const STAGE_COPY: Record<StageId, StageCopy> = {
  filings: {
    title: "Filings",
    description: "Download SEC 10-K and DART business reports into data/corpus.",
    why: "Everything downstream cites these files by SHA-256. Re-running only fetches what is missing.",
    jobKinds: ["acquire_edgar", "acquire_dart"],
  },
  index: {
    title: "Parse & chunk",
    description: "Read each filing, split it into citable text and table chunks, and load them into PostgreSQL.",
    why: "Chunk boundaries decide what can be cited. Every answer must point to a chunk from this step.",
    jobKinds: ["ingest_manifest"],
  },
  embeddings: {
    title: "Embeddings",
    description: "Turn every chunk into a vector so questions can match by meaning, not only by exact words.",
    why: "Vector search is what lets a Korean question find an English filing. Rows carry model identity, so a model change marks old vectors stale until you backfill.",
    jobKinds: ["backfill_embeddings"],
  },
  lexical: {
    title: "Lexical index (BM25)",
    description: "Keyword statistics for exact terms, tickers, numbers and Korean tokens. Recomputed automatically after every ingest.",
    why: "Hybrid retrieval fuses this index with embeddings (RRF). Rebuild by hand only if the statistics were reset.",
    jobKinds: ["rebuild_bm25"],
  },
  ask: {
    title: "Ask",
    description: "Retrieve evidence for a question across both indexes, then let the model answer only from it.",
    why: "Unsupported answers end as NOT_IN_DOCS. Retrieval quality, not the model, decides most outcomes.",
    jobKinds: [],
  },
  answer_model: {
    title: "Answer model",
    description: "The LLM that writes the answer and checks every citation. Optional: without it, Ask still returns evidence.",
    why: "The model never sees the corpus directly, only the evidence from step 5. Provider failures are shown as failures, never disguised as NOT_IN_DOCS.",
    jobKinds: [],
  },
  evaluate: {
    title: "Evaluate",
    description: "Score retrieval against golden questions so you can trust, or fix, the steps above.",
    why: "Recall@k, hit rate and MRR measure retrieval only, not answer factuality. Freeze a good result as a snapshot to keep it comparable.",
    jobKinds: ["quick", "matrix"],
  },
};

const OPENAI_KEY_HINT = "No answer model. In dev, set OPENAI_API_KEY_LOCAL in .env (OPENAI_API_KEY_PROD is used when MODE=prod), then run docker compose up -d app.";
const EVIDENCE_ONLY_HINT = "Ask keeps working in evidence-only mode.";
/** A public build never names the local engine, because that build cannot run one. */
export const ANSWER_MODEL_HINT = LOCAL_ENGINE_VISIBLE
  ? `${OPENAI_KEY_HINT} For a local model set LOCAL_LLM_BASE_URL and LOCAL_LLM_MODEL instead. ${EVIDENCE_ONLY_HINT}`
  : `${OPENAI_KEY_HINT} ${EVIDENCE_ONLY_HINT}`;

export function stageStatusLabel(status: StageStatus): string {
  switch (status) {
    case "done": return "Done";
    case "action": return "Action needed";
    case "running": return "Running";
    case "queued": return "Queued";
    case "failed": return "Failed";
    case "blocked": return "Blocked";
    case "readonly": return "Read-only";
    default: return "Checking…";
  }
}

const READ_ONLY_STAGES: ReadonlySet<StageId> = new Set(["filings", "index", "embeddings", "lexical", "evaluate"]);

/** Unknown counts for a live build that has not heard from the API yet; every stage reports "Checking…". */
const PENDING_COUNTS: CorpusCounts = {
  database_connected: null,
  schema_status: null,
  schema_message: null,
  documents: null,
  chunks: null,
  embedded_chunks: null,
  pending_embeddings: null,
  bm25_ready: null,
  writable: null,
};

function count(value: number | null | undefined): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function n(value: number): string {
  return value.toLocaleString("en-US");
}

function registryLabel(registry: string | null): string {
  return (registry ?? "other").toUpperCase();
}

function stepRef(order: number, title: string): string {
  return `step ${order} · ${title}`;
}

interface Draft {
  status: StageStatus;
  statusDetail?: string;
  numbers?: string[];
  hint?: string;
  action?: StageAction | null;
  blockedBy?: StageId | null;
}

/**
 * Derive the seven build stages from readiness, the administrator snapshot, and the
 * job board. Pure: the same inputs always produce the same stages, so the rules are
 * testable without rendering.
 */
export function derivePipeline(input: PipelineInput): Pipeline {
  const readOnly = !input.live || input.readiness?.mode === "canned";
  const readinessCorpus = input.readiness && input.readiness.corpus.availability !== "not_applicable"
    ? input.readiness.corpus
    : null;
  // A live build never derives real state from the portfolio fixture; it waits.
  const fixtureAllowed = !input.live;
  const source: Pipeline["source"] = input.corpus ? "admin" : readinessCorpus ? "readiness" : fixtureAllowed ? "fixture" : "pending";
  const counts: CorpusCounts = input.corpus ?? readinessCorpus ?? (fixtureAllowed ? CANNED_CORPUS.status : PENDING_COUNTS);
  const manifests = source === "admin" ? input.manifests.filter((item) => item.valid) : source === "fixture" ? CANNED_CORPUS.manifests : [];
  const documents = count(counts.documents);
  const chunks = count(counts.chunks);
  const embedded = count(counts.embedded_chunks);
  const pending = count(counts.pending_embeddings);
  const bm25Ready = counts.bm25_ready === true;
  const schemaBroken = input.live && (counts.database_connected === false || counts.schema_status === "drifted" || counts.schema_status === "unavailable");
  const schemaMessage = counts.schema_message || "The database or its schema is unavailable.";

  const drafts: Record<StageId, Draft> = {
    filings: filingsDraft(manifests, documents, counts.writable, source, readOnly),
    index: { status: "unknown" },
    embeddings: { status: "unknown" },
    lexical: { status: "unknown" },
    ask: { status: "unknown" },
    answer_model: answerModelDraft(input.readiness),
    evaluate: { status: "unknown" },
  };

  const filingsDone = drafts.filings.status === "done" || drafts.filings.status === "readonly";
  // Before the administrator snapshot arrives the filings state is unknown; downstream
  // stages report "Checking…" instead of a misleading "download filings first".
  const filingsUnknown = drafts.filings.status === "unknown";
  const checking: Draft = { status: "unknown", statusDetail: "Checking…", numbers: [] };
  const indexDone = documents > 0 && chunks > 0;
  const embeddingsDone = chunks > 0 && pending === 0;
  const lexicalDone = bm25Ready;
  const provider = counts.provider ? ` · ${counts.provider}` : "";

  // Step 2 — Parse & chunk
  {
    const numbers = [`${n(documents)} documents`, `${n(chunks)} chunks`];
    // Registry facets describe the ingested corpus only when their total matches the
    // document count; a failed facets call must not read as "nothing ingested".
    const facetTotal = Object.values(input.registryCounts).reduce((sum, value) => sum + count(value), 0);
    const facetsKnown = facetTotal > 0 && facetTotal === documents;
    const gaps = facetsKnown
      ? manifests
        .filter((item) => item.registry && count(item.documents) > count(input.registryCounts[item.registry]))
        .map((item) => ({ registry: item.registry, gap: count(item.documents) - count(input.registryCounts[item.registry as string]) }))
      : [];
    let hint = "";
    if (source === "admin" && indexDone && gaps.length) {
      for (const item of gaps) numbers.push(`${n(item.gap)} listed filing${item.gap === 1 ? "" : "s"} not ingested yet (${registryLabel(item.registry)})`);
      hint = "Re-run Ingest all manifests to add them.";
    }
    if (indexDone) drafts.index = { status: "done", numbers, hint };
    else if (schemaBroken) drafts.index = { status: "blocked", statusDetail: "database", numbers, hint: schemaMessage };
    else if (filingsUnknown) drafts.index = { ...checking };
    else if (!filingsDone) drafts.index = { status: "blocked", statusDetail: `after ${stepRef(1, "Filings")}`, numbers: ["Nothing ingested yet."], hint: "Download filings first (step 1).", blockedBy: "filings" };
    else drafts.index = { status: "action", numbers: ["Nothing ingested yet."], hint: "Pick the manifests that list your filings and run Ingest all manifests." };
    drafts.index.action = { label: "Ingest all manifests", kind: "ingest_all" };
  }

  // Step 3 — Embeddings
  {
    const numbers = [`${n(embedded)} embedded`, `${n(pending)} pending${provider}`];
    if (embeddingsDone) drafts.embeddings = { status: "done", numbers };
    else if (schemaBroken) drafts.embeddings = { status: "blocked", statusDetail: "database", numbers, hint: schemaMessage };
    else if (drafts.index.status === "unknown") drafts.embeddings = { ...checking };
    else if (!indexDone) drafts.embeddings = { status: "blocked", statusDetail: `after ${stepRef(2, "Parse & chunk")}`, numbers: ["No chunks to embed yet."], hint: "Ingest a manifest first (step 2).", blockedBy: "index" };
    else drafts.embeddings = { status: "action", numbers, hint: `${n(pending)} chunk${pending === 1 ? " still needs" : "s still need"} vectors. Run Backfill embeddings.` };
    drafts.embeddings.action = { label: "Backfill embeddings", kind: "embed" };
  }

  // Step 4 — Lexical index
  {
    const numbers = [bm25Ready ? "BM25 ready" : "BM25 not built"];
    if (lexicalDone) drafts.lexical = { status: "done", numbers };
    else if (schemaBroken) drafts.lexical = { status: "blocked", statusDetail: "database", numbers, hint: schemaMessage };
    else if (drafts.index.status === "unknown") drafts.lexical = { ...checking };
    else if (!indexDone) drafts.lexical = { status: "blocked", statusDetail: `after ${stepRef(2, "Parse & chunk")}`, numbers, hint: "Ingest a manifest first (step 2).", blockedBy: "index" };
    else drafts.lexical = { status: "action", numbers, hint: "Run Rebuild BM25 to compute the term statistics." };
    drafts.lexical.action = { label: "Rebuild BM25", kind: "bm25" };
  }

  // Step 5 — Ask
  {
    if (drafts.index.status === "unknown") {
      drafts.ask = { ...checking };
    } else if (chunks > 0) {
      const detail = embeddingsDone && lexicalDone ? "hybrid ready" : embeddingsDone ? "vector ready · BM25 pending" : lexicalDone ? "lexical only · embeddings pending" : "retrieval limited";
      drafts.ask = { status: "done", statusDetail: detail, numbers: [`${n(chunks)} chunks searchable`] };
    } else {
      drafts.ask = { status: "blocked", statusDetail: "corpus is empty", numbers: ["Nothing to search yet."], hint: "Finish steps 1–2 to enable retrieval.", blockedBy: "index" };
    }
    drafts.ask.action = { label: "Ask a question", kind: "ask" };
  }

  // Step 7 — Evaluate
  {
    const succeeded = input.jobs.some((job) => job.domain === "evaluation" && job.status === "succeeded");
    const measured = readOnly ? input.snapshots > 0 : input.evaluationResults > 0 || succeeded;
    const numbers = readOnly
      ? [`${n(input.snapshots)} published snapshot${input.snapshots === 1 ? "" : "s"}`]
      : [`${n(input.evaluationResults)} result${input.evaluationResults === 1 ? "" : "s"}`, `${n(input.snapshots)} snapshot${input.snapshots === 1 ? "" : "s"}`];
    if (source === "pending" || drafts.index.status === "unknown") drafts.evaluate = { ...checking };
    else if (measured) drafts.evaluate = { status: "done", numbers };
    else if (chunks === 0) drafts.evaluate = { status: "blocked", statusDetail: "after steps 2–4", numbers: ["Not measured yet."], hint: "Finish retrieval (steps 1–4) first.", blockedBy: "index" };
    else drafts.evaluate = { status: "action", numbers: ["Not measured yet."], hint: "Queue a quick evaluation on the sec-en suite, then compare results and freeze a snapshot." };
    drafts.evaluate.action = readOnly
      ? { label: "Compare published snapshots", kind: "compare" }
      : { label: "Run quick evaluation", kind: "evaluate" };
  }

  const stages: Stage[] = STAGE_ORDER.map((id, index) => {
    const copy = STAGE_COPY[id];
    const draft = drafts[id];
    let status = draft.status;
    let statusDetail = draft.statusDetail ?? "";
    let hint = draft.hint ?? "";
    let action = draft.action ?? null;
    let numbers = draft.numbers ?? [];
    let job: OperatorJob | null = null;
    let progress: number | null = null;

    if (readOnly && READ_ONLY_STAGES.has(id)) {
      // Keep the action so the card can render it disabled with the read-only note.
      status = "readonly";
      statusDetail = source === "fixture" ? "Portfolio fixture" : "stored";
      hint = "";
    }

    if (!readOnly && input.live && copy.jobKinds.length) {
      const running = input.jobs.find((item) => copy.jobKinds.includes(item.kind) && item.status === "running") ?? null;
      const queued = input.jobs.find((item) => copy.jobKinds.includes(item.kind) && item.status === "queued") ?? null;
      const latest = input.jobs.find((item) => copy.jobKinds.includes(item.kind)) ?? null;
      if (running) {
        job = running;
        progress = running.total ? Math.min(100, Math.round((running.current / Math.max(running.total, 1)) * 100)) : null;
        status = "running";
        statusDetail = progress === null ? running.stage : `${progress}%`;
        hint = running.message;
      } else if (queued) {
        job = queued;
        status = "queued";
        statusDetail = queued.queue_position ? `Queued #${queued.queue_position}` : "Queued";
        hint = "Waiting for the current job to finish.";
      } else if (latest && (latest.status === "failed" || latest.status === "interrupted") && status !== "done") {
        job = latest;
        status = "failed";
        statusDetail = latest.error_code ?? latest.status;
        hint = `Last run ${latest.status}: ${latest.message}`;
      }
    }

    if (input.healthKind === "api_down") {
      status = "unknown";
      statusDetail = "API unavailable";
      hint = "";
      action = null;
      numbers = [];
      job = null;
      progress = null;
    }

    return {
      id,
      order: index + 1,
      title: copy.title,
      description: copy.description,
      why: copy.why,
      status,
      statusDetail,
      numbers,
      hint,
      action,
      jobKinds: copy.jobKinds,
      job,
      progress,
      blockedBy: draft.blockedBy ?? null,
    };
  });

  const next = stages.find((stage) => stage.status === "action" || stage.status === "failed") ?? null;
  const corpusReady = stages.slice(0, 4).every((stage) => stage.status === "done" || stage.status === "readonly");
  return { stages, next, corpusReady, readOnly, source };
}

function filingsDraft(manifests: ManifestSummary[], documents: number, writable: boolean | null, source: Pipeline["source"], readOnly: boolean): Draft {
  const action: StageAction = { label: "Download missing filings", kind: "acquire" };
  if (readOnly || source === "readiness" || source === "pending") {
    const label = readOnly ? "filings in the published corpus" : "filings ingested";
    const numbers = source === "pending" ? [] : [`${n(documents)} ${label}`];
    return { status: readOnly ? "readonly" : "unknown", statusDetail: readOnly ? "" : "Checking…", numbers, action };
  }
  const total = manifests.reduce((sum, item) => sum + count(item.documents), 0);
  const present = manifests.reduce((sum, item) => sum + count(item.sources_present), 0);
  const perRegistry = manifests.map((item) => `${registryLabel(item.registry)} ${n(count(item.sources_present))}/${n(count(item.documents))}`);
  if (writable === false) {
    return { status: "blocked", statusDetail: "data/ not writable", numbers: [`${n(present)} / ${n(total)} filings on disk`, ...perRegistry], hint: "Set HOST_GID=<id -g> in .env and restart the app so the container can write data/.", action };
  }
  if (total === 0) {
    return { status: "action", numbers: ["No filings yet."], hint: "Choose a registry, keep the default tickers and fiscal years, then run Download missing filings.", action };
  }
  if (present >= total) {
    return { status: "done", numbers: [`${n(present)} / ${n(total)} filings on disk`, ...perRegistry], action };
  }
  const missing = total - present;
  return { status: "action", numbers: [`${n(present)} / ${n(total)} filings on disk`, ...perRegistry], hint: `${n(missing)} listed filing${missing === 1 ? " is" : "s are"} not on disk yet. Run Download missing filings.`, action };
}

function answerModelDraft(readiness: Readiness | null): Draft {
  if (!readiness) return { status: "unknown", statusDetail: "Checking…", numbers: [] };
  const engines = readiness.review_engines ?? {};
  const openai = engines.openai ?? {};
  const local = engines.local ?? {};
  if (readiness.mode === "canned") {
    return { status: "readonly", statusDetail: "Public demo", numbers: ["Public demo replays stored answers; no provider is called."], action: null };
  }
  if (readiness.review_enabled) {
    const numbers: string[] = [];
    if (openai.enabled) numbers.push(`OpenAI · ${openai.model ?? readiness.active_review_model ?? "configured"}${openai.key_slot ? ` · ${openai.key_slot} key` : ""}`);
    if (LOCAL_ENGINE_VISIBLE && local.enabled) numbers.push(`Local · ${local.model ?? "configured"}`);
    // A public build suppresses the local row, so say something rather than nothing.
    if (!numbers.length) numbers.push("Configured");
    return { status: "done", numbers, action: null };
  }
  return {
    status: "blocked",
    statusDetail: "No answer model",
    numbers: LOCAL_ENGINE_VISIBLE
      ? [`openai · ${openai.enabled ? "enabled" : "disabled"}`, `local · ${local.reason ?? (local.enabled ? "enabled" : "not configured")}`]
      : [`openai · ${openai.enabled ? "enabled" : "disabled"}`],
    hint: ANSWER_MODEL_HINT,
    action: { label: "Re-check", kind: "recheck" },
  };
}

/**
 * Turn one run failure into a sentence that names the cause.
 *
 * Matching is on `failure.status`, whose four values are a closed contract, rather than
 * on `node`. Only the exception class at the head of `details[0]` is parsed; the text
 * after it is a provider message and not a contract. Advice that only an operator can
 * act on is withheld from a public build, which cannot run a local model at all.
 */
export function failureMessage(failure: Record<string, unknown>): string {
  const detail = JSON.stringify(failure);
  if (/AuthenticationError|token_invalidated|invalidated/i.test(detail)) {
    return "OpenAI API authentication failed. Update the server-side API key and retry.";
  }
  const status = String(failure.status ?? failure.code ?? "provider failure");
  if (status === "schema_rejected") {
    const advice = LOCAL_ENGINE_VISIBLE
      ? " Smaller local models often fail structured output; try the OpenAI engine for this question."
      : "";
    return `The model returned output that did not match the required schema.${advice}`;
  }
  if (status === "budget_exceeded") {
    const node = typeof failure.node === "string" ? ` at the ${failure.node} step` : "";
    return `The run exceeded its token budget${node}.`;
  }
  if (status === "provider_error" && LOCAL_ENGINE_VISIBLE) {
    if (/ReadTimeout|ConnectTimeout|TimeoutException/i.test(detail)) {
      return "The model did not answer within the time limit. Raise LOCAL_LLM_TIMEOUT_S, or choose a smaller model.";
    }
    if (/ConnectError|Connection refused|ConnectionError/i.test(detail)) {
      return "The model host is unreachable. Check that the local-llm compose profile is running.";
    }
  }
  return `The answer could not be generated (${status}).`;
}
