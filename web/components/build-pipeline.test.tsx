import { readFileSync } from "node:fs";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { I18nProvider, LOCALE_KEY, translate } from "@/lib/i18n";
import { derivePipeline, type PipelineInput } from "@/lib/pipeline";
import type { OperatorJob, Readiness } from "@/lib/types";
import { BuildPipeline, type BuildPipelineProps } from "./build-pipeline";

afterEach(() => { cleanup(); localStorage.clear(); });

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
    manifests: [{ name: "manifest.json", corpus_id: "sec", registries: ["sec"], issuers: [], documents: 21, valid: true, sources_present: 21, selections: [{ selection_id: "sec-evaluation", document_ids: Array.from({length: 21}, (_, i) => `sec-${i}`), artifact_ids: Array.from({length: 21}, (_, i) => `sec-source-${i}`), sources_present: 21 }] }],
    registryCounts: {},
    jobs: [],
    evaluationResults: 0,
    snapshots: 0,
    ...overrides,
  };
}

function renderPipeline(input: PipelineInput, overrides: Partial<BuildPipelineProps> = {}) {
  if (!localStorage.getItem(LOCALE_KEY)) localStorage.setItem(LOCALE_KEY, "en");
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
    <I18nProvider><BuildPipeline
      pipeline={derivePipeline(input)}
      live={input.live}
      busy={false}
      canOperateCorpus={input.live}
      acquisition={{ identifiers: "NVDA AMD", years: "2023 2024" }}
      manifests={input.manifests}
      {...handlers}
      {...overrides}
    /></I18nProvider>,
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



  it("points at the next stage and wires its primary action", () => {
    const handlers = renderPipeline(liveInput(), { sources: ["NVDA", "AMD"].flatMap((issuer) => [2023, 2024].map((year) => ({ manifest: "manifest.json", document_id: `${issuer}-FY${year}`, registry: "sec", issuer, name: issuer, fiscal_year: year, on_disk: true }))) });

    expect(screen.getByText("Recommended next step")).toBeInTheDocument();
    expect(document.querySelector(".pipeline-guidance button")).toHaveTextContent("Parse & chunk");
    fireEvent.click(screen.getByRole("button", { name: "Select Filings" }));
    expect(screen.getByRole("region", { name: "Company and fiscal-year selection" })).toContainElement(screen.getByRole("button", { name: /^NVDA FY2024/ }));
    fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
    const buttons = screen.getAllByRole("button", { name: "Parse & chunk selected sources" });
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
    expect(screen.getByRole("button", { name: "Recompute BM25" })).toBeDisabled();
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
    expect(screen.getAllByText("rag-dev up --build -d").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Start database" })).toBeNull();
    expect(onRunOperation).toHaveBeenCalledTimes(1);
  });
});

it("keeps empty-schema setup explicit and rechecks after terminal work", () => {
  const handlers = renderPipeline(liveInput(), { schemaStatus: "empty", databaseConnected: true, focusStage: "filings" });
  expect(screen.getByRole("region", { name: "Terminal preparation" })).toHaveTextContent("uv run python -m scripts.schema prepare");
  expect(screen.getByRole("button", { name: "Download missing filings" })).toBeDisabled();
  expect(handlers.onDownload).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Check updated status" })).toBeEnabled();
});

it("opens canonical setup checks from the selected step diagnosis", () => {
  renderPipeline(liveInput(), { databaseConnected: true, schemaStatus: "drifted", writable: true, focusStage: "index" });
  fireEvent.click(screen.getByRole("button", { name: "Open setup checks" }));
  expect(document.getElementById("pipeline-setup-checks")).toHaveAttribute("open");
  expect(document.getElementById("pipeline-setup-checks")).toHaveFocus();
});

it.each(["en", "ko"])("contains drift detail only inside the localized notice (%s)", (locale) => {
  localStorage.setItem(LOCALE_KEY, locale);
  const message = "The database schema does not match: chunks missing index_text_sha256";
  const input = liveInput();
  const handlers = renderPipeline({ ...input, corpus: { ...input.corpus!, schema_status: "drifted", schema_message: message } }, {
    focusStage: "index", databaseConnected: true, schemaStatus: "drifted", schemaMessage: message, writable: true,
  });
  const detail = screen.getByText(message);
  expect(screen.getAllByText(message)).toHaveLength(1);
  const disclosure = detail.closest("details");
  expect(disclosure).not.toHaveAttribute("open");
  expect(disclosure?.closest(".terminal-handoff")).not.toBeNull();
  expect(document.querySelector(".stage-hint")?.textContent).not.toContain(message);
  const summary = screen.getByText(locale === "en" ? "Schema technical details" : "스키마 기술 상세");
  fireEvent.click(summary);
  expect(disclosure).toHaveAttribute("open");
  expect(document.querySelector(".pipeline-guidance button")?.textContent).toMatch(/Parse|파싱/);
  expect(handlers.onAsk).not.toHaveBeenCalled();
  localStorage.removeItem(LOCALE_KEY);
});

it("links schema-blocked downstream selection back to step 2", () => {
  const input = liveInput();
  renderPipeline({ ...input, corpus: { ...input.corpus!, schema_status: "drifted" } }, {
    focusStage: "embeddings", databaseConnected: true, schemaStatus: "drifted", writable: true,
  });
  expect(document.querySelector("#pipeline-execution > .helper")?.textContent).toContain("Parse & chunk");
  fireEvent.click(screen.getByRole("button", { name: "Go to prerequisite step" }));
  expect(document.querySelector("#pipeline-execution h2")?.textContent).toContain("2. Parse & chunk");
});


it("names missing company years, blocks the default ingest, and keeps Advanced actions", () => {
  const handlers = renderPipeline(liveInput(), { sources: [{ manifest: "manifest.json", document_id: "NVDA-FY2024", registry: "sec", issuer: "NVDA", name: "NVIDIA", fiscal_year: 2024, on_disk: true }] });
  fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
  expect(screen.getByRole("region", { name: "Selected documents" })).toHaveTextContent("NVDA FY2023");
  expect(screen.queryByRole("textbox", { name: "Tickers / stock codes" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Parse & chunk selected sources" })).toBeDisabled();
  fireEvent.click(screen.getByText("Advanced"));
  fireEvent.click(screen.getByRole("button", { name: "Ingest manifest.json / sec-evaluation" }));
  expect(handlers.onIngest).toHaveBeenCalledWith("manifest.json", "sec-evaluation");
  fireEvent.click(screen.getByRole("button", { name: "Change selection in Filings" }));
  expect(screen.getByRole("textbox", { name: "Tickers / stock codes" })).toBeInTheDocument();
});

it.each(["en", "ko"] as const)("keeps the developer guide aligned with actual Filings and parsing controls (%s)", (locale) => {
  localStorage.setItem(LOCALE_KEY, locale);
  const guide = readFileSync(`../docs/TUTORIAL/${locale}/quickstart-dev.md`, "utf8").split("<!-- quickstart-web -->")[1];
  renderPipeline(liveInput(), { focusStage: "filings" });
  for (const key of ["Tickers / stock codes", "Fiscal years"]) {
    const label = translate(locale, key);
    expect(screen.getByRole("textbox", { name: label })).toBeVisible();
    expect(guide).toContain(`**${label}**`);
  }
  for (const key of ["Clear selection", "Add to selection", "Download missing filings"]) {
    const label = translate(locale, key);
    expect(screen.getByRole("button", { name: label })).toBeVisible();
    expect(guide).toContain(`**${label}**`);
  }
  expect(guide).not.toMatch(/(?:Filings|원문 수집) → (?:Change|변경)…/);
  fireEvent.click(screen.getByRole("button", { name: translate(locale, "Select {p0}", { p0: translate(locale, "Parse & chunk") }) }));
  expect(screen.getByRole("button", { name: translate(locale, "Parse & chunk selected sources") })).toBeVisible();
  expect(guide).toContain(`**${translate(locale, "Parse & chunk selected sources")}**`);
  expect(guide).toContain(`**${translate(locale, "Advanced")}**`);
  expect(guide).toContain(`**${translate(locale, "Ingest")}**`);
});
