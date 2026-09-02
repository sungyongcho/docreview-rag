import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CANNED_JOB, CANNED_SUITES } from "@/lib/canned";
import { HELP_TOPICS, type HelpScreen } from "@/lib/help-content";
import { derivePipeline, type PipelineInput } from "@/lib/pipeline";
import { ONBOARDING_KEY } from "@/lib/storage";
import { DEFAULT_PROFILE, type Readiness } from "@/lib/types";
import { BuildPipeline } from "./build-pipeline";
import { MeasureWorkspace, type MeasureTab } from "./measure-workspace";
import { Playground } from "./playground";
import { ServiceShell } from "./service-shell";
import { SystemWorkspace, type SystemTab } from "./system-workspace";

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
    documents: 29,
    chunks: 21927,
    embedded_chunks: 21927,
    pending_embeddings: 0,
    bm25_ready: true,
    writable: true,
  },
};

const HIT = {
  chunk_id: 41, doc_id: "NVDA-FY2024", item: "7", kind: "text", citation: "NVDA FY2024 · Item 7",
  start_char: 120, end_char: 480, source_sha256: "0".repeat(64),
  body: "Data Center revenue grew on Hopper demand.", context_header: "Item 7", score: 0.91,
};

/** Ids of the topics that must be on the screen whenever it renders, plus the ids the DOM currently carries. */
function coverage(screen: HelpScreen): { required: string[]; missing: string[] } {
  const required = HELP_TOPICS[screen].filter((topic) => !topic.optional).map((topic) => topic.id);
  const missing = required.filter((id) => !document.querySelector(`[data-help="${id}"]`));
  return { required, missing };
}

function expectPresent(ids: string[]) {
  for (const id of ids) expect(document.querySelector(`[data-help="${id}"]`), id).not.toBeNull();
}

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
}

function stubFetch(handler: (url: string, init?: RequestInit) => unknown) {
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => jsonResponse(handler(String(input), init) ?? {}));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function MeasureHost({ initialTab }: { initialTab: MeasureTab }) {
  const [tab, setTab] = useState<MeasureTab>(initialTab);
  return (
    <MeasureWorkspace
      live
      ready
      profile={DEFAULT_PROFILE}
      onProfileChange={vi.fn()}
      onApplyProfile={vi.fn()}
      onApplySnapshot={vi.fn()}
      jobBoard={{ jobs: [], active_count: 0, queued_count: 0 }}
      onRefreshJobs={vi.fn()}
      tab={tab}
      onTabChange={setTab}
      onOpenSettings={vi.fn()}
    />
  );
}

function SystemHost({ initialTab }: { initialTab: SystemTab }) {
  const [tab, setTab] = useState<SystemTab>(initialTab);
  return <SystemWorkspace live readiness={READINESS} checking={false} onRefresh={vi.fn()} operationsAvailable tab={tab} onTabChange={setTab} />;
}

describe("help topic coverage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem(ONBOARDING_KEY, "done");
    vi.stubGlobal("crypto", { randomUUID: () => "conversation-id" });
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("Build › Pipeline carries every non-optional build hook", () => {
    const input: PipelineInput = {
      live: true,
      healthKind: "healthy",
      readiness: READINESS,
      corpus: { ...READINESS.corpus, provider: "deterministic" },
      manifests: [{ name: "manifest.json", registry: "sec", documents: 21, valid: true, sources_present: 21 }],
      registryCounts: { sec: 21 },
      jobs: [],
      evaluationResults: 1,
      snapshots: 0,
    };
    const noop = vi.fn();
    render(
      <BuildPipeline
        pipeline={derivePipeline(input)}
        live
        busy={false}
        canOperateCorpus
        acquisition={{ registry: "sec", identifiers: "NVDA", years: "2024" }}
        onAcquisitionChange={noop}
        manifests={input.manifests}
        onCancelJob={noop}
        onDownload={noop}
        onIngestAll={noop}
        onIngest={noop}
        onBackfill={noop}
        onRebuildBm25={noop}
        onAsk={noop}
        onRecheck={noop}
        onEvaluate={noop}
        onCompareSnapshots={noop}
        onOpenDocuments={noop}
        onOpenJobs={noop}
        onOpenStatus={noop}
        onRefresh={noop}
      />,
    );

    expect(coverage("build").missing).toEqual([]);
    cleanup();
    render(<BuildPipeline pipeline={derivePipeline({ ...input, live: false, readiness: null, corpus: null })} live={false} busy={false} canOperateCorpus={false} acquisition={{ registry: "sec", identifiers: "", years: "" }} onAcquisitionChange={noop} manifests={[]} onCancelJob={noop} onDownload={noop} onIngestAll={noop} onIngest={noop} onBackfill={noop} onRebuildBm25={noop} onAsk={noop} onRecheck={noop} onEvaluate={noop} onCompareSnapshots={noop} onOpenDocuments={noop} onOpenJobs={noop} onOpenStatus={noop} onRefresh={noop} />);
    expect(coverage("build").missing).toEqual([]);
  });

  it("Ask carries the toolbar and composer hooks in the shell", async () => {
    stubFetch((url) => {
      if (url.endsWith("/health")) return { status: "ok" };
      if (url.endsWith("/ready")) return { ...READINESS, admin_mode: "readonly" };
      if (url.endsWith("/snapshots")) return { snapshots: [] };
      return {};
    });
    render(<ServiceShell />);

    await waitFor(() => expect(screen.getByRole("button", { name: "healthy" })).toBeInTheDocument());
    expect(coverage("review").missing).toEqual([]);
  });

  it("Measure › Playground carries the question, profile fields and previews, then the results once run", async () => {
    stubFetch((url, init) => {
      if (url.endsWith("/admin/retrieval/preview")) return {
        query: JSON.parse(String(init?.body)).query, profile: DEFAULT_PROFILE, score_stage: "rrf",
        component_rankings: { vector: [41], vector_by_language: {}, lexical: [41], lexical_by_language: {} }, results: [HIT],
      };
      if (url.endsWith("/admin/review/preview")) return {
        profile: DEFAULT_PROFILE,
        run: { run_id: "run-1", status: "ok", failure: null, report: { report_kind: "document_review", label: "SUPPORTED", answer: "Hopper.", citations: [], rationale: "", reasons: [] } },
      };
      return {};
    });
    render(<Playground live profile={DEFAULT_PROFILE} onProfileChange={vi.fn()} onOpenSnapshots={vi.fn()} />);

    expect(coverage("measure.playground").missing).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Preview retrieval" }));
    await screen.findByText("Score stage · rrf");
    expectPresent(["measure.playground.rankings", "measure.playground.results"]);
    fireEvent.click(screen.getByRole("button", { name: "Preview review" }));
    await screen.findByText("SUPPORTED");
    expectPresent(["measure.playground.review"]);
  });

  it("Measure › Runs, Snapshots, Golden Tests and Compare carry their hooks on the live build", async () => {
    stubFetch((url) => {
      if (url.endsWith("/admin/evaluations/suites")) return CANNED_SUITES;
      if (url.endsWith("/admin/evaluations/runs")) return { jobs: [CANNED_JOB] };
      if (url.endsWith("/admin/snapshots")) return [];
      if (url.endsWith("/canonical")) return { suite_id: "sec-en", filename: "retrieval.json", sha256: "a".repeat(64), payload: [] };
      if (url.includes("/admin/golden/")) return [];
      return {};
    });
    render(<MeasureHost initialTab="runs" />);

    await screen.findByRole("heading", { name: "New run" });
    expect(coverage("measure.runs").missing).toEqual([]);
    // Opening the disclosure reveals the profile fields, which stay optional topics because the disclosure starts closed.
    fireEvent.change(screen.getByLabelText("Run mode"), { target: { value: "matrix" } });
    expectPresent(["measure.runs.chunk_targets", "measure.runs.k", "measure.runs.rrf_k"]);

    fireEvent.click(screen.getByRole("button", { name: "Snapshots" }));
    await screen.findByRole("heading", { name: "Evaluation snapshots" });
    expect(coverage("measure.snapshots").missing).toEqual([]);
    expectPresent(["measure.snapshots.freeze"]);

    fireEvent.click(screen.getByRole("button", { name: "Golden Tests" }));
    await screen.findByText("retrieval.json");
    expect(coverage("measure.golden").missing).toEqual([]);
    expectPresent(["measure.golden.revision"]);

    fireEvent.click(screen.getByRole("button", { name: "Compare" }));
    expect(coverage("measure.compare").missing).toEqual([]);
  });

  it("System carries the status panel and, per tab, Operations, the API inspector and Usage", async () => {
    vi.stubEnv("NEXT_PUBLIC_OPERATOR_BASE_URL", "http://operator.test");
    vi.stubEnv("NEXT_PUBLIC_OPERATOR_TOKEN", "operator-token");
    stubFetch((url) => (url.endsWith("/admin/usage")
      ? { runs: 0, requests: 0, input_tokens: 0, cached_input_tokens: 0, cache_write_input_tokens: 0, output_tokens: 0, reasoning_tokens: 0, estimated_cost_usd: "0", latest_run_at: null, models: [] }
      : []));
    render(<SystemHost initialTab="status" />);

    expect(coverage("system").missing).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Operations" }));
    expectPresent(["system.operations"]);
    fireEvent.click(screen.getByRole("button", { name: "API inspector" }));
    expectPresent(["system.api"]);
    fireEvent.click(screen.getByRole("button", { name: "Usage" }));
    expectPresent(["system.usage"]);
    await act(async () => undefined);
  });
});
