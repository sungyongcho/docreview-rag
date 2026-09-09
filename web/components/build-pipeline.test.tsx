import { readFileSync } from "node:fs";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useState } from "react";
import { acquisitionDraft, type SourceInventory } from "@/lib/source-selection";
import type { AcquisitionForm } from "./build-pipeline";
import { I18nProvider, LOCALE_KEY, translate } from "@/lib/i18n";
import { derivePipeline, type PipelineInput, type StageStatus } from "@/lib/pipeline";
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
      acquisition={acquisitionDraft(["NVDA", "AMD"].flatMap(issuer => [2023, 2024].map(year => ({ registry: "sec", issuer, year }))))}
      manifests={input.manifests}
      {...handlers}
      {...overrides}
    /></I18nProvider>,
  );
  return handlers;
}

describe("BuildPipeline", () => {
  it.each(["en", "ko"] as const)("keeps the embedding duration note visible and inert across stage states (%s)", (locale) => {
    localStorage.setItem(LOCALE_KEY, locale);
    const message = locale === "en"
      ? "Initial embedding or a large number of new chunks can take time."
      : "첫 임베딩이거나 새 청크가 많으면 처리에 시간이 걸릴 수 있습니다.";
    const statuses: StageStatus[] = ["action", "running", "queued", "done", "failed", "blocked", "readonly", "unknown"];
    for (const status of statuses) {
      const input = liveInput({ jobs: status === "running" ? [RUNNING_JOB] : [] });
      const pipeline = derivePipeline(input);
      pipeline.stages.find((stage) => stage.id === "embeddings")!.status = status;
      const handlers = renderPipeline(input, { pipeline, focusStage: "embeddings" });
      const note = screen.getByText(message).closest('[role="note"]')!;
      expect(note).toBeVisible();
      expect(note.tagName).toBe("P");
      expect(note).not.toHaveAttribute("tabindex");
      expect(note).not.toHaveAttribute("onclick");
      expect(note.querySelector("button, a, input, [tabindex]")).toBeNull();
      expect(note.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
      expect(note.querySelector("svg")).toHaveAttribute("focusable", "false");
      fireEvent.click(note);
      (note as HTMLElement).focus();
      fireEvent.keyDown(note, { key: "Enter" });
      fireEvent.keyDown(note, { key: " " });
      expect(note).not.toHaveFocus();
      expect(screen.getByRole("heading", { name: locale === "en" ? "1-3. Embeddings" : "1-3. 임베딩" })).toBeVisible();
      for (const handler of Object.values(handlers)) expect(handler).not.toHaveBeenCalled();
      cleanup();
    }
  });

  it.each(["openai", "deterministic", "none", null])("shows the duration note only on embedding execution for provider %s", (provider) => {
    const handlers = renderPipeline(liveInput(), { embeddingProvider: provider, focusStage: "embeddings" });
    expect(document.querySelector("#pipeline-execution .embedding-duration-note")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Select Lexical index (BM25)" }));
    expect(document.querySelector(".embedding-duration-note")).toBeNull();
    for (const handler of Object.values(handlers)) expect(handler).not.toHaveBeenCalled();
  });

  it("marks operator execution stages without marking the public question path", () => {
    renderPipeline(liveInput(), { focusStage: "filings" });
    expect(document.querySelector(".pipeline-header-dev .development-badge")).toHaveAttribute("aria-label", "DEV only");
    fireEvent.click(screen.getByRole("button", { name: "Select Ask" }));
    expect(document.querySelector(".pipeline-header-dev .development-badge")).toBeNull();
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
      expect(screen.getByRole("heading", { name: `${["1-1", "1-2", "1-3", "1-4", "3-1", "2", "3-2"][index]}. ${title}` })).toBeVisible();
      expect(screen.getByText("Why it matters:")).toBeVisible();
      expect(document.querySelectorAll("ol.stage-list article.stage-card")).toHaveLength(1);
    });
    for (const handler of Object.values(handlers)) expect(handler).not.toHaveBeenCalled();
  });



  it("points at the next stage and wires its primary action", () => {
    const handlers = renderPipeline(liveInput(), { sources: ["NVDA", "AMD"].flatMap((issuer) => [2023, 2024].map((year) => ({ manifest: "manifest.json", document_id: `${issuer}-FY${year}`, filing_id: `${issuer}-FY${year}`, can_redownload: false, registry: "sec", issuer, name: issuer, fiscal_year: year, ready: true, on_disk: true }))) });

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
    expect(screen.queryByRole("button", { name: "Sync selection" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Select Embeddings" }));
    expect(screen.getByRole("button", { name: "Next step" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Select Lexical index (BM25)" }));
    expect(screen.getByRole("button", { name: "Next step" })).toBeEnabled();
    expect(document.querySelector(".stage-note")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Select Evaluate" }));
    expect(screen.getByText("Open Quality checks to explore datasets, try evaluation settings and compare published results. Running new evaluations is available in DEV mode.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Quality checks" })).not.toHaveAttribute("aria-disabled", "true");
    fireEvent.click(screen.getByRole("button", { name: "Open Quality checks" }));
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

    expect(screen.getByRole("heading", { name: "1-3. Embeddings" })).toBeInTheDocument();
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
  expect(screen.getByRole("button", { name: "Sync selection" })).toBeDisabled();
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
  expect(document.querySelector("#pipeline-execution > .pipeline-prerequisite")?.textContent).toContain("Parse & chunk");
  fireEvent.click(screen.getByRole("button", { name: "Go to prerequisite step" }));
  expect(document.querySelector("#pipeline-execution h2")?.textContent).toContain("2. Parse & chunk");
});


it("names missing company years, blocks the default ingest, and removes the Advanced bypass", () => {
  const handlers = renderPipeline(liveInput(), { sources: [{ manifest: "manifest.json", document_id: "NVDA-FY2024", filing_id: "NVDA-FY2024", registry: "sec", issuer: "NVDA", name: "NVIDIA", fiscal_year: 2024, ready: true, can_redownload: false, on_disk: true }] });
  fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
  expect(screen.getByRole("region", { name: "Selected documents" })).toHaveTextContent("4 documents · 1 ready · 3 to download");
  expect(screen.getByRole("button", { name: "NVDA FY2023 · Missing source" })).toHaveAttribute("aria-pressed", "true");
  expect(within(screen.getByRole("region", { name: "Selected documents" })).getByRole("alert")).toHaveTextContent("3 company-years need download or repair");
  expect(screen.queryByRole("textbox", { name: "Search/add company or year" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Parse & chunk selected sources" })).toBeDisabled();
  expect(screen.queryByText("Advanced")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Ingest manifest/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Change selection in Filings" }));
  expect(screen.getByRole("textbox", { name: "Search/add company or year" })).toBeInTheDocument();
});

it.each(["en", "ko"] as const)("keeps the developer guide aligned with actual Filings and parsing controls (%s)", (locale) => {
  localStorage.setItem(LOCALE_KEY, locale);
  const guide = readFileSync(`../docs/TUTORIAL/${locale}/quickstart-dev.md`, "utf8").split("<!-- quickstart-web -->")[1];
  renderPipeline(liveInput(), { focusStage: "filings" });
  for (const key of ["Search/add company or year"]) {
    const label = translate(locale, key);
    expect(screen.getByRole("textbox", { name: label })).toBeVisible();
    expect(guide).toContain(`**${label}**`);
  }
  for (const key of ["Clear selection", "Sync selection"]) {
    const label = translate(locale, key);
    expect(screen.getByRole("button", { name: label })).toBeVisible();
    expect(guide).toContain(`**${label}**`);
  }
  expect(guide).not.toMatch(/(?:Filings|원문 수집) → (?:Change|변경)…/);
  fireEvent.click(screen.getByRole("button", { name: translate(locale, "Select {p0}", { p0: translate(locale, "Parse & chunk") }) }));
  expect(screen.getByRole("button", { name: translate(locale, "Parse & chunk selected sources") })).toBeVisible();
  expect(guide).toContain(`**${translate(locale, "Parse & chunk selected sources")}**`);
  expect(screen.queryByText(translate(locale, "Advanced"))).not.toBeInTheDocument();
});

/** Keep source identities distinct from human-facing company/year labels. */
function selectionSource(issuer: string, year: number, onDisk = true): SourceInventory {
  return { registry: /^\d{6}$/.test(issuer) ? "dart" : "sec", issuer, fiscal_year: year, document_id: `raw-${issuer}-${year}`, filing_id: `raw-${issuer}-${year}`, can_redownload: !onDisk, name: issuer === "NVDA" ? "NVIDIA" : issuer, ready: onDisk, on_disk: onDisk, manifest: "manifest.json" };
}

it.each(["en", "ko"] as const)("summarizes 32 documents once with a shared compact grid (%s)", (locale) => {
  localStorage.setItem(LOCALE_KEY, locale);
  const sources = ["AMD", "INTC", "MU", "NVDA", "000660", "005930", "035420"].flatMap((issuer, index) => Array.from({ length: index < 4 ? 6 : index < 6 ? 3 : 2 }, (_, offset) => selectionSource(issuer, 2019 + offset)));
  renderPipeline(liveInput(), { sources: [...sources, sources[0]], acquisition: acquisitionDraft(sources.map((row) => ({ registry: row.registry, issuer: row.issuer, year: row.fiscal_year }))), focusStage: "index" });
  const summary = screen.getByRole("region", { name: locale === "en" ? "Selected documents" : "선택한 문서" });
  expect(within(summary).getByRole("status")).toHaveTextContent(locale === "en" ? "32 documents · 32 ready · 0 to download" : "문서 32개 · 준비됨 32개 · 다운로드 예정 0개");
  expect(within(summary).getAllByRole("group")).toHaveLength(7);
  expect(within(summary).getAllByRole("button", { name: /FY/ })).toHaveLength(32);
  expect(summary.textContent).not.toContain("raw-");
  expect(screen.getByRole("button", { name: locale === "en" ? "Parse & chunk selected sources" : "선택한 원문 파싱 및 청크 생성" })).toHaveClass("primary");
});

it("counts partial and absent source identities and explains disabled parsing", () => {
  const row = selectionSource("NVDA", 2024);
  const sources = [row, { ...row, manifest: "duplicate.json" }, { ...row, document_id: "raw-second", filing_id: "0001045810-24-000030", on_disk: false, ready: false, can_redownload: true }];
  renderPipeline(liveInput(), { sources, acquisition: acquisitionDraft([{ registry: "sec", issuer: "NVDA", year: 2024 }, { registry: "sec", issuer: "AMD", year: 2023 }]), focusStage: "index" });
  expect(within(screen.getByRole("region", { name: "Selected documents" })).getByRole("status")).toHaveTextContent("3 documents · 1 ready · 2 to download");
  const primary = screen.getByRole("button", { name: "Parse & chunk selected sources" });
  expect(primary).toBeDisabled();
  expect(primary).toHaveAccessibleDescription("2 company-years need download or repair in step 1 before parsing.");
  expect(screen.getByRole("button", { name: "NVDA FY2024 · Missing source" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "NVDA FY2024 · Missing source" })).toHaveTextContent("1/2");
});

it.each(["running", "queued"] as const)("replaces parsing with shared progress and cancel while %s", (status) => {
  const job = { ...RUNNING_JOB, kind: "ingest_manifest", status, stage: "prepare", message: "Preparing selected sources", overall_current: 25, overall_total: 100, stage_index: 2, stage_count: 4 };
  const input = liveInput(); const pipeline = derivePipeline(input);
  const stage = pipeline.stages.find((item) => item.id === "index")!;
  stage.job = job; stage.status = status;
  const handlers = renderPipeline(input, { pipeline, focusStage: "index", sources: [selectionSource("NVDA", 2024)], acquisition: acquisitionDraft([{ registry: "sec", issuer: "NVDA", year: 2024 }]) });
  const actions = screen.getByRole("group", { name: "Parsing actions" });
  expect(within(actions).getByRole("progressbar", { name: "Overall progress" })).toHaveAttribute("value", "25");
  expect(within(actions).queryByRole("progressbar", { name: "Current stage" })).not.toBeInTheDocument();
  expect(within(actions).getByText("Stage 2 / 4 · 25%")).toBeVisible();
  expect(document.querySelectorAll(".job-progress")).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "Parse & chunk selected sources" })).toBeNull();
  fireEvent.click(within(actions).getByRole("button", { name: "Cancel" }));
  expect(handlers.onCancelJob).toHaveBeenCalledWith(job.job_id);
  expect(screen.getByRole("button", { name: "NVDA FY2024 · On disk" })).toBeDisabled();
  fireEvent.click(within(actions).getByRole("button", { name: "Open Documents" }));
  const viewJobs = screen.getByRole("button", { name: "View all jobs" });
  expect(viewJobs.closest("header")).not.toBeNull();
  fireEvent.click(viewJobs);
  expect(handlers.onOpenDocuments).toHaveBeenCalledOnce(); expect(handlers.onOpenJobs).toHaveBeenCalledOnce();
});

it("expands 65 selected documents by company without duplicating collapsed entries", () => {
  const sources = Array.from({ length: 13 }, (_, index) => Array.from({ length: 5 }, (_, year) => selectionSource(`C${index}`, 2020 + year))).flat();
  renderPipeline(liveInput(), { focusStage: "index", sources, acquisition: acquisitionDraft(sources.map((row) => ({ registry: row.registry, issuer: row.issuer, year: row.fiscal_year }))) });
  const summary = screen.getByRole("region", { name: "Selected documents" });
  expect(within(summary).getByRole("status")).toHaveTextContent("65 documents");
  expect(within(summary).getAllByRole("group")).toHaveLength(8);
  fireEvent.click(within(summary).getByRole("button", { name: "Show all companies (13)" }));
  expect(within(summary).getAllByRole("button", { name: /FY/ })).toHaveLength(65);
});

/** Exercise the same controlled draft while navigating between both preparation steps. */
function SelectionRoundTrip() {
  const sources = [selectionSource("NVDA", 2024), selectionSource("AMD", 2023)];
  const [draft, setDraft] = useState<AcquisitionForm>(acquisitionDraft(sources.map((row) => ({ registry: row.registry, issuer: row.issuer, year: row.fiscal_year }))));
  const noop = () => undefined;
  return <BuildPipeline pipeline={derivePipeline(liveInput())} focusStage="index" live busy={false} canOperateCorpus acquisition={draft} onAcquisitionChange={setDraft} sources={sources} manifests={[]} onCancelJob={noop} onDownload={noop} onIngestAll={noop} onBackfill={noop} onRebuildBm25={noop} onAsk={noop} onRecheck={noop} onEvaluate={noop} onCompareSnapshots={noop} onOpenDocuments={noop} onOpenJobs={noop} onOpenStatus={noop} onRefresh={noop} />;
}

it("returns to Filings with step 2 deselection preserved in the same sparse draft", () => {
  render(<SelectionRoundTrip />);
  fireEvent.click(screen.getByRole("button", { name: "AMD FY2023 · On disk" }));
  expect(within(screen.getByRole("region", { name: "Selected documents" })).getByRole("status")).toHaveTextContent("1 documents · 1 ready · 0 to download");
  fireEvent.click(screen.getByRole("button", { name: "Change selection in Filings" }));
  expect(screen.getByRole("button", { name: "AMD FY2023 · On disk" })).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByRole("button", { name: "NVDA FY2024 · On disk" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
  expect(screen.queryByRole("button", { name: "AMD FY2023 · On disk" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Change selection in Filings" }));
  fireEvent.click(screen.getByRole("button", { name: "AMD FY2023 · On disk" }));
  fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
  expect(screen.getByRole("button", { name: "AMD FY2023 · On disk" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "Parse & chunk selected sources" })).toBeEnabled();
});


it.each(["en", "ko"] as const)("shows matching dual engine lights, details and row destinations (%s)", async (locale) => {
  vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live");
  vi.resetModules();
  const { BuildPipeline: LivePipeline } = await import("./build-pipeline");
  const { derivePipeline: deriveLivePipeline } = await import("@/lib/pipeline");
  const { I18nProvider: LiveI18n } = await import("@/lib/i18n");
  localStorage.setItem(LOCALE_KEY, locale);
  const readiness: Readiness = { ...READINESS, review_engines: {
    openai: { enabled: true, model: "gpt-test", key_slot: "dev" },
    local: { enabled: true, protocol: "ollama", model: "gemma", models: [{ name: "gemma", selectable: true, loaded: true, placement: "cpu", cpu_performance: { tokens_per_second: 20, measured_at: new Date().toISOString() }, size_bytes: 100, family: null, parameter_size: null, quantization_level: null, capabilities: ["completion"] }] },
  } };
  const onOpenStatus = vi.fn(), onOpenLocalSettings = vi.fn();
  const input = liveInput({ readiness });
  const props = {
    live: true, busy: false, canOperateCorpus: true, acquisition: acquisitionDraft([]), manifests: [], focusStage: "answer_model",
    onAcquisitionChange: vi.fn(), onCancelJob: vi.fn(), onDownload: vi.fn(), onIngestAll: vi.fn(), onIngest: vi.fn(), onBackfill: vi.fn(), onRebuildBm25: vi.fn(), onAsk: vi.fn(), onRecheck: vi.fn(), onEvaluate: vi.fn(), onCompareSnapshots: vi.fn(), onOpenDocuments: vi.fn(), onOpenJobs: vi.fn(), onRefresh: vi.fn(), onOpenStatus, onOpenLocalSettings,
  };
  const { rerender } = render(<LiveI18n><LivePipeline {...props} readiness={readiness} pipeline={deriveLivePipeline(input)} /></LiveI18n>);
  const map = screen.getByRole("button", { name: translate(locale, "Select {p0}", { p0: translate(locale, "Answer model") }) });
  expect(map.querySelectorAll('[data-light="green"]')).toHaveLength(2);
  expect(screen.getByText("20.0 tok/s")).toBeVisible();
  expect(screen.getByText("CPU")).toBeVisible();
  expect(screen.getByText("Ollama")).toBeVisible();
  expect(document.querySelector(".stage-body .stage-status")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: locale === "en" ? "Open System status" : "시스템 상태 열기" }));
  fireEvent.click(screen.getByRole("button", { name: locale === "en" ? "Open Local LLM settings" : "로컬 LLM 설정 열기" }));
  expect(onOpenStatus).toHaveBeenCalledOnce();
  expect(onOpenLocalSettings).toHaveBeenCalledOnce();
  const changed: Readiness = { ...readiness, review_engines: { ...readiness.review_engines, local: { ...readiness.review_engines!.local, models: [readiness.review_engines!.local.models![0], { ...readiness.review_engines!.local.models![0], name: "selected", loaded: false, placement: null, cpu_performance: null }] } } };
  rerender(<LiveI18n><LivePipeline {...props} localModel="selected" readiness={changed} pipeline={deriveLivePipeline({ ...input, readiness: changed })} /></LiveI18n>);
  expect(map.querySelectorAll('[data-light="amber"]')).toHaveLength(1);
  const localRow = screen.getByRole("region", { name: translate(locale, "Local") });
  expect(localRow).toHaveTextContent("selected");
  expect(localRow).toHaveTextContent(translate(locale, "Model not loaded"));
  fireEvent.mouseEnter(screen.getByRole("region", { name: translate(locale, "Terminal preparation") }).querySelector(".preparation-state")!);
  expect(screen.getByRole("tooltip")).toHaveTextContent(translate(locale, "OpenAI only ready · Local: Model not loaded"));
  fireEvent.mouseLeave(screen.getByRole("region", { name: translate(locale, "Terminal preparation") }).querySelector(".terminal-handoff-heading")!);
  expect(map.querySelectorAll('[data-light="green"]')).toHaveLength(1);
  expect(screen.queryByText("20.0 tok/s")).not.toBeInTheDocument();
  expect(screen.queryByText(locale === "en" ? "OpenAI only ready · Local: Model not loaded" : "OpenAI만 준비 · 로컬: 모델 미적재")).not.toBeInTheDocument();
  vi.unstubAllEnvs();
  vi.resetModules();
});

it("offers only fully eligible years and keeps every intended invalid or absent pair as a blocker", () => {
  const changed = { ...selectionSource("NVDA", 2024), ready: false, blocker: "Source bytes changed", filing_id: "0001045810-24-000029" };
  const sources = [changed, selectionSource("AMD", 2023), selectionSource("INTC", 2023, false), selectionSource("MU", 2023)];
  const acquisition = acquisitionDraft([{ registry: "sec", issuer: "NVDA", year: 2024 }, { registry: "sec", issuer: "AMD", year: 2023 }, { registry: "sec", issuer: "MSFT", year: 2022 }]);
  const handlers = renderPipeline(liveInput(), { focusStage: "index", sources, acquisition });
  expect(screen.getByRole("button", { name: /^NVDA FY/ })).toHaveClass("source-blocked");
  expect(screen.queryByRole("button", { name: /^INTC FY/ })).toBeNull();
  expect(screen.getByRole("button", { name: /^MSFT FY/ })).toHaveClass("missing");
  expect(screen.queryByRole("button", { name: "MU FY2023 · On disk" })).toBeNull();
  expect(screen.getByRole("region", { name: "Selected documents" })).toHaveTextContent("NVDA FY2024");
  expect(screen.getByRole("region", { name: "Selected documents" })).toHaveTextContent("0001045810-24-000029: Source bytes changed");
  expect(screen.getByRole("region", { name: "Selected documents" })).toHaveTextContent("MSFT FY2022: Missing source");
  fireEvent.click(screen.getByRole("button", { name: "Parse & chunk selected sources" }));
  expect(handlers.onIngestAll).not.toHaveBeenCalled();
  expect(screen.queryByText("Advanced")).toBeNull();
});

/** A physically present XML does not hide the incomplete archive bundle in step two. */
it.each(["en", "ko"] as const)("shows repair count without fabricating missing files in %s", locale => {
  localStorage.setItem(LOCALE_KEY, locale);
  const broken = { ...selectionSource("005930", 2024), ready: false, can_redownload: true, blocker: "Registered original.zip is missing", filing_id: "20250311001085" };
  const handlers = renderPipeline(liveInput(), { sources: [broken], acquisition: acquisitionDraft([{ registry: "dart", issuer: "005930", year: 2024 }]) });
  fireEvent.click(screen.getByRole("button", { name: translate(locale, "Select {p0}", { p0: translate(locale, "Parse & chunk") }) }));
  const summary = screen.getByRole("region", { name: translate(locale, "Selected documents") });
  expect(within(summary).getByRole("status")).toHaveTextContent(locale === "en" ? "1 documents · 0 ready · 0 to download · Needs repair: 1" : "문서 1개 · 준비됨 0개 · 다운로드 예정 0개 · 조치 필요 1개");
  expect(summary).toHaveTextContent("20250311001085: Registered original.zip is missing");
  const parse = screen.getByRole("button", { name: translate(locale, "Parse & chunk selected sources") });
  expect(parse).toBeDisabled(); fireEvent.click(parse); expect(handlers.onIngestAll).not.toHaveBeenCalled();
});

/** Unsafe conflicts remain visible even when they cannot be queued for acquisition. */
it.each([true, false])("shows non-retryable source conflicts with on_disk=%s", onDisk => {
  const conflict = { ...selectionSource("NVDA", 2024, onDisk), ready: false, can_redownload: false, blocker: "Conflicting primary sources: inspect both registered identities", filing_id: "conflicting-filing" };
  const handlers = renderPipeline(liveInput(), { sources: [conflict], acquisition: acquisitionDraft([{ registry: "sec", issuer: "NVDA", year: 2024 }]) });
  fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
  const summary = screen.getByRole("region", { name: "Selected documents" });
  expect(summary).toHaveTextContent("conflicting-filing: Conflicting primary sources: inspect both registered identities");
  expect(within(summary).getByRole("status")).not.toHaveTextContent("-1 ready");
  if (onDisk) expect(within(summary).getByRole("status")).toHaveTextContent("0 to download · Needs repair: 1");
  const parse = screen.getByRole("button", { name: "Parse & chunk selected sources" });
  expect(parse).toBeDisabled(); fireEvent.click(parse); expect(handlers.onIngestAll).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Select Filings" }));
  const sync = screen.getByRole("button", { name: "Sync selection" });
  expect(sync).toBeDisabled(); fireEvent.click(sync); expect(handlers.onDownload).not.toHaveBeenCalled();
});

it("groups only the left map while retaining the existing execution panel", () => {
  renderPipeline(liveInput());
  const map = screen.getByRole("region", { name: "Data workflow" });
  expect(within(map).getByRole("region", { name: "Data preparation" })).toBeVisible();
  expect(within(map).getByRole("region", { name: "Answer preparation" })).toBeVisible();
  expect(within(map).getByRole("region", { name: "Use and evaluation" })).toBeVisible();
  expect([...map.querySelectorAll(".pipeline-node-number")].map((node) => node.textContent)).toEqual(["1-1", "1-2", "1-3", "1-4", "3-1", "3-2"]);
  fireEvent.click(within(map).getByRole("button", { name: "Select Answer model" }));
  expect(screen.getByRole("heading", { name: "2. Answer model" })).toBeVisible();
});

it.each(["embeddings", "lexical"] as const)("keeps %s teaching UI and locks only execution in PROD", (stageId) => {
  const input = liveInput({ live: false, publicScope: { filings: 0, total: 18, chunks: 0, embedded: null, pending: null, status: "ready" } });
  const handlers = renderPipeline(input, { focusStage: stageId });
  const execution = screen.getByRole("region", { name: "Selected step execution" });
  const scoped = within(execution);
  expect(execution.querySelector(".stage-description")).toBeInTheDocument();
  expect(execution.querySelector(".stage-numbers")).toBeInTheDocument();
  expect(scoped.getByText("Why it matters")).toBeInTheDocument();
  expect(scoped.queryByText("This control runs in DEV mode only.")).not.toBeInTheDocument();
  expect(scoped.queryByText("Select at least one published filing to ask a question.")).not.toBeInTheDocument();
  const reference = scoped.getByText("Implementation and terminal reference").closest("details")!;
  fireEvent.click(scoped.getByText("Implementation and terminal reference"));
  expect(within(reference).getByText("Mechanism")).toBeVisible();
  expect(within(reference).getByText("Design trade-off")).toBeVisible();
  expect(within(reference).getByText(stageId === "embeddings" ? "rag-corpus backfill_embeddings" : "rag-corpus rebuild_bm25")).toBeVisible();
  const action = scoped.getByRole("button", { name: "Next step" });
  expect(action).toBeEnabled();
  fireEvent.click(action);
  expect(scoped.getByRole("button", { name: /Continue/ })).toHaveTextContent("3");
  expect(scoped.getByRole("heading", { name: stageId === "embeddings" ? "1-3. Embeddings" : "1-4. Lexical index (BM25)" })).toBeVisible();
  fireEvent.click(scoped.getByRole("button", { name: /Continue/ }));
  expect(scoped.getByRole("heading", { name: stageId === "embeddings" ? "1-4. Lexical index (BM25)" : "2. Answer model" })).toBeVisible();
  expect(handlers.onBackfill).not.toHaveBeenCalled();
  expect(handlers.onRebuildBm25).not.toHaveBeenCalled();

});


it("uses step-one scope as a read-only summary and navigates without parsing in PROD", () => {
  const ask = vi.fn();
  const handlers = renderPipeline(liveInput({ live: false }), { onAskScope: ask, sources: [], acquisition: acquisitionDraft([{ registry: "sec", issuer: "NVDA", year: 2024 }]) });
  fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
  const summary = screen.getByRole("region", { name: "Selected documents" });
  expect(within(summary).getByRole("button", { name: /NVDA FY2024/ })).toBeEnabled();
  expect(within(summary).getByRole("button", { name: /Remove/ })).toBeEnabled();
  expect(summary).toHaveTextContent("FY2024");
  fireEvent.click(screen.getByRole("button", { name: "Confirm search scope" }));
  expect(ask).not.toHaveBeenCalled();
  expect(handlers.onIngestAll).not.toHaveBeenCalled();
  expect(screen.getByRole("heading", { name: "1-3. Embeddings" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Next step" })).toBeEnabled();
});
