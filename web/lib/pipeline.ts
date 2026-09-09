import { answerEngineStates, answerEngineSummary } from "./answer-engine-state";
import { LOCAL_ENGINE_VISIBLE } from "./build-mode";
import { CANNED_CORPUS } from "./canned";
import type { CorpusSnapshot, CorpusCounts, ManifestSummary, OperatorJob, Readiness, RetrievalProfile } from "./types";
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
  /** A failed connection check is retrying while last-known readiness is retained. */
  connectionPending?: boolean;
  readiness: Readiness | null;
  /** `/admin/corpus.status` once loaded in live mode; `null` falls back to readiness or the fixture. */
  corpus: CorpusCounts | null;
  manifests: ManifestSummary[];
  sourceInventory?: NonNullable<CorpusSnapshot["sources"]>;
  sourceSelection?: { complete: boolean; present: unknown[]; missing: string[] };
  /** Ingested documents per registry, from `/admin/documents/facets`. */
  registryCounts: Record<string, number>;
  jobs: OperatorJob[];
  evaluationResults: number;
  snapshots: number;
  profile?: RetrievalProfile;
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
    jobKinds: ["acquire_edgar", "acquire_dart", "delete_sources"],
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
    description: "Compute keyword statistics for exact terms, tickers, numbers and Korean tokens after each parse and chunk operation.",
    why: "Step 4 owns BM25 computation. Hybrid retrieval requires this index and embeddings; chunk changes invalidate the statistics.",
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
  ? `${OPENAI_KEY_HINT} For a local model connect a server in Settings › Local LLM, then select a discovered model above the conversation input. ${EVIDENCE_ONLY_HINT}`
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

/** Use reported job-wide units only; running work cannot claim final completion. */
export function overallJobPercent(job: OperatorJob): number | null {
  if (typeof job.overall_current !== "number" || !Number.isFinite(job.overall_current)
    || typeof job.overall_total !== "number" || !Number.isFinite(job.overall_total) || job.overall_total <= 0) return null;
  return Math.max(0, Math.min(job.status === "succeeded" ? 100 : 99, Math.round(job.overall_current / job.overall_total * 100)));
}

/** Share strategy prerequisites between the pipeline and the question composer. */
export function retrievalReadiness(counts: CorpusCounts | null, strategy: RetrievalProfile["strategy"], jobs: OperatorJob[] = []): {
  status: "done" | "blocked" | "running" | "queued" | "unknown";
  blockedBy: "index" | "embeddings" | "lexical" | null;
  hint: string;
} {
  if (!counts) return { status: "unknown", blockedBy: null, hint: "Checking corpus…" };
  if (counts.database_connected === false || ["empty", "drifted", "unavailable"].includes(counts.schema_status ?? "")) {
    return { status: "blocked", blockedBy: "index", hint: "Resolve database setup before continuing." };
  }
  if (counts.database_connected !== true || !["ok", "compatible"].includes(counts.schema_status ?? "")
    || counts.chunks == null || counts.pending_embeddings == null && strategy !== "lexical") {
    return { status: "unknown", blockedBy: null, hint: "Readiness not confirmed" };
  }
  if (!counts.chunks) return { status: "blocked", blockedBy: "index", hint: "Finish steps 1–2 to enable retrieval." };
  for (const prerequisite of ["embeddings", "lexical"] as const) {
    if (prerequisite === "embeddings" && strategy === "lexical" || prerequisite === "lexical" && strategy === "vector") continue;
    const kind = prerequisite === "embeddings" ? "backfill_embeddings" : "rebuild_bm25";
    const active = jobs.find((job) => job.domain === "corpus" && job.kind === kind && job.status === "running")
      ?? jobs.find((job) => job.domain === "corpus" && job.kind === kind && job.status === "queued");
    if (active) return { status: active.status as "running" | "queued", blockedBy: prerequisite, hint: prerequisite === "embeddings" ? "Embeddings are in progress (step 3). Ask when they finish." : "BM25 is in progress (step 4). Ask when it finishes." };
    const done = prerequisite === "embeddings" ? counts.pending_embeddings === 0 : counts.bm25_ready === true;
    if (!done) return { status: "blocked", blockedBy: prerequisite, hint: prerequisite === "embeddings" ? "Complete Embeddings (step 3) before asking." : "Complete BM25 (step 4) before asking." };
  }
  return { status: "done", blockedBy: null, hint: "" };
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
  const connectionUnconfirmed = input.healthKind === "checking" || input.connectionPending === true;
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
  const schemaHint = "Resolve database setup before continuing.";

  const drafts: Record<StageId, Draft> = {
    filings: filingsDraft(manifests, documents, counts.writable, source, readOnly, input.sourceSelection),
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
  const embeddingsDone = chunks > 0 && counts.pending_embeddings === 0;
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
        .filter((item) => item.registries.length === 1 && count(item.documents) > count(input.registryCounts[item.registries[0]]))
        .map((item) => ({ registry: item.registries[0], gap: count(item.documents) - count(input.registryCounts[item.registries[0]]) }))
      : [];
    const downloadedCounts: Record<string, number> = {};
    if (input.sourceInventory) {
      for (const source of new Map(input.sourceInventory.filter((source) => source.on_disk && source.ready).map((source) => [source.document_id, source])).values()) downloadedCounts[source.registry] = (downloadedCounts[source.registry] ?? 0) + 1;
    } else {
      for (const manifest of manifests) if (manifest.registries.length === 1) downloadedCounts[manifest.registries[0]] = Math.max(downloadedCounts[manifest.registries[0]] ?? 0, count(manifest.sources_present));
    }
    const newOriginals = source === "admin" && indexDone && facetsKnown && Object.entries(downloadedCounts).some(([registry, available]) => available > count(input.registryCounts[registry]));
    let hint = "";
    if (source === "admin" && indexDone && gaps.length) {
      for (const item of gaps) numbers.push(`${n(item.gap)} listed filing${item.gap === 1 ? "" : "s"} not ingested yet (${registryLabel(item.registry)})`);
      hint = "Re-run Ingest selected sources to add them.";
    }
    if (schemaBroken) drafts.index = { status: "blocked", statusDetail: "Database setup required", numbers, hint: schemaHint };
    else if (indexDone) drafts.index = { status: "done", statusDetail: newOriginals ? "Complete · new originals available" : undefined, numbers, hint: newOriginals ? "New downloaded originals can be parsed and chunked. Select them and run Ingest selected sources." : hint };
    else if (filingsUnknown) drafts.index = { ...checking };
    else if (!filingsDone) drafts.index = { status: "blocked", statusDetail: `after ${stepRef(1, "Filings")}`, numbers: ["No parsed and chunked documents have been stored in the database yet."], hint: "Download filings first (step 1).", blockedBy: "filings" };
    else drafts.index = { status: "action", numbers: ["No parsed and chunked documents have been stored in the database yet."], hint: "Run parsing and chunking for the selected sources." };
    drafts.index.action = { label: "Ingest selected sources", kind: "ingest_all" };
  }

  // Step 3 — Embeddings
  {
    const numbers = [`${n(embedded)} embedded`, `${n(pending)} pending${provider}`];
    if (schemaBroken) drafts.embeddings = { status: "blocked", statusDetail: `after ${stepRef(2, "Parse & chunk")}`, numbers, hint: schemaHint, blockedBy: "index" };
    else if (embeddingsDone) drafts.embeddings = { status: "done", numbers };
    else if (drafts.index.status === "unknown") drafts.embeddings = { ...checking };
    else if (!indexDone) drafts.embeddings = { status: "blocked", statusDetail: `after ${stepRef(2, "Parse & chunk")}`, numbers: ["No chunks to embed yet."], hint: "Ingest a manifest first (step 2).", blockedBy: "index" };
    else drafts.embeddings = { status: "action", numbers, hint: `${n(pending)} chunk${pending === 1 ? " still needs" : "s still need"} vectors. Run Backfill embeddings.` };
    drafts.embeddings.action = { label: "Backfill embeddings", kind: "embed" };
  }

  // Step 4 — Lexical index
  {
    const needsUpdate = !bm25Ready && counts.bm25_rebuild_recorded === true;
    const numbers = [bm25Ready ? "BM25 ready" : needsUpdate ? "Keyword index update required" : "BM25 not built"];
    if (schemaBroken) drafts.lexical = { status: "blocked", statusDetail: `after ${stepRef(2, "Parse & chunk")}`, numbers, hint: schemaHint, blockedBy: "index" };
    else if (lexicalDone) drafts.lexical = { status: "done", numbers };
    else if (drafts.index.status === "unknown") drafts.lexical = { ...checking };
    else if (!indexDone) drafts.lexical = { status: "blocked", statusDetail: `after ${stepRef(2, "Parse & chunk")}`, numbers, hint: "Ingest a manifest first (step 2).", blockedBy: "index" };
    else drafts.lexical = { status: "action", statusDetail: needsUpdate ? "Update required" : undefined, numbers, hint: needsUpdate ? "Update the keyword index to match the parsing and chunking results." : "Compute BM25 after parsing and chunking, or recompute it after chunk changes." };
    drafts.lexical.action = { label: bm25Ready || counts.bm25_rebuild_recorded ? "Recompute BM25" : "Compute BM25", kind: "bm25" };
  }

  // Step 5 — Ask
  {
    if (schemaBroken) {
      drafts.ask = { status: "blocked", statusDetail: `after ${stepRef(2, "Parse & chunk")}`, numbers: [], hint: schemaHint, blockedBy: "index" };
    } else if (drafts.index.status === "unknown") {
      drafts.ask = { ...checking };
    } else if (chunks > 0) {
      const strategy = input.profile?.strategy ?? "hybrid";
      const readiness = source === "fixture"
        ? { status: "done" as const, blockedBy: null, hint: "" }
        : retrievalReadiness(counts, strategy, readOnly ? [] : input.jobs);
      drafts.ask = { ...readiness, statusDetail: readiness.status === "done" ? `${strategy} ready` : readiness.hint, numbers: readiness.status === "done" ? [`${n(chunks)} chunks searchable`] : [] };
    } else {
      drafts.ask = { status: "blocked", statusDetail: `after ${stepRef(2, "Parse & chunk")}`, numbers: ["Nothing to search yet."], hint: "Finish steps 1–2 to enable retrieval.", blockedBy: "index" };
    }
    drafts.ask.action = { label: "Ask a question", kind: "ask" };
  }

  // Step 7 — Evaluate
  {
    const succeeded = input.jobs.some((job) => job.domain === "evaluation" && job.status === "succeeded");
    const measured = readOnly ? input.snapshots > 0 : input.evaluationResults > 0;
    const numbers = readOnly
      ? [`${n(input.snapshots)} published snapshot${input.snapshots === 1 ? "" : "s"}`]
      : [`${n(input.evaluationResults)} result${input.evaluationResults === 1 ? "" : "s"}`, `${n(input.snapshots)} snapshot${input.snapshots === 1 ? "" : "s"}`];
    if (schemaBroken) drafts.evaluate = { status: "blocked", statusDetail: `after ${stepRef(2, "Parse & chunk")}`, numbers, hint: schemaHint, blockedBy: "index" };
    else if (source === "pending" || drafts.index.status === "unknown") drafts.evaluate = { ...checking };
    else if (measured) drafts.evaluate = { status: "done", numbers };
    else if (chunks === 0) drafts.evaluate = { status: "blocked", statusDetail: `after ${stepRef(2, "Parse & chunk")}`, numbers: ["Not measured yet."], hint: "Finish retrieval (steps 1–4) first.", blockedBy: "index" };
    else drafts.evaluate = { status: "action", statusDetail: succeeded ? "No results" : "Not run", numbers: readOnly ? ["Not measured yet."] : numbers, hint: succeeded ? "A job finished, but no evaluation results are available. Refresh results or run a quick evaluation to measure retrieval quality." : "Queue a quick evaluation on the sec-en suite, then compare results and freeze a snapshot." };
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
        progress = overallJobPercent(running);
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

    if (input.healthKind === "api_down" || connectionUnconfirmed) {
      status = "unknown";
      statusDetail = input.healthKind === "api_down" ? "API unavailable" : "Checking…";
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
      blockedBy: input.healthKind === "api_down" || connectionUnconfirmed ? null : draft.blockedBy ?? null,
    };
  });

  const next = stages.find((stage) => stage.status === "action" || stage.status === "failed" || (stage.status === "blocked" && stage.id !== "answer_model")) ?? null;
  const corpusReady = stages.slice(0, 4).every((stage) => stage.status === "done" || stage.status === "readonly");
  return { stages, next, corpusReady, readOnly, source };
}

function filingsDraft(manifests: ManifestSummary[], documents: number, writable: boolean | null, source: Pipeline["source"], readOnly: boolean, selection?: PipelineInput["sourceSelection"]): Draft {
  const action: StageAction = { label: "Download missing filings", kind: "acquire" };
  if (readOnly || source === "readiness" || source === "pending") {
    const label = readOnly ? "filings in the published corpus" : "filings ingested";
    const numbers = source === "pending" ? [] : [`${n(documents)} ${label}`];
    return { status: readOnly ? "readonly" : "unknown", statusDetail: readOnly ? "" : "Checking…", numbers, action };
  }
  const total = manifests.reduce((sum, item) => sum + count(item.documents), 0);
  const present = manifests.reduce((sum, item) => sum + count(item.sources_present), 0);
  const perRegistry = manifests.map((item) => `${registryLabel(item.registries.join(" / "))} ${n(count(item.sources_present))}/${n(count(item.documents))}`);
  if (writable === false) {
    return { status: "blocked", statusDetail: "data/ not writable", numbers: [`${n(present)} / ${n(total)} filings on disk`, ...perRegistry], hint: "Set HOST_GID=<id -g> in .env and restart the app so the container can write data/.", action };
  }
  if (selection) {
    return { status: selection.complete ? "done" : "action", numbers: [`${n(selection.present.length)} / ${n(selection.present.length + selection.missing.length)} filings on disk`], hint: selection.complete ? "" : "Choose companies and fiscal years, then download the selected sources.", action };
  }
  if (total === 0) {
    return { status: "action", numbers: ["No filings yet."], hint: "Choose companies, keep the default fiscal years, then run Download missing filings.", action };
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
  const states = answerEngineStates(readiness).filter((engine) => LOCAL_ENGINE_VISIBLE || engine.id === "openai");
  if (states.some((engine) => engine.light === "green")) {
    const numbers: string[] = [];
    if (openai.enabled) numbers.push(`OpenAI · ${openai.model ?? readiness.active_review_model ?? "configured"}${openai.key_slot ? ` · ${openai.key_slot} key` : ""}`);
    if (LOCAL_ENGINE_VISIBLE && local.enabled) numbers.push(`Local · ${local.model ?? "configured"}`);
    // A public build suppresses the local row, so say something rather than nothing.
    if (!numbers.length) numbers.push("Configured");
    return { status: "done", statusDetail: answerEngineSummary(states), numbers, action: null };
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

/** A settings destination that would let the reader change the limit they just hit. */
export interface FailureFix {
  label: string;
  category: "limits" | "runtime" | "documents" | "jobs";
}

export interface FailureReport {
  text: string;
  /** Absent when no reachable setting would change the outcome. */
  fix?: FailureFix;
}

/** Where the workflow Budget fields are edited; the label matches the Settings nav. */
const RUN_LIMITS: FailureFix = { label: "Open run limits", category: "limits" };

/**
 * Explain one run failure and, where one exists, name the setting that would change it.
 *
 * Budget failures carry `resource`, which says which ceiling stopped the run; a
 * wall-clock stop is not a token budget and pointing at the wrong field wastes the
 * reader's time. Provider failures are matched on `status`, whose four values are a
 * closed contract. Only the exception class at the head of `details[0]` is read, because
 * the provider text after it is not one. Advice an operator alone can act on, and the
 * Settings categories a public build does not render, are withheld from that build.
 */
export function failureReport(failure: Record<string, unknown>, developer = LOCAL_ENGINE_VISIBLE): FailureReport {
  if (failure.code === "query_scope_unavailable") {
    if (!developer) return { text: "Corpus metadata is unavailable. Try again later." };
    const causes: Record<string, string> = {
      missing_file: "The corpus manifest file is missing.",
      invalid_json: "The corpus manifest is not valid JSON.",
      invalid_manifest: "The corpus manifest does not satisfy its data contract.",
      alias_conflict: "Company aliases conflict in the corpus manifest.",
      permission: "The API cannot read the corpus manifest because access was denied.",
    };
    const job = failure.corpus_job && typeof failure.corpus_job === "object" ? failure.corpus_job as Record<string, unknown> : null;
    return { text: causes[String(failure.cause)] ?? "Corpus metadata is unavailable. Inspect the manifest.", fix: job?.job_id ? { label: "Open Jobs", category: "jobs" } : { label: "Open Documents", category: "documents" } };
  }
  const detail = JSON.stringify(failure);
  if (/AuthenticationError|token_invalidated|invalidated/i.test(detail)) {
    return { text: "OpenAI API authentication failed. Update the server-side API key and retry." };
  }
  const status = String(failure.status ?? failure.code ?? "provider failure");
  const at = (key: string) => (typeof failure[key] === "string" ? ` at the ${String(failure[key])} step` : "");
  const tried = typeof failure.attempts === "number" && failure.attempts > 1 ? ` after ${failure.attempts} attempts` : "";

  if (status === "budget_exceeded" && failure.code === "provider_failure") {
    const budget = failure.budget && typeof failure.budget === "object" ? failure.budget as Record<string, unknown> : null;
    const first = Array.isArray(failure.details) && typeof failure.details[0] === "string" ? failure.details[0] : "";
    // Older persisted reports carry this exact server-generated budget line.
    const legacy = /^(input_tokens|output_tokens|estimated_cost_usd): used=([\d.]+) limit=([\d.]+)$/.exec(first);
    const resource = budget?.which ?? legacy?.[1];
    const used = budget?.used ?? legacy?.[2];
    const limit = budget?.limit ?? legacy?.[3];
    const kind = resource === "input_tokens" ? "input token" : resource === "output_tokens" ? "output token" : resource === "estimated_cost_usd" ? "estimated cost" : null;
    const amount = used !== undefined && limit !== undefined ? ` (${used} of ${limit})` : "";
    const projected = typeof budget?.projected_input_tokens === "number" ? budget.projected_input_tokens : null;
    // A refusal made before the call: the prompt was measured against what remained, not spent.
    const remaining = projected !== null && used !== undefined && limit !== undefined ? Math.max(0, Number(limit) - Number(used)) : null;
    const text = projected !== null && remaining !== null
      ? `The model call was refused before it started: its prompt is about ${projected} input tokens and ${remaining} remain of ${limit}${at("node")}.`
      : kind ? `The model call reached its ${kind} limit${amount}${at("node")}.` : `The model call reached a budget limit${at("node")}.`;
    const fix = failure.budget_source === "run_limits" ? RUN_LIMITS : failure.budget_source === "provider_budget" || failure.budget_source === "both" ? { label: "Open System status", category: "runtime" as const } : undefined;
    return { text, fix };
  }

  if (status === "budget_exceeded") {
    const node = at("blocked_node");
    const observed = typeof failure.observed === "number" ? failure.observed : null;
    const limit = typeof failure.limit === "number" ? failure.limit : null;
    const reached = observed !== null && limit !== null ? ` (${observed} of ${limit})` : "";
    if (failure.resource === "wall_clock_s") {
      const advice = LOCAL_ENGINE_VISIBLE ? " A local model on CPU usually needs a longer one." : "";
      return {
        text: `The run passed its wall-clock limit${limit === null ? "" : ` of ${limit}s`}${node}.${advice}`,
        fix: RUN_LIMITS,
      };
    }
    if (failure.resource === "iterations") {
      return { text: `The run used all of its allowed steps${reached}${node}.`, fix: RUN_LIMITS };
    }
    if (failure.resource !== "input_tokens" && failure.resource !== "output_tokens") return { text: "The run reached an unspecified budget limit." };
    const half = failure.resource === "output_tokens" ? "output" : "input";
    return { text: `The run exceeded its ${half} token budget${reached}${node}.`, fix: RUN_LIMITS };
  }

  if (status === "schema_rejected") {
    const advice = LOCAL_ENGINE_VISIBLE
      ? " Smaller local models often fail structured output; try the OpenAI engine for this question."
      : "";
    return { text: `The model returned output that did not match the required schema${tried}.${advice}` };
  }

  if (status === "provider_error" && LOCAL_ENGINE_VISIBLE) {
    if (/ReadTimeout|ConnectTimeout|TimeoutException/i.test(detail)) {
      return {
        text: `The model did not answer within the time limit${tried}. Raise LOCAL_LLM_TIMEOUT_S, or choose a smaller model.`,
        fix: { label: "Open System status", category: "runtime" },
      };
    }
    if (/ConnectError|Connection refused|ConnectionError/i.test(detail)) {
      return {
        text: "The model host is unreachable. Check that the separately installed model server is running and LOCAL_LLM_BASE_URL is reachable from the app.",
        fix: { label: "Open System status", category: "runtime" },
      };
    }
  }

  if (status === "node_error") {
    const kind = typeof failure.error_type === "string" ? failure.error_type : "step";
    const message = typeof failure.message === "string" ? `: ${failure.message}` : "";
    return { text: `A ${kind} stopped the run${at("node")}${message}` };
  }

  const first = Array.isArray(failure.details) && typeof failure.details[0] === "string" ? ` ${failure.details[0]}` : "";
  return { text: `The answer could not be generated (${status})${at("node")}${tried}.${first}` };
}

/** The failure sentence alone, for callers with nowhere to put an action. */
export function failureMessage(failure: Record<string, unknown>): string {
  return failureReport(failure).text;
}
