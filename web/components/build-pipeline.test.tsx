import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { derivePipeline, type PipelineInput } from "@/lib/pipeline";
import type { OperatorJob, Readiness } from "@/lib/types";
import { BuildPipeline, type BuildPipelineProps } from "./build-pipeline";

const READINESS: Readiness = {
  status: "ready",
  mode: "runtime",
  admin_mode: "live",
  policy_revision: "test",
  models: {},
  review_enabled: true,
  active_review_model: "gpt-5.6-terra",
  review_engines: { openai: { enabled: true, model: "gpt-5.6-terra", key_slot: "dev" } },
  corpus: {
    availability: "ready",
    database_connected: true,
    schema_status: "compatible",
    schema_message: "ok",
    documents: 0,
    chunks: 0,
    embedded_chunks: 0,
    pending_embeddings: 0,
    bm25_ready: false,
    writable: true,
  },
};

const RUNNING_JOB: OperatorJob = {
  job_id: "job-1",
  domain: "corpus",
  kind: "backfill_embeddings",
  request: {},
  status: "running",
  stage: "embedding",
  current: 50,
  total: 100,
  detail_current: null,
  detail_total: null,
  message: "Embedded 50",
  error_code: null,
  result_refs: {},
  queue_position: null,
  can_cancel: true,
  can_retry: false,
  created_at: "2026-09-01T12:00:00Z",
  started_at: "2026-09-01T12:00:01Z",
  finished_at: null,
  updated_at: "2026-09-01T12:00:02Z",
};

function liveInput(overrides: Partial<PipelineInput> = {}): PipelineInput {
  return {
    live: true,
    healthKind: "healthy",
    readiness: READINESS,
    corpus: {
      database_connected: true, schema_status: "compatible", schema_message: "ok",
      documents: 0, chunks: 0, embedded_chunks: 0, pending_embeddings: 0, bm25_ready: false, writable: true, provider: "deterministic",
    },
    manifests: [{ name: "manifest.json", registry: "sec", documents: 21, valid: true, sources_present: 21 }],
    registryCounts: {},
    jobs: [],
    evaluationResults: 0,
    snapshots: 0,
    ...overrides,
  };
}

function renderPipeline(input: PipelineInput, overrides: Partial<BuildPipelineProps> = {}) {
  const handlers = {
    onAcquisitionChange: vi.fn(),
    onDownload: vi.fn(),
    onIngestAll: vi.fn(),
    onIngest: vi.fn(),
    onBackfill: vi.fn(),
    onRebuildBm25: vi.fn(),
    onAsk: vi.fn(),
    onRecheck: vi.fn(),
    onEvaluate: vi.fn(),
    onCompareSnapshots: vi.fn(),
    onOpenDocuments: vi.fn(),
    onOpenJobs: vi.fn(),
    onOpenStatus: vi.fn(),
    onRefresh: vi.fn(),
    onCancelJob: vi.fn(),
  };
  render(
    <BuildPipeline
      pipeline={derivePipeline(input)}
      live={input.live}
      busy={false}
      canOperateCorpus={input.live}
      acquisition={{ registry: "sec", identifiers: "NVDA AMD", years: "2023 2024" }}
      manifests={input.manifests}
      {...handlers}
      {...overrides}
    />,
  );
  return handlers;
}

describe("BuildPipeline", () => {
  it("distinguishes a ready corpus from an unmeasured evaluation without blocking questions", () => {
    const handlers = renderPipeline(liveInput({
      corpus: { database_connected: true, schema_status: "compatible", schema_message: "ok", documents: 21, chunks: 100, embedded_chunks: 100, pending_embeddings: 0, bm25_ready: true, writable: true, provider: "deterministic" },
      evaluationResults: 0,
    }));
    expect(screen.getByRole("heading", { name: "Corpus ready · evaluation pending" })).toBeInTheDocument();
    expect(screen.getByText("Not run")).toBeInTheDocument();
    expect(screen.queryByText("All steps done")).not.toBeInTheDocument();
    const summary = document.querySelector('.next-step')!;
    const ask = [...summary.querySelectorAll('button')].find((button) => button.textContent === "Ask a question")!;
    expect(ask).toBeEnabled();
    fireEvent.click(ask);
    expect(handlers.onAsk).toHaveBeenCalledOnce();
  });

  it("keeps every setup number and its purpose visible after completion", () => {
    renderPipeline(liveInput({
      corpus: { database_connected: true, schema_status: "compatible", schema_message: "ok", documents: 21, chunks: 100, embedded_chunks: 100, pending_embeddings: 0, bm25_ready: true, writable: true, provider: "deterministic" },
      evaluationResults: 1,
    }));
    const titles = ["Filings", "Parse & chunk", "Embeddings", "Lexical index (BM25)", "Ask", "Answer model", "Evaluate"];
    titles.forEach((title, index) => expect(screen.getByRole("heading", { name: `${index + 1}. ${title}` })).toBeVisible());
    expect(screen.getAllByText("Why it matters:")).toHaveLength(7);
  });

  afterEach(cleanup);

  it("points at the next stage and wires its primary action", () => {
    const handlers = renderPipeline(liveInput());

    expect(screen.getByText("Next step · 2 Parse & chunk")).toBeInTheDocument();
    expect(screen.getByText("SEC EDGAR · NVDA, AMD · FY2023, FY2024")).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: "Ingest all manifests" });
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[0]);
    expect(handlers.onIngestAll).toHaveBeenCalledTimes(1);
    expect(document.querySelector("#stage-2.stage-card.next")).not.toBeNull();
    expect(document.querySelectorAll("ol.stage-list article.stage-card")).toHaveLength(7);
  });

  it("locks operator stages in read-only mode and offers exploration instead", () => {
    const handlers = renderPipeline(liveInput({ live: false, readiness: null, corpus: null, manifests: [], snapshots: 2 }));

    expect(screen.getByText("Explore")).toBeInTheDocument();
    expect(screen.getByText("Read-only portfolio · stored snapshots + live retrieval")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download missing filings" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Backfill embeddings" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Rebuild BM25" })).toBeDisabled();
    expect(screen.getAllByText("Runs on the local operator build.")).toHaveLength(5);
    fireEvent.click(screen.getByRole("button", { name: "Compare snapshots" }));
    expect(handlers.onCompareSnapshots).toHaveBeenCalledTimes(1);
  });

  it("renders a running job once inside its stage card", () => {
    const handlers = renderPipeline(liveInput({
      corpus: {
        database_connected: true, schema_status: "compatible", schema_message: "ok",
        documents: 29, chunks: 21927, embedded_chunks: 10000, pending_embeddings: 11927, bm25_ready: true, writable: true, provider: "deterministic",
      },
      registryCounts: { sec: 21 },
      jobs: [RUNNING_JOB],
    }));

    expect(screen.getByText("Running · 3 Embeddings · 50%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
    expect(screen.getAllByText("50 / 100 · 50%")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "View all jobs" }));
    expect(handlers.onOpenJobs).toHaveBeenCalledTimes(1);
  });

  it("offers Operations buttons for runtime problems only when an operator is attached", () => {
    const onRunOperation = vi.fn();
    const input = liveInput({ corpus: { database_connected: false, schema_status: "unavailable", schema_message: "db down", documents: 0, chunks: 0, embedded_chunks: 0, pending_embeddings: 0, bm25_ready: false, writable: true } });
    renderPipeline(input, { databaseConnected: false, schemaStatus: "unavailable", schemaMessage: "db down", operationsAvailable: true, onRunOperation });

    fireEvent.click(screen.getByRole("button", { name: "Start database" }));
    expect(onRunOperation).toHaveBeenCalledWith("db-start");
    expect(screen.queryByText("docker compose up -d db")).toBeNull();
    cleanup();

    // A handler alone is not enough: the button only appears when a local operator is attached.
    renderPipeline(input, { databaseConnected: false, schemaStatus: "unavailable", schemaMessage: "db down", operationsAvailable: false, onRunOperation });
    expect(screen.getByText("docker compose up -d db")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start database" })).toBeNull();
    expect(onRunOperation).toHaveBeenCalledTimes(1);
  });
});
