import { describe, expect, it } from "vitest";

import { ANSWER_MODEL_HINT, derivePipeline, STAGE_ORDER } from "./pipeline";
import type { Pipeline, PipelineInput, Stage, StageId } from "./pipeline";
import type { CorpusCounts, ManifestSummary, OperatorJob, Readiness } from "./types";

/** Full, healthy corpus as reported by `/admin/corpus`.status. */
function fullCorpus(overrides: Partial<CorpusCounts> = {}): CorpusCounts {
  return {
    database_connected: true,
    schema_status: "ok",
    schema_message: null,
    documents: 29,
    chunks: 21927,
    embedded_chunks: 21927,
    pending_embeddings: 0,
    bm25_ready: true,
    writable: true,
    ...overrides,
  };
}

/** Empty database right after `docker compose up`: schema created, nothing ingested. */
function emptyCorpus(overrides: Partial<CorpusCounts> = {}): CorpusCounts {
  return fullCorpus({
    schema_status: "empty",
    documents: 0,
    chunks: 0,
    embedded_chunks: 0,
    pending_embeddings: 0,
    bm25_ready: false,
    ...overrides,
  });
}

/** Runtime readiness with the OpenAI engine configured on the dev key slot. */
function baseReadiness(overrides: Partial<Readiness> = {}): Readiness {
  return {
    status: "ready",
    mode: "runtime",
    admin_mode: "live",
    policy_revision: "test",
    models: {},
    review_enabled: true,
    active_review_model: "gpt-5.6-terra",
    review_engines: {
      openai: { enabled: true, model: "gpt-5.6-terra", key_slot: "dev" },
      local: { enabled: false, reason: "not_configured" },
    },
    corpus: { availability: "ready", ...fullCorpus() },
    ...overrides,
  };
}

function manifest(registry: string, documents: number, sourcesPresent: number): ManifestSummary {
  return {
    name: registry === "sec" ? "manifest.json" : `${registry}-manifest.json`,
    registry,
    documents,
    valid: true,
    sources_present: sourcesPresent,
  };
}

const SEC_AND_DART: ManifestSummary[] = [manifest("sec", 21, 21), manifest("dart", 9, 9)];

function job(overrides: Partial<OperatorJob> = {}): OperatorJob {
  return {
    job_id: "job-1",
    domain: "corpus",
    kind: "rebuild_bm25",
    request: {},
    status: "succeeded",
    stage: "done",
    current: 0,
    total: null,
    detail_current: null,
    detail_total: null,
    message: "",
    error_code: null,
    result_refs: {},
    queue_position: null,
    can_cancel: false,
    can_retry: false,
    created_at: "2026-09-02T00:00:00Z",
    started_at: null,
    finished_at: null,
    updated_at: "2026-09-02T00:00:00Z",
    ...overrides,
  };
}

/** Live operator with the full corpus loaded; individual tests override what they exercise. */
function liveInput(overrides: Partial<PipelineInput> = {}): PipelineInput {
  return {
    live: true,
    healthKind: "healthy",
    readiness: baseReadiness(),
    corpus: fullCorpus(),
    manifests: SEC_AND_DART,
    registryCounts: { sec: 20, dart: 9 },
    jobs: [],
    evaluationResults: 1,
    snapshots: 0,
    ...overrides,
  };
}

function stage(pipeline: Pipeline, id: StageId): Stage {
  const found = pipeline.stages.find((item) => item.id === id);
  if (!found) throw new Error(`missing stage ${id}`);
  return found;
}

function statuses(pipeline: Pipeline): Record<StageId, Stage["status"]> {
  return Object.fromEntries(pipeline.stages.map((item) => [item.id, item.status])) as Record<StageId, Stage["status"]>;
}

describe("derivePipeline", () => {
  it("orders the seven stages 1..7 following STAGE_ORDER", () => {
    const pipeline = derivePipeline(liveInput());
    expect(pipeline.stages.map((item) => item.id)).toEqual([...STAGE_ORDER]);
    expect(pipeline.stages.map((item) => item.order)).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });

  // Case 1: every stage done; the SEC manifest lists one filing more than what is ingested.
  it("marks all stages done for a live, fully built corpus and flags the un-ingested SEC filing", () => {
    const pipeline = derivePipeline(liveInput());

    expect(pipeline.source).toBe("admin");
    expect(pipeline.readOnly).toBe(false);
    expect(pipeline.corpusReady).toBe(true);
    expect(pipeline.next).toBeNull();
    expect(Object.values(statuses(pipeline)).every((status) => status === "done")).toBe(true);

    const filings = stage(pipeline, "filings");
    expect(filings.numbers).toEqual(["30 / 30 filings on disk", "SEC 21/21", "DART 9/9"]);
    expect(filings.hint).toBe("");
    expect(filings.action?.label).toBe("Download missing filings");

    const index = stage(pipeline, "index");
    expect(index.numbers).toEqual(["29 documents", "21,927 chunks", "1 listed filing not ingested yet (SEC)"]);
    expect(index.hint).toContain("Ingest all manifests");
    expect(index.action).toEqual({ label: "Ingest all manifests", kind: "ingest_all" });

    expect(stage(pipeline, "embeddings").numbers).toEqual(["21,927 embedded", "0 pending"]);
    expect(stage(pipeline, "lexical").numbers).toEqual(["BM25 ready"]);

    const ask = stage(pipeline, "ask");
    expect(ask.statusDetail).toBe("hybrid ready");
    expect(ask.numbers).toEqual(["21,927 chunks searchable"]);
    expect(ask.action?.label).toBe("Ask a question");

    const answerModel = stage(pipeline, "answer_model");
    expect(answerModel.numbers).toEqual(["OpenAI · gpt-5.6-terra · dev key"]);
    expect(answerModel.action).toBeNull();

    const evaluate = stage(pipeline, "evaluate");
    expect(evaluate.numbers).toEqual(["1 result", "0 snapshots"]);
    expect(evaluate.action).toEqual({ label: "Run quick evaluation", kind: "evaluate" });
  });

  it("uses the plural form for several un-ingested filings", () => {
    const pipeline = derivePipeline(liveInput({ corpus: fullCorpus({ documents: 27 }), registryCounts: { sec: 18, dart: 9 } }));
    expect(stage(pipeline, "index").numbers).toContain("3 listed filings not ingested yet (SEC)");
  });

  // Case 2: `/ready` has answered but `/admin/corpus` has not; nothing downstream may guess.
  it("reports Checking… for filings and every corpus stage before the admin snapshot arrives", () => {
    const readiness = baseReadiness({ corpus: { availability: "ready", ...emptyCorpus() } });
    const pipeline = derivePipeline(liveInput({ readiness, corpus: null, manifests: [], registryCounts: {}, evaluationResults: 0 }));

    expect(pipeline.source).toBe("readiness");
    expect(pipeline.readOnly).toBe(false);
    expect(pipeline.corpusReady).toBe(false);
    expect(pipeline.next).toBeNull();

    const filings = stage(pipeline, "filings");
    expect(filings.status).toBe("unknown");
    expect(filings.statusDetail).toBe("Checking…");
    expect(filings.numbers).toEqual(["0 filings ingested"]);

    for (const id of ["index", "embeddings", "lexical", "ask", "evaluate"] as const) {
      const item = stage(pipeline, id);
      expect(item.status, id).toBe("unknown");
      expect(item.statusDetail, id).toBe("Checking…");
      expect(item.numbers, id).toEqual([]);
    }
    expect(stage(pipeline, "answer_model").status).toBe("done");
  });

  it("derives Parse & chunk from readiness counts when the admin snapshot is missing but /ready already has numbers", () => {
    const pipeline = derivePipeline(liveInput({ corpus: null, manifests: [], registryCounts: {} }));

    expect(pipeline.source).toBe("readiness");
    expect(stage(pipeline, "filings").status).toBe("unknown");
    expect(stage(pipeline, "filings").numbers).toEqual(["29 filings ingested"]);
    const index = stage(pipeline, "index");
    expect(index.status).toBe("done");
    expect(index.numbers).toEqual(["29 documents", "21,927 chunks"]);
    expect(stage(pipeline, "ask").status).toBe("done");
  });

  // Case 3: filings are on disk, the schema exists, but nothing has been ingested yet.
  it("asks for Ingest all manifests on an empty database and blocks everything after step 2", () => {
    const pipeline = derivePipeline(liveInput({
      corpus: emptyCorpus(),
      manifests: [manifest("sec", 21, 21)],
      registryCounts: {},
      evaluationResults: 0,
    }));

    expect(pipeline.source).toBe("admin");
    expect(pipeline.corpusReady).toBe(false);
    expect(pipeline.next?.id).toBe("index");

    const filings = stage(pipeline, "filings");
    expect(filings.status).toBe("done");
    expect(filings.numbers).toEqual(["21 / 21 filings on disk", "SEC 21/21"]);

    const index = stage(pipeline, "index");
    expect(index.status).toBe("action");
    expect(index.numbers).toEqual(["Nothing ingested yet."]);
    expect(index.hint).toContain("Ingest all manifests");
    expect(index.action).toEqual({ label: "Ingest all manifests", kind: "ingest_all" });

    for (const id of ["embeddings", "lexical"] as const) {
      const item = stage(pipeline, id);
      expect(item.status, id).toBe("blocked");
      expect(item.statusDetail, id).toBe("after step 2 · Parse & chunk");
      expect(item.blockedBy, id).toBe("index");
      expect(item.hint, id).toBe("Ingest a manifest first (step 2).");
    }

    const ask = stage(pipeline, "ask");
    expect(ask.status).toBe("blocked");
    expect(ask.statusDetail).toBe("corpus is empty");
    expect(ask.blockedBy).toBe("index");

    const evaluate = stage(pipeline, "evaluate");
    expect(evaluate.status).toBe("blocked");
    expect(evaluate.statusDetail).toBe("after steps 2–4");
    expect(evaluate.numbers).toEqual(["Not measured yet."]);
  });

  // Case 4: the manifest lists filings but none of the source files exist yet.
  it("asks to download filings when the manifest entries are missing on disk and blocks Parse & chunk on step 1", () => {
    const pipeline = derivePipeline(liveInput({
      corpus: emptyCorpus(),
      manifests: [manifest("sec", 21, 0)],
      registryCounts: {},
      evaluationResults: 0,
    }));

    expect(pipeline.next?.id).toBe("filings");
    expect(pipeline.corpusReady).toBe(false);

    const filings = stage(pipeline, "filings");
    expect(filings.status).toBe("action");
    expect(filings.numbers).toEqual(["0 / 21 filings on disk", "SEC 0/21"]);
    expect(filings.hint).toBe("21 listed filings are not on disk yet. Run Download missing filings.");
    expect(filings.action).toEqual({ label: "Download missing filings", kind: "acquire" });

    const index = stage(pipeline, "index");
    expect(index.status).toBe("blocked");
    expect(index.statusDetail).toBe("after step 1 · Filings");
    expect(index.blockedBy).toBe("filings");
    expect(index.hint).toBe("Download filings first (step 1).");
  });

  it("asks to download filings when no manifest lists anything", () => {
    const pipeline = derivePipeline(liveInput({ corpus: emptyCorpus(), manifests: [], registryCounts: {}, evaluationResults: 0 }));
    const filings = stage(pipeline, "filings");
    expect(filings.status).toBe("action");
    expect(filings.numbers).toEqual(["No filings yet."]);
    expect(filings.hint).toContain("Download missing filings");
    expect(pipeline.next?.id).toBe("filings");
  });

  // Case 5: chunks exist but some still lack vectors; BM25 keeps Ask usable.
  it("asks for Backfill embeddings when chunks are pending and reports lexical-only retrieval", () => {
    const pipeline = derivePipeline(liveInput({ corpus: fullCorpus({ embedded_chunks: 21915, pending_embeddings: 12 }) }));

    expect(pipeline.corpusReady).toBe(false);
    expect(pipeline.next?.id).toBe("embeddings");

    const embeddings = stage(pipeline, "embeddings");
    expect(embeddings.status).toBe("action");
    expect(embeddings.numbers).toEqual(["21,915 embedded", "12 pending"]);
    expect(embeddings.hint).toContain("12 chunks still need vectors");
    expect(embeddings.action).toEqual({ label: "Backfill embeddings", kind: "embed" });

    const ask = stage(pipeline, "ask");
    expect(ask.status).toBe("done");
    expect(ask.statusDetail).toBe("lexical only · embeddings pending");
  });

  it("appends the embedding provider to the pending count when the snapshot names one", () => {
    const pipeline = derivePipeline(liveInput({ corpus: fullCorpus({ provider: "deterministic" }) }));
    expect(stage(pipeline, "embeddings").numbers).toEqual(["21,927 embedded", "0 pending · deterministic"]);
  });

  // Case 6: vectors are complete but the BM25 statistics were reset.
  it("asks for Rebuild BM25 when bm25_ready is false and reports vector-only retrieval", () => {
    const pipeline = derivePipeline(liveInput({ corpus: fullCorpus({ bm25_ready: false }) }));

    expect(pipeline.corpusReady).toBe(false);
    expect(pipeline.next?.id).toBe("lexical");

    const lexical = stage(pipeline, "lexical");
    expect(lexical.status).toBe("action");
    expect(lexical.numbers).toEqual(["BM25 not built"]);
    expect(lexical.hint).toBe("Run Rebuild BM25 to compute the term statistics.");
    expect(lexical.action).toEqual({ label: "Rebuild BM25", kind: "bm25" });

    const ask = stage(pipeline, "ask");
    expect(ask.status).toBe("done");
    expect(ask.statusDetail).toBe("vector ready · BM25 pending");
  });

  it("reports limited retrieval when neither vectors nor BM25 are complete", () => {
    const pipeline = derivePipeline(liveInput({ corpus: fullCorpus({ pending_embeddings: 5, embedded_chunks: 21922, bm25_ready: false }) }));
    expect(stage(pipeline, "ask").statusDetail).toBe("retrieval limited");
  });

  // Case 7: a running job overrides its stage with progress; a queued one shows its position.
  it("shows a running backfill with 50% progress and a queued BM25 rebuild as Queued #2", () => {
    const running = job({ job_id: "embed-1", kind: "backfill_embeddings", status: "running", stage: "embed", current: 50, total: 100, message: "Embedded 50", can_cancel: true });
    const queued = job({ job_id: "bm25-1", kind: "rebuild_bm25", status: "queued", stage: "queued", queue_position: 2 });
    const pipeline = derivePipeline(liveInput({
      corpus: fullCorpus({ embedded_chunks: 21877, pending_embeddings: 50, bm25_ready: false }),
      jobs: [running, queued],
    }));

    const embeddings = stage(pipeline, "embeddings");
    expect(embeddings.status).toBe("running");
    expect(embeddings.progress).toBe(50);
    expect(embeddings.statusDetail).toBe("50%");
    expect(embeddings.hint).toBe("Embedded 50");
    expect(embeddings.job).toBe(running);

    const lexical = stage(pipeline, "lexical");
    expect(lexical.status).toBe("queued");
    expect(lexical.statusDetail).toBe("Queued #2");
    expect(lexical.job).toBe(queued);
    expect(lexical.hint).toBe("Waiting for the current job to finish.");

    expect(pipeline.next).toBeNull();
    expect(pipeline.corpusReady).toBe(false);
  });

  it("falls back to the job stage name when a running job has no total", () => {
    const running = job({ kind: "ingest_manifest", status: "running", stage: "parsing", current: 3, total: null, message: "Parsing NVDA FY2024" });
    const pipeline = derivePipeline(liveInput({ jobs: [running] }));
    const index = stage(pipeline, "index");
    expect(index.status).toBe("running");
    expect(index.progress).toBeNull();
    expect(index.statusDetail).toBe("parsing");
  });

  // Case 8: the latest job of a stage failed; it only matters while the stage is not done.
  it("marks Lexical index failed with the job message when the latest rebuild failed and BM25 is not ready", () => {
    const failed = job({ job_id: "bm25-9", kind: "rebuild_bm25", status: "failed", message: "boom", error_code: "bm25_failed", can_retry: true });
    const pipeline = derivePipeline(liveInput({ corpus: fullCorpus({ bm25_ready: false }), jobs: [failed] }));

    const lexical = stage(pipeline, "lexical");
    expect(lexical.status).toBe("failed");
    expect(lexical.statusDetail).toBe("bm25_failed");
    expect(lexical.hint).toContain("boom");
    expect(lexical.job).toBe(failed);
    expect(pipeline.next?.id).toBe("lexical");
  });

  it("keeps Lexical index done when an older rebuild failed but BM25 is ready now", () => {
    const failed = job({ job_id: "bm25-9", kind: "rebuild_bm25", status: "failed", message: "boom" });
    const pipeline = derivePipeline(liveInput({ jobs: [failed] }));

    const lexical = stage(pipeline, "lexical");
    expect(lexical.status).toBe("done");
    expect(lexical.job).toBeNull();
    expect(lexical.hint).toBe("");
    expect(pipeline.next).toBeNull();
  });

  // Case 9: runtime mode with no configured engine; Ask still works in evidence-only mode.
  it("blocks Answer model with the setup hint and a Re-check action when review is disabled", () => {
    const readiness = baseReadiness({
      review_enabled: false,
      active_review_model: null,
      review_engines: { openai: { enabled: false }, local: { enabled: false, reason: "not_configured" } },
    });
    const pipeline = derivePipeline(liveInput({ readiness }));

    const answerModel = stage(pipeline, "answer_model");
    expect(answerModel.status).toBe("blocked");
    expect(answerModel.statusDetail).toBe("No answer model");
    expect(answerModel.numbers).toEqual(["openai · disabled", "local · not_configured"]);
    expect(answerModel.hint).toBe(ANSWER_MODEL_HINT);
    expect(answerModel.action).toEqual({ label: "Re-check", kind: "recheck" });

    // A blocked answer model is not an operator action; the corpus stages are all done.
    expect(pipeline.next).toBeNull();
    expect(pipeline.corpusReady).toBe(true);
  });

  it("lists a local engine next to OpenAI when both are enabled", () => {
    const readiness = baseReadiness({
      review_engines: {
        openai: { enabled: true, model: "gpt-5.6-terra", key_slot: "prod" },
        local: { enabled: true, model: "qwen3" },
      },
    });
    const pipeline = derivePipeline(liveInput({ readiness }));
    expect(stage(pipeline, "answer_model").numbers).toEqual(["OpenAI · gpt-5.6-terra · prod key", "Local · qwen3"]);
  });

  // Case 10: static public build with no API at all; the portfolio fixture stands in.
  it("renders the portfolio fixture read-only when neither live nor readiness is available", () => {
    const pipeline = derivePipeline({
      live: false,
      healthKind: "checking",
      readiness: null,
      corpus: null,
      manifests: [],
      registryCounts: {},
      jobs: [],
      evaluationResults: 0,
      snapshots: 0,
    });

    expect(pipeline.source).toBe("fixture");
    expect(pipeline.readOnly).toBe(true);
    expect(pipeline.next).toBeNull();
    expect(pipeline.corpusReady).toBe(true);

    for (const id of ["filings", "index", "embeddings", "lexical", "evaluate"] as const) {
      const item = stage(pipeline, id);
      expect(item.status, id).toBe("readonly");
      expect(item.statusDetail, id).toBe("Portfolio fixture");
      expect(item.hint, id).toBe("");
    }

    expect(stage(pipeline, "filings").numbers).toEqual(["22 filings in the published corpus"]);
    expect(stage(pipeline, "filings").action?.label).toBe("Download missing filings");
    expect(stage(pipeline, "ask").status).toBe("done");

    const evaluate = stage(pipeline, "evaluate");
    expect(evaluate.action).toEqual({ label: "Compare published snapshots", kind: "compare" });
    // No published snapshot yet, so the read-only card keeps the unmeasured numbers line.
    expect(evaluate.numbers).toEqual(["Not measured yet."]);

    const answerModel = stage(pipeline, "answer_model");
    expect(answerModel.status).toBe("unknown");
    expect(answerModel.statusDetail).toBe("Checking…");
  });

  // Case 11: public UI in front of a live API; numbers come from /ready and /snapshots.
  it("uses readiness numbers read-only with the stored qualifier when the UI is public but the API is real", () => {
    const pipeline = derivePipeline({
      live: false,
      healthKind: "healthy",
      readiness: baseReadiness(),
      corpus: null,
      manifests: [],
      registryCounts: {},
      jobs: [],
      evaluationResults: 0,
      snapshots: 2,
    });

    expect(pipeline.source).toBe("readiness");
    expect(pipeline.readOnly).toBe(true);
    expect(pipeline.corpusReady).toBe(true);

    const filings = stage(pipeline, "filings");
    expect(filings.status).toBe("readonly");
    expect(filings.statusDetail).toBe("stored");
    expect(filings.numbers).toEqual(["29 filings in the published corpus"]);

    // Plan §2 override (d): read-only mode turns stage 7 into `readonly` even though
    // two published snapshots satisfy its public "done" rule.
    const evaluate = stage(pipeline, "evaluate");
    expect(evaluate.status).toBe("readonly");
    expect(evaluate.statusDetail).toBe("stored");
    expect(evaluate.numbers).toEqual(["2 published snapshots"]);
    expect(evaluate.action).toEqual({ label: "Compare published snapshots", kind: "compare" });

    expect(stage(pipeline, "ask").status).toBe("done");
    expect(stage(pipeline, "answer_model").status).toBe("done");
  });

  // Case 12: the API itself is the canned public demo, so a live UI must still be read-only.
  it("treats readiness mode canned as read-only and shows the public demo answer model", () => {
    const readiness = baseReadiness({ mode: "canned", admin_mode: "readonly" });
    const pipeline = derivePipeline(liveInput({ readiness, corpus: null, manifests: [], registryCounts: {} }));

    expect(pipeline.readOnly).toBe(true);
    expect(pipeline.source).toBe("readiness");

    const answerModel = stage(pipeline, "answer_model");
    expect(answerModel.status).toBe("readonly");
    expect(answerModel.statusDetail).toBe("Public demo");
    expect(answerModel.numbers).toEqual(["Public demo replays stored answers; no provider is called."]);
    expect(answerModel.action).toBeNull();

    expect(stage(pipeline, "filings").status).toBe("readonly");
    expect(stage(pipeline, "filings").statusDetail).toBe("stored");
  });

  // Case 13: the API is unreachable; no stage may claim anything.
  it("marks every stage unknown with API unavailable and no action when the API is down", () => {
    const pipeline = derivePipeline(liveInput({ healthKind: "api_down" }));

    for (const item of pipeline.stages) {
      expect(item.status, item.id).toBe("unknown");
      expect(item.statusDetail, item.id).toBe("API unavailable");
      expect(item.action, item.id).toBeNull();
      expect(item.hint, item.id).toBe("");
    }
    expect(pipeline.next).toBeNull();
    expect(pipeline.corpusReady).toBe(false);
  });

  // Case 14: the database is not reachable; the corpus stages carry its message.
  it("blocks the corpus stages on the database with schema_message when the database is disconnected", () => {
    const pipeline = derivePipeline(liveInput({
      corpus: emptyCorpus({ database_connected: false, schema_status: "unavailable", schema_message: "db down" }),
      manifests: [manifest("sec", 21, 21)],
      registryCounts: {},
      evaluationResults: 0,
    }));

    expect(stage(pipeline, "filings").status).toBe("done");
    for (const id of ["index", "embeddings", "lexical"] as const) {
      const item = stage(pipeline, id);
      expect(item.status, id).toBe("blocked");
      expect(item.statusDetail, id).toBe("database");
      expect(item.hint, id).toBe("db down");
    }
    expect(pipeline.next).toBeNull();
    expect(pipeline.corpusReady).toBe(false);
  });

  it("blocks on a drifted schema even when counts are still available", () => {
    const pipeline = derivePipeline(liveInput({
      corpus: emptyCorpus({ schema_status: "drifted", schema_message: "Run migrations." }),
      manifests: [manifest("sec", 21, 21)],
      registryCounts: {},
    }));
    expect(stage(pipeline, "index").status).toBe("blocked");
    expect(stage(pipeline, "index").hint).toBe("Run migrations.");
  });

  // Case 15: the container cannot write data/, so downloads cannot land anywhere.
  it("blocks Filings with data/ not writable when the snapshot reports writable false", () => {
    const pipeline = derivePipeline(liveInput({ corpus: fullCorpus({ writable: false }) }));

    const filings = stage(pipeline, "filings");
    expect(filings.status).toBe("blocked");
    expect(filings.statusDetail).toBe("data/ not writable");
    expect(filings.numbers).toEqual(["30 / 30 filings on disk", "SEC 21/21", "DART 9/9"]);
    expect(filings.hint).toContain("HOST_GID");
    expect(filings.action?.label).toBe("Download missing filings");

    expect(stage(pipeline, "index").status).toBe("done");
    expect(pipeline.corpusReady).toBe(false);
    expect(pipeline.next).toBeNull();
  });

  it("counts a succeeded evaluation job as measured even before results are listed", () => {
    const succeeded = job({ job_id: "eval-1", domain: "evaluation", kind: "quick", status: "succeeded" });
    const pipeline = derivePipeline(liveInput({ evaluationResults: 0, jobs: [succeeded] }));
    expect(stage(pipeline, "evaluate").status).toBe("done");
    expect(stage(pipeline, "evaluate").numbers).toEqual(["0 results", "0 snapshots"]);
  });

  it("asks for a quick evaluation when retrieval is ready but nothing was measured", () => {
    const pipeline = derivePipeline(liveInput({ evaluationResults: 0 }));
    const evaluate = stage(pipeline, "evaluate");
    expect(evaluate.status).toBe("action");
    expect(evaluate.numbers).toEqual(["Not measured yet."]);
    expect(evaluate.hint).toContain("quick evaluation");
    expect(pipeline.next?.id).toBe("evaluate");
  });

  it("ignores invalid manifests when counting filings in live mode", () => {
    const broken: ManifestSummary = { name: "broken.json", registry: null, documents: null, valid: false, sources_present: null };
    const pipeline = derivePipeline(liveInput({ manifests: [...SEC_AND_DART, broken] }));
    expect(stage(pipeline, "filings").numbers).toEqual(["30 / 30 filings on disk", "SEC 21/21", "DART 9/9"]);
  });

  it("waits with Checking… on a live build before readiness or the admin snapshot arrives", () => {
    const pipeline = derivePipeline(liveInput({ healthKind: "checking", readiness: null, corpus: null, manifests: [], registryCounts: {} }));

    expect(pipeline.source).toBe("pending");
    expect(pipeline.readOnly).toBe(false);
    for (const id of ["filings", "index", "embeddings", "lexical", "ask", "answer_model", "evaluate"] as const) {
      expect(stage(pipeline, id).status, id).toBe("unknown");
      expect(stage(pipeline, id).numbers, id).toEqual([]);
    }
    expect(pipeline.next).toBeNull();
  });

  it("does not report un-ingested filings when the registry facets are unavailable", () => {
    const pipeline = derivePipeline(liveInput({ registryCounts: {} }));
    const index = stage(pipeline, "index");

    expect(index.status).toBe("done");
    expect(index.numbers).toEqual(["29 documents", "21,927 chunks"]);
    expect(index.hint).toBe("");
  });

  it("uses singular hints for one missing filing and one pending chunk", () => {
    const filings = derivePipeline(liveInput({ manifests: [manifest("sec", 21, 20), manifest("dart", 9, 9)] }));
    expect(stage(filings, "filings").hint).toBe("1 listed filing is not on disk yet. Run Download missing filings.");

    const embeddings = derivePipeline(liveInput({ corpus: fullCorpus({ embedded_chunks: 21926, pending_embeddings: 1 }) }));
    expect(stage(embeddings, "embeddings").hint).toBe("1 chunk still needs vectors. Run Backfill embeddings.");
  });

  it("drops job progress and numbers from every stage when the API is down", () => {
    const running = job({ kind: "backfill_embeddings", status: "running", current: 50, total: 100 });
    const pipeline = derivePipeline(liveInput({ healthKind: "api_down", jobs: [running] }));

    for (const item of pipeline.stages) {
      expect(item.job, item.id).toBeNull();
      expect(item.progress, item.id).toBeNull();
      expect(item.numbers, item.id).toEqual([]);
    }
  });
});
