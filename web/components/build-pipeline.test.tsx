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
  it("marks operator execution stages without marking the public question path", () => {
    renderPipeline(liveInput(), { focusStage: "filings" });
    expect(document.querySelector(".stage-head .development-badge")).toHaveAttribute("title", "DEV only");
    fireEvent.click(screen.getByRole("button", { name: "Select Ask" }));
    expect(document.querySelector(".stage-head .development-badge")).toBeNull();
  });

  it("distinguishes a ready corpus from an unmeasured evaluation without blocking questions", () => {
    const handlers = renderPipeline(liveInput({
      corpus: { database_connected: true, schema_status: "compatible", schema_message: "ok", documents: 21, chunks: 100, embedded_chunks: 100, pending_embeddings: 0, bm25_ready: true, writable: true, provider: "deterministic" },
      evaluationResults: 0,
    }));
    expect(screen.getByText("Corpus ready")).toBeInTheDocument();
    expect(document.querySelector(".pipeline-node.evaluate")).toHaveTextContent("Not run");
    expect(screen.queryByText("All steps done")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Select Ask" }));
    const ask = screen.getByRole("button", { name: "Ask a question" });
    expect(ask).toBeEnabled();
    fireEvent.click(ask);
    expect(handlers.onAsk).toHaveBeenCalledOnce();
  });

  it("keeps every setup number and its purpose visible after completion", () => {
    const handlers = renderPipeline(liveInput({
      corpus: { database_connected: true, schema_status: "compatible", schema_message: "ok", documents: 21, chunks: 100, embedded_chunks: 100, pending_embeddings: 0, bm25_ready: true, writable: true, provider: "deterministic" },
      evaluationResults: 1,
    }));
    const titles = ["Filings", "Parse & chunk", "Embeddings", "Lexical index (BM25)", "Ask", "Answer model", "Evaluate"];
    titles.forEach((title, index) => {
      const node = screen.getByRole("button", { name: `Select ${title}` });
      expect(node).toBeVisible();
      fireEvent.click(node);
      expect(screen.getByRole("heading", { name: `${index + 1}. ${title}` })).toBeVisible();
      expect(screen.getByText("Why it matters:")).toBeVisible();
      expect(document.querySelectorAll("ol.stage-list article.stage-card")).toHaveLength(1);
    });
    for (const handler of Object.values(handlers)) expect(handler).not.toHaveBeenCalled();
  });

  afterEach(cleanup);

  it("points at the next stage and wires its primary action", () => {
    const handlers = renderPipeline(liveInput());

    expect(screen.getByText("Recommended next step")).toBeInTheDocument();
    expect(document.querySelector(".pipeline-guidance button")).toHaveTextContent("Parse & chunk");
    fireEvent.click(screen.getByRole("button", { name: "Select Filings" }));
    expect(screen.getByText("SEC EDGAR · NVDA, AMD · FY2023, FY2024")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
    const buttons = screen.getAllByRole("button", { name: "Ingest all manifests" });
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);
    expect(handlers.onIngestAll).toHaveBeenCalledTimes(1);
    expect(document.querySelector("#stage-2.stage-card.next")).not.toBeNull();
    expect(document.querySelectorAll("ol.stage-list article.stage-card")).toHaveLength(1);
  });

  it("locks operator stages in read-only mode and offers exploration instead", () => {
    const handlers = renderPipeline(liveInput({ live: false, readiness: null, corpus: null, manifests: [], snapshots: 2 }));

    expect(document.querySelector(".pipeline-guidance")).toBeInTheDocument();
    expect(screen.getByText("Read-only portfolio · stored snapshots + live retrieval")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download missing filings" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Select Embeddings" }));
    expect(screen.getByRole("button", { name: "Backfill embeddings" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Select Lexical index (BM25)" }));
    expect(screen.getByRole("button", { name: "Rebuild BM25" })).toBeDisabled();
    expect(screen.getByText("Runs on the local operator build.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Select Evaluate" }));
    fireEvent.click(screen.getByRole("button", { name: "Compare published snapshots" }));
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

    expect(screen.getByRole("heading", { name: "3. Embeddings" })).toBeInTheDocument();
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
