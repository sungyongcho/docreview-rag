import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { NotificationProvider } from "./notifications";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CANNED_CORPUS, CANNED_JOB, CANNED_SUITES } from "@/lib/canned";
import type { OperatorJob, OperatorJobStatus, Readiness } from "@/lib/types";
import { DEFAULT_PROFILE, DEFAULT_SESSION_PROFILE } from "@/lib/types";
import { BuildWorkspace, type BuildTab, type BuildWorkspaceProps } from "./build-workspace";

afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });

const READY_RUNTIME: Readiness = {
  status: "ready",
  mode: "runtime",
  admin_mode: "live",
  policy_revision: "test",
  models: {},
  review_enabled: true,
  active_review_model: "gpt-5.6-terra",
  review_engines: { openai: { enabled: true, model: "gpt-5.6-terra", key_slot: "dev" }, local: { enabled: false, reason: "not_configured" } },
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

const EMPTY_DOCUMENT_FACETS_FIXTURE = {
  registries: [],
  issuers: [],
  years: [],
  languages: [],
  forms: [],
  parse_statuses: [],
  embedding_statuses: [],
  snapshots: [],
};

const SAMPLE_PAIRS = ["NVDA", "AMD"].flatMap((issuer) => [2023, 2024].map((year) => ({ registry: "sec" as const, issuer, year })));
const SAMPLE_DRAFT = { identifiers: ["NVDA", "AMD"], years: [2023, 2024], pairs: SAMPLE_PAIRS, revision: "sample-v1" };
const COMPANIES = [{ registry: "sec", issuer: "NVDA", name: "NVIDIA" }, { registry: "sec", issuer: "AMD", name: "Advanced Micro Devices" }, { registry: "dart", issuer: "005930", name: "Samsung Electronics" }, { registry: "dart", issuer: "000660", name: "SK hynix" }];

function jsonResponse(payload: unknown) {
  if (payload && typeof payload === "object" && "sources" in payload) {
    const snapshot = payload as Record<string, unknown>;
    payload = { acquisition_companies: COMPANIES, acquisition_draft: SAMPLE_DRAFT, ...snapshot };
  }
  return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
}

type HarnessProps = Partial<Omit<BuildWorkspaceProps, "tab" | "onTabChange">>;

/** The shell owns the tab; this harness stands in for it so tab switches re-render. */
function Harness(props: HarnessProps) {
  const [tab, setTab] = useState<BuildTab>("pipeline");
  return (
    <BuildWorkspace
      live={false}
      ready
      readiness={null}
      healthKind="healthy"
      profile={DEFAULT_PROFILE}
      jobBoard={{ jobs: [], active_count: 0, queued_count: 0 }}
      jobsLoading={false}
      onRetryJob={() => undefined}
      onCancelJob={() => undefined}
      onRefreshJobs={() => undefined}
      onRecheck={() => undefined}
      onNavigate={() => undefined}
      {...props}
      tab={tab}
      onTabChange={setTab}
    />
  );
}

describe("Build workspace", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/admin/evaluations/preparation")) return jsonResponse({ suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] });
      if (url.endsWith("/admin/evaluations/suites")) return jsonResponse(CANNED_SUITES);
      if (url.endsWith("/documents/facets")) return jsonResponse(EMPTY_DOCUMENT_FACETS_FIXTURE);
      if (url.includes("/documents?")) return jsonResponse({ documents: [], total: 0, next_cursor: null });
      if (url.endsWith("/snapshots")) return jsonResponse({ snapshots: [] });
      return jsonResponse({});
    }));
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("keeps real corpus operations disabled in the public read-only mode", () => {
    render(<Harness live={false} />);

    expect(screen.getByText("Read-only portfolio")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync selection" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
    expect(screen.queryByRole("button", { name: "Parse & chunk selected sources" })).toBeNull();
  });

  it("shows active progress on the pipeline and opens the Job Center from it", () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/admin/evaluations/preparation")) return jsonResponse({ suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] });
      if (url.endsWith("/admin/evaluations/suites")) return jsonResponse(CANNED_SUITES);
      let payload: unknown = {};
      if (url.endsWith("/admin/evaluations/runs")) payload = { jobs: [] };
      else if (url.endsWith("/admin/corpus")) payload = { status: {}, documents: [] };
      else if (url.endsWith("/admin/documents/facets")) payload = EMPTY_DOCUMENT_FACETS_FIXTURE;
      else if (url.includes("/admin/documents?")) payload = { documents: [], total: 0, next_cursor: null };
      else if (url.endsWith("/admin/snapshots")) payload = [];
      return jsonResponse(payload);
    }));
    const active = {
      job_id: "admin-progress",
      domain: "corpus" as const,
      kind: "backfill_embeddings",
      request: {},
      status: "running" as const,
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
    render(<Harness live jobBoard={{ jobs: [active], active_count: 1, queued_count: 0 }} />);

    expect(screen.getAllByText("50 / 100 · 50%")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "View all jobs" }));
    expect(screen.getByRole("heading", { name: "Job Center" })).toBeInTheDocument();
    expect(document.querySelector(".job-detail")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Backfill embeddings/ }));
    expect(screen.getAllByText("Embedded 50").length).toBeGreaterThan(0);
  });

  it.each([true, false])("filters and preserves document detail across tabs (operator=%s)", async (live) => {
    const prefix = live ? "/admin" : "/public";
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/admin/evaluations/preparation")) return jsonResponse({ suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] });
      if (url.endsWith("/admin/evaluations/suites")) return jsonResponse(CANNED_SUITES);
      let payload: unknown = {};
      if (url.endsWith("/admin/evaluations/runs")) payload = { jobs: [] };
      else if (url.endsWith("/admin/corpus")) payload = { status: {}, documents: [] };
      else if (url.endsWith(`${prefix}/documents/facets`)) payload = {
        registries: [{ value: "sec", count: 1 }],
        issuers: [{ value: "NVDA", count: 1 }],
        years: [{ value: "2024", count: 1 }],
        languages: [{ value: "en", count: 1 }],
        forms: [{ value: "10-K", count: 1 }],
        parse_statuses: [{ value: "parsed", count: 1 }],
        embedding_statuses: [{ value: "complete", count: 1 }],
        snapshots: [{ value: "3", count: 1, label: "Baseline · ready" }],
      };
      else if (url.includes(`${prefix}/documents?`)) payload = {
        documents: [{
          doc_id: "NVDA-FY2024", registry: "sec", language: "en", issuer: "NVDA",
          issuer_id: "123", fiscal_year: 2024, form: "10-K", filing_date: "2025-02-01",
          report_period: "2024-12-31", filing_id: "filing-1", source_url: "https://example.invalid/acme",
          parse_status: "parsed", source_length: 1000, source_sha256: "d".repeat(64),
          chunk_count: 2, embedded_chunks: 2, text_chunks: 1, table_chunks: 1,
          embedding_status: "complete", snapshot_count: 1,
        }],
        total: 1,
        next_cursor: null,
      };
      else if (url.endsWith(`${prefix}/documents/NVDA-FY2024`)) payload = {
        document: {
          doc_id: "NVDA-FY2024", registry: "sec", language: "en", issuer: "NVDA",
          issuer_id: "123", fiscal_year: 2024, form: "10-K", parse_status: "parsed",
          filing_date: "2025-02-01", report_period: "2024-12-31", filing_id: "filing-1",
          source_url: "https://example.invalid/acme", source_length: 1000,
          source_sha256: "d".repeat(64), chunk_count: 2,
        },
        chunks: [{ chunk_id: 7, ordinal: 0, citation: "NVDA FY2024 · Item 7", span: "chars 0-20", source_sha256: "d".repeat(64), body: "Revenue grew." }],
        text_chunks: 1,
        table_chunks: 1,
        embedded_chunks: 2,
        item_counts: [{ item: "7", count: 2 }],
        embedding_identities: [{ provider: "deterministic", model: "token-hash-384", dimensions: 384, count: 2 }],
        snapshot_memberships: [{ snapshot_id: 3, label: "Baseline", status: "ready", public: true, created_at: "2026-09-01T12:00:00Z" }],
      };
      else if (url.includes("/admin/documents?")) payload = { documents: [], total: 0, next_cursor: null };
      else if (url.endsWith("/admin/snapshots")) payload = [];
      return jsonResponse(payload);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Harness live={live} />);

    fireEvent.click(screen.getByRole("button", { name: "Documents" }));
    expect(await screen.findByRole("combobox", { name: "Filter company" })).toBeInTheDocument();
    await screen.findByRole("option", { name: "NVDA (1)" });
    fireEvent.change(screen.getByRole("combobox", { name: "Filter company" }), { target: { value: "NVDA" } });
    fireEvent.click(screen.getByRole("button", { name: /Filters/ }));
    fireEvent.change(screen.getByRole("combobox", { name: "Group documents" }), { target: { value: "issuer" } });
    await waitFor(() => expect(fetchMock.mock.calls.some(([value]) => String(value).includes("issuer=NVDA"))).toBe(true));
    expect(await screen.findByText("Company · NVDA")).toBeInTheDocument();
    const list = screen.getByRole("table", { name: "Document inventory" }).parentElement!;
    list.scrollTop = 120;
    fireEvent.click(screen.getByRole("button", { name: "NVDA-FY2024" }));

    expect(await screen.findByRole("heading", { name: "Original filing" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Index revisions & snapshot membership" })).toBeInTheDocument();
    expect(screen.getByText("Revision #3 · Baseline")).toBeInTheDocument();
    expect(screen.getByText("NVDA FY2024 · Item 7")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: live ? "Jobs" : "Pipeline" }));
    expect(screen.queryByRole("heading", { name: "Original filing" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Documents" }));
    expect(screen.getByRole("heading", { name: "Original filing" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filter company" })).toHaveValue("NVDA");
    expect(screen.getByRole("combobox", { name: "Group documents" })).toHaveValue("issuer");
    fireEvent.click(screen.getByRole("button", { name: "Back to documents" }));
    expect(list.scrollTop).toBe(120);
    expect(screen.getByRole("row", { name: /NVDA-FY2024/ })).toHaveAttribute("aria-selected", "true");
    if (!live) expect(fetchMock.mock.calls.every(([value]) => !String(value).includes("/admin/"))).toBe(true);
  });

  it("orders build steps from the administrator snapshot", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/admin/evaluations/preparation")) return jsonResponse({ suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] });
      if (url.endsWith("/admin/evaluations/suites")) return jsonResponse(CANNED_SUITES);
      let payload: unknown = {};
      if (url.endsWith("/admin/evaluations/suites")) payload = CANNED_SUITES;
      else if (url.endsWith("/admin/evaluations/runs")) payload = { jobs: [CANNED_JOB] };
      else if (url.endsWith("/admin/corpus/jobs") && init?.method === "POST") payload = { job_id: "queued", status: "queued" };
      else if (url.endsWith("/admin/corpus")) payload = {
        status: {
          database_connected: true, schema_status: "compatible", schema_message: "ok",
          documents: 29, chunks: 21927, embedded_chunks: 21927, pending_embeddings: 0,
          bm25_ready: true, writable: true, provider: "deterministic",
        },
        sources: ["AMD", "NVDA"].flatMap((issuer) => [2023, 2024].map((year) => ({ manifest: "manifest.json", document_id: `${issuer}-FY${year}`, filing_id: `${issuer}-FY${year}`, can_redownload: false, registry: "sec", issuer, name: issuer, fiscal_year: year, ready: true, on_disk: true }))),
        manifests: [{
          name: "manifest.json", corpus_id: "test", registries: ["sec", "dart"], documents: 30, valid: true, sources_present: 30,
          selections: [
            { selection_id: "sec-evaluation", document_ids: Array.from({ length: 21 }, (_, i) => `sec-${i}`), artifact_ids: Array.from({ length: 21 }, (_, i) => `sec-source-${i}`), sources_present: 21 },
            { selection_id: "dart-evaluation", document_ids: Array.from({ length: 9 }, (_, i) => `dart-${i}`), artifact_ids: Array.from({ length: 9 }, (_, i) => `dart-source-${i}`), sources_present: 9 },
          ],
        }],
        documents: [],
      };
      else if (url.endsWith("/admin/documents/facets")) payload = {
        ...EMPTY_DOCUMENT_FACETS_FIXTURE,
        registries: [{ value: "sec", count: 20 }, { value: "dart", count: 9 }],
      };
      else if (url.includes("/admin/documents?")) payload = { documents: [], total: 0, next_cursor: null };
      else if (url.endsWith("/admin/snapshots")) payload = [];
      return jsonResponse(payload);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Harness live readiness={READY_RUNTIME} />);

    fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
    expect(await screen.findByText("29 documents")).toBeInTheDocument();
    expect(screen.getByText("21,927 chunks")).toBeInTheDocument();
    expect(await screen.findByText("Corpus ready")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Select Filings" }));
    expect(screen.getByText("4 / 4 filings on disk")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
    const ingestButtons = screen.getAllByRole("button", { name: "Parse & chunk selected sources" });
    for (const button of ingestButtons) expect(button).toBeEnabled();
    expect(within(screen.getByRole("region", { name: "Selected documents" })).getByRole("status")).toHaveTextContent("4 documents · 4 ready · 0 to download");
    fireEvent.click(ingestButtons[0]);

    await waitFor(() => {
      const queued = fetchMock.mock.calls.filter(([value, init]) => String(value).endsWith("/admin/corpus/jobs") && (init as RequestInit | undefined)?.method === "POST");
      expect(queued).toHaveLength(1);
    });
    const bodies = fetchMock.mock.calls
      .filter(([value, init]) => String(value).endsWith("/admin/corpus/jobs") && (init as RequestInit | undefined)?.method === "POST")
      .map(([, init]) => JSON.parse(String((init as RequestInit).body)) as Record<string, unknown>);
    expect(bodies).toEqual([
      { kind: "ingest_selected", identifiers: ["AMD", "NVDA"], years: [2023, 2024], document_ids: ["AMD-FY2023", "AMD-FY2024", "NVDA-FY2023", "NVDA-FY2024"] },
    ]);
  });

  it("never calls the administrator API in the public build", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/admin/evaluations/preparation")) return jsonResponse({ suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] });
      if (url.endsWith("/admin/evaluations/suites")) return jsonResponse(CANNED_SUITES);
      const payload: unknown = url.endsWith("/snapshots") ? { snapshots: [] } : url.endsWith("/public/documents/facets") ? EMPTY_DOCUMENT_FACETS_FIXTURE : url.includes("/public/documents?") ? { documents: [], total: 0, next_cursor: null } : {};
      return jsonResponse(payload);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Harness live={false} />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchMock.mock.calls.every(([value]) => !String(value).includes("/admin/"))).toBe(true);
    expect(screen.queryByText("Portfolio fixture")).not.toBeInTheDocument();
    expect(await screen.findByText("No portfolio filings have been published yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Select Evaluate" }));
    expect(screen.getByRole("button", { name: "Open Quality checks" })).toBeInTheDocument();
    expect(screen.getByText("Open Quality checks to explore datasets, try evaluation settings and compare published results. Running new evaluations is available in DEV mode.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Documents" }));
    expect(await screen.findByText("No documents match these filters.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([value]) => String(value).includes("/public/documents?"))).toBe(true);
    expect(screen.queryByText("NVDA-FY2024")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.every(([value]) => !String(value).includes("/admin/"))).toBe(true);

    expect(screen.queryByRole("button", { name: "Jobs" })).not.toBeInTheDocument();
  });

  it("shows the answer-model fix when review is disabled", () => {
    const onRecheck = vi.fn();
    render(
      <Harness
        live={false}
        readiness={{ ...READY_RUNTIME, review_enabled: false, active_review_model: null, review_engines: { openai: { enabled: false }, local: { enabled: false, reason: "not_configured" } } }}
        onRecheck={onRecheck}
      />,
    );

    expect(screen.getByRole("button", { name: "Select Answer model" })).toHaveTextContent("Not configured");
    fireEvent.click(screen.getByRole("button", { name: "Select Answer model" }));
    expect(screen.getByRole("button", { name: "Next step" })).toBeEnabled();
    expect(onRecheck).not.toHaveBeenCalled();
  });

  it("routes quality navigation and confirmed public questions through their handlers", () => {
    const onNavigate = vi.fn();
    const onAskScope = vi.fn();
    const published = { ...CANNED_CORPUS.documents[0], chunk_count: 10, embedded_chunks: 10, embedding_status: "complete" as const, text_chunks: 10, table_chunks: 0, snapshot_count: 1 };
    render(<Harness live={false} onNavigate={onNavigate} onAskScope={onAskScope} readiness={READY_RUNTIME} publishedCorpus={{ documents: [published], status: "ready", refresh: vi.fn() }} publicProfile={{ ...DEFAULT_SESSION_PROFILE, doc_ids: [published.doc_id] }} />);

    fireEvent.click(screen.getByRole("button", { name: "Select Evaluate" }));
    fireEvent.click(screen.getByRole("button", { name: "Open Quality checks" }));
    expect(onNavigate).toHaveBeenCalledWith({ view: "measure", tab: "runs" });
    // Confirm the public scope and acknowledge preparation before asking.
    fireEvent.click(screen.getByRole("button", { name: "Select Filings" }));
    fireEvent.click(screen.getByRole("button", { name: "Review parsing and chunks" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm search scope" }));
    for (let step = 0; step < 2; step++) {
      fireEvent.click(screen.getByRole("button", { name: "Next step" }));
      fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
    }
    fireEvent.click(screen.getByRole("button", { name: "Next step" }));
    expect(screen.getByRole("button", { name: "Ask about this scope" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Ask about this scope" }));
    expect(onAskScope).toHaveBeenCalledExactlyOnceWith({ registries: [], issuers: [], fiscal_years: [] });
  });

  it("queues a quick evaluation with a non-empty chunk target list", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/admin/evaluations/preparation")) return jsonResponse({ suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] });
      if (url.endsWith("/admin/evaluations/suites")) return jsonResponse(CANNED_SUITES);
      let payload: unknown = {};
      if (url.endsWith("/admin/evaluations/runs") && init?.method === "POST") payload = { ...CANNED_JOB, job_id: "eval-new", status: "queued", result_id: null, result_ids: [] };
      else if (url.endsWith("/admin/evaluations/runs")) payload = { jobs: [] };
      else if (url.endsWith("/admin/corpus")) payload = {
        status: {
          database_connected: true, schema_status: "compatible", schema_message: "ok",
          documents: 30, chunks: 22367, embedded_chunks: 22367, pending_embeddings: 0,
          bm25_ready: true, writable: true, provider: "deterministic",
        },
        sources: ["NVDA", "AMD"].flatMap((issuer) => [2023, 2024].map((year) => ({ manifest: "manifest.json", document_id: `${issuer}-FY${year}`, filing_id: `${issuer}-FY${year}`, can_redownload: false, registry: "sec", issuer, name: issuer, fiscal_year: year, ready: true, on_disk: true }))),
        manifests: [{ name: "manifest.json", corpus_id: "sec", registries: ["sec"], documents: 21, valid: true, sources_present: 21, selections: [{ selection_id: "sec-evaluation", document_ids: Array.from({length: 21}, (_, i) => `sec-${i}`), artifact_ids: Array.from({length: 21}, (_, i) => `sec-source-${i}`), sources_present: 21 }] }],
        documents: [],
      };
      else if (url.endsWith("/admin/documents/facets")) payload = { ...EMPTY_DOCUMENT_FACETS_FIXTURE, registries: [{ value: "sec", count: 21 }, { value: "dart", count: 9 }] };
      else if (url.includes("/admin/golden/")) payload = [];
      else if (url.includes("/admin/documents?")) payload = { documents: [], total: 0, next_cursor: null };
      else if (url.endsWith("/admin/snapshots")) payload = [];
      return jsonResponse(payload);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Harness live readiness={READY_RUNTIME} />);

    await screen.findByText("Corpus ready");
    fireEvent.click(screen.getByRole("button", { name: "Select Evaluate" }));
    fireEvent.click(screen.getByRole("button", { name: "Run quick evaluation" }));

    await waitFor(() => {
      const posted = fetchMock.mock.calls.find(([value, init]) => String(value).endsWith("/admin/evaluations/runs") && (init as RequestInit | undefined)?.method === "POST");
      expect(posted).toBeDefined();
      const body = JSON.parse(String((posted?.[1] as RequestInit).body)) as Record<string, unknown>;
      expect(body.mode).toBe("quick");
      expect(body.golden_revision_id).toBeNull();
      expect(Array.isArray(body.target_tokens) && (body.target_tokens as number[]).length > 0).toBe(true);
    });
  });
});


describe("preparation refresh after corpus jobs", () => {
  afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });
  it.each(["succeeded", "failed", "cancelled", "interrupted"] as const)("refreshes once for %s and ignores repeated polls", async (status: OperatorJobStatus) => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/admin/evaluations/preparation")) return jsonResponse({ suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] });
      if (url.endsWith("/admin/evaluations/suites")) return jsonResponse(CANNED_SUITES);
      if (url.endsWith("/admin/corpus")) return jsonResponse({ mode: "live", ...CANNED_CORPUS });
      if (url.endsWith("/documents/facets")) return jsonResponse(EMPTY_DOCUMENT_FACETS_FIXTURE);
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const job: OperatorJob = { job_id: "corpus-terminal", domain: "corpus", kind: "ingest_manifest", request: {}, status: "running", stage: "parse", current: 0, total: 1, detail_current: null, detail_total: null, message: "Parsing", error_code: null, result_refs: {}, queue_position: null, can_cancel: true, can_retry: false, created_at: "2026-01-01", started_at: "2026-01-01", finished_at: null, updated_at: "2026-01-01" };
    const board = (row: OperatorJob) => ({ jobs: [row], active_count: row.status === "running" ? 1 : 0, queued_count: 0 });
    const { rerender } = render(<Harness live jobBoard={board(job)} />);
    const corpusCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/admin/corpus")).length;
    await waitFor(() => expect(corpusCalls()).toBe(1));
    const terminal = { ...job, status };
    rerender(<Harness live jobBoard={board(terminal)} />);
    await waitFor(() => expect(corpusCalls()).toBe(2));
    rerender(<Harness live jobBoard={board({ ...terminal })} />);
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/admin/evaluations/runs")).length).toBeGreaterThan(0));
    expect(corpusCalls()).toBe(2);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/documents/facets"))).toHaveLength(2);
  });

  it("does not expose local manifest and evaluation selections in parsing", async () => {
    const manifest = CANNED_CORPUS.manifests[0];
    const selection = manifest.selections[0];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/admin/corpus")) return jsonResponse({ mode: "live", ...CANNED_CORPUS, acquisition_draft: SAMPLE_DRAFT, sources: [], status: { ...CANNED_CORPUS.status, writable: true }, manifests: [{ ...manifest, selections: [selection, { ...selection, selection_id: "overlap" }] }] });
      if (String(input).endsWith("/documents/facets")) return jsonResponse(EMPTY_DOCUMENT_FACETS_FIXTURE);
      return jsonResponse([]);
    }));
    render(<Harness live />);
    fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
    await screen.findByRole("button", { name: "NVDA FY2024 · Missing source" });
    expect(screen.getByRole("button", { name: "NVDA FY2024 · Missing source" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("checkbox", { name: /sec-evaluation|overlap/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Advanced")).not.toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Selected documents" })).getByRole("status")).toHaveTextContent("4 documents · 0 ready · 4 to download");
  });
});


it("queues exactly the selected company years after changing matrix cells", async () => {
  const onRefreshJobs = vi.fn();
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/admin/evaluations/preparation")) return jsonResponse({ suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] });
    if (url.endsWith("/admin/evaluations/suites")) return jsonResponse(CANNED_SUITES);
    if (url.endsWith("/admin/corpus/jobs") && init?.method === "POST") return jsonResponse({ job_id: "acquisition", status: "queued" });
    if (url.endsWith("/admin/corpus")) return jsonResponse({ mode: "live", ...CANNED_CORPUS, acquisition_draft: SAMPLE_DRAFT, sources: [], status: { ...CANNED_CORPUS.status, database_connected: true, schema_status: "compatible", documents: 0, chunks: 0, embedded_chunks: 0, pending_embeddings: 0, writable: true, bm25_ready: false }, documents: [], manifests: CANNED_CORPUS.manifests.map((manifest) => ({ ...manifest, sources_present: 0 })) });
    if (url.endsWith("/documents/facets")) return jsonResponse(EMPTY_DOCUMENT_FACETS_FIXTURE);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<Harness live ready={false} onRefreshJobs={onRefreshJobs} />);
  await screen.findByText("0 / 4 filings on disk");
  fireEvent.click(screen.getByRole("button", { name: /^Remove AMD.*from basket/ }));
  fireEvent.click(screen.getByRole("button", { name: /^NVDA FY2023/ }));
  const years = screen.getByRole("textbox", { name: "Search/add company or year" });
  const download = screen.getByRole("button", { name: "Sync selection" });
  fireEvent.focus(years);
  fireEvent.mouseDown(download);
  fireEvent.blur(years, { relatedTarget: download });
  fireEvent.mouseUp(download);
  fireEvent.click(download);
  await waitFor(() => expect(onRefreshJobs).toHaveBeenCalledTimes(1));
  const submitted = fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith("/admin/corpus/jobs") && init?.method === "POST");
  expect(submitted).toHaveLength(1);
  expect(JSON.parse(String(submitted[0][1]?.body))).toEqual({ kind: "acquire_edgar", identifiers: ["NVDA"], years: [2024] });
  cleanup(); vi.unstubAllGlobals();
});


it("keeps source acquisition available during schema drift and exposes terminal recovery", async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/admin/evaluations/preparation")) return jsonResponse({ suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] });
    if (url.endsWith("/admin/evaluations/suites")) return jsonResponse(CANNED_SUITES);
    if (url.endsWith("/admin/corpus")) return jsonResponse({ mode: "live", ...CANNED_CORPUS, acquisition_draft: SAMPLE_DRAFT, sources: [], status: { ...CANNED_CORPUS.status, database_connected: true, schema_status: "drifted", schema_message: "Missing source columns", writable: true }, documents: [], manifests: CANNED_CORPUS.manifests.map((manifest) => ({ ...manifest, sources_present: 0 })) });
    if (url.endsWith("/documents/facets")) return jsonResponse(EMPTY_DOCUMENT_FACETS_FIXTURE);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<Harness live ready={false} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Sync selection" })).toBeEnabled());
  expect(screen.getByRole("region", { name: "Terminal preparation" })).toHaveTextContent("Ready to run");
  expect(screen.getByRole("region", { name: "Terminal preparation" }).closest("header")).not.toBeNull();
  expect(document.getElementById("pipeline-setup-checks")).toHaveTextContent("scripts.schema recover --return-stage filings");
  expect(screen.getByRole("button", { name: "Check updated status" })).toBeEnabled();
  expect(screen.queryByText("data/ not writable")).not.toBeInTheDocument();
});


it.each([false, true])("queues mixed companies by source and reports partial submission (failure=%s)", async (failDart) => {
  const submitted: Record<string, unknown>[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/admin/evaluations/preparation")) return jsonResponse({ suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] });
    if (url.endsWith("/admin/evaluations/suites")) return jsonResponse(CANNED_SUITES);
    if (url.endsWith("/admin/corpus/jobs") && init?.method === "POST") {
      const body = JSON.parse(String(init.body)); submitted.push(body);
      if (failDart && body.kind === "acquire_dart") return new Response(JSON.stringify({ error: { message: "DART submission unavailable" } }), { status: 503, headers: { "Content-Type": "application/json" } });
      return jsonResponse({ job_id: String(submitted.length), status: "queued" });
    }
    if (url.endsWith("/admin/corpus")) return jsonResponse({ mode: "live", ...CANNED_CORPUS, acquisition_draft: SAMPLE_DRAFT, sources: [], status: { ...CANNED_CORPUS.status, database_connected: true, schema_status: "compatible", writable: true }, documents: [], manifests: CANNED_CORPUS.manifests.map((manifest) => ({ ...manifest, sources_present: 0 })) });
    if (url.endsWith("/documents/facets")) return jsonResponse(EMPTY_DOCUMENT_FACETS_FIXTURE);
    return jsonResponse([]);
  }));
  render(<NotificationProvider><Harness live ready={false} /></NotificationProvider>);
  await screen.findByText("0 / 4 filings on disk");
  fireEvent.change(screen.getByRole("textbox", { name: "Search/add company or year" }), { target: { value: "005930,000660" } });
  fireEvent.keyDown(screen.getByRole("textbox", { name: "Search/add company or year" }), { key: "Enter" });
  for (const year of [2023, 2024]) { const choice = screen.queryByRole("button", { name: `FY${year}` }); if (choice) fireEvent.click(choice); }
  fireEvent.click(screen.getByRole("button", { name: /^Add years for 000660/ }));
  for (const year of [2023, 2024]) { const choice = screen.queryByRole("button", { name: `FY${year}` }); if (choice) fireEvent.click(choice); }
  fireEvent.click(screen.getByRole("button", { name: "Sync selection" }));
  await waitFor(() => expect(submitted).toHaveLength(2));
  expect(submitted).toEqual([
    { kind: "acquire_edgar", identifiers: ["AMD", "NVDA"], years: [2023, 2024] },
    { kind: "acquire_dart", identifiers: ["000660", "005930"], years: [2023, 2024] },
  ]);
  if (failDart) expect(await screen.findByText(/Acquisition stopped after 1 queued jobs/)).toBeInTheDocument();
});


it("initializes empty, accepts a server sample, and reconciles disk changes without overwriting an edited draft", async () => {
  const sourceRows = ["NVDA", "AMD"].flatMap((issuer) => [2023, 2024].map((year) => ({ manifest: "manifest.json", document_id: `${issuer}-FY${year}`, filing_id: `${issuer}-FY${year}`, can_redownload: false, registry: "sec", issuer, name: issuer, fiscal_year: year, ready: true, on_disk: true })));
  let sources: typeof sourceRows = [];
  let preset: typeof SAMPLE_DRAFT = { identifiers: [], years: [], pairs: [], revision: "empty-v1" };
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/admin/evaluations/preparation")) return jsonResponse({ suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] });
    if (url.endsWith("/admin/evaluations/suites")) return jsonResponse(CANNED_SUITES);
    if (url.endsWith("/admin/corpus")) return jsonResponse({ mode: "live", ...CANNED_CORPUS, status: { ...CANNED_CORPUS.status, database_connected: true, schema_status: "compatible", writable: true }, sources, acquisition_draft: preset });
    if (url.endsWith("/documents/facets")) return jsonResponse(EMPTY_DOCUMENT_FACETS_FIXTURE);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<Harness live />);
  fireEvent.click(screen.getByRole("button", { name: "Select Filings" }));
  await screen.findByText("No sources yet. Add a company and fiscal year below.");
  expect(screen.queryByRole("button", { name: /^NVDA FY/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Sync selection" })).toBeDisabled();
  preset = SAMPLE_DRAFT;
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await screen.findByRole("button", { name: /^Add years for NVDA/ });
  expect(screen.getByText("0 / 4 filings on disk")).toBeInTheDocument();
  sources = sourceRows;
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await screen.findByText("4 / 4 filings on disk");
  fireEvent.click(screen.getByRole("button", { name: /^Remove AMD.*from basket/ }));
  expect(screen.getByText(/On disk not selected: 2/)).toBeInTheDocument();
  sources = sourceRows.filter((row) => row.document_id !== "NVDA-FY2023");
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() => expect(screen.getByRole("button", { name: /^NVDA FY2023/ })).toHaveAccessibleName("NVDA FY2023 · Missing source"));
  expect(screen.queryByRole("button", { name: /^Remove AMD.*from basket/ })).toBeNull();
  expect(screen.getByRole("button", { name: /^NVDA FY2023/ })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "Select everything on disk" }));
  expect(screen.getAllByRole("button", { name: /^AMD FY/ }).every((button) => button.getAttribute("aria-pressed") === "true")).toBe(true);
  expect(screen.queryByRole("button", { name: "Sync draft with downloaded sources" })).not.toBeInTheDocument();
});

describe("quick evaluation feedback", () => {
  /** Serve current corpus facts and persist the request returned by the queue endpoint. */
  function stubQueue(corpus: Partial<Readiness["corpus"]> = {}, duplicate = false) {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/admin/evaluations/preparation")) return jsonResponse({ suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] });
      if (url.endsWith("/admin/evaluations/suites")) return jsonResponse(CANNED_SUITES);
      if (url.endsWith("/admin/corpus")) return jsonResponse({ mode: "live", ...CANNED_CORPUS, status: { ...READY_RUNTIME.corpus, ...corpus }, sources: [] });
      if (url.endsWith("/admin/evaluations/runs") && init?.method === "POST") {
        if (duplicate) return new Response(JSON.stringify({ error: { code: "evaluation_already_queued", message: "Already queued" } }), { status: 409, headers: { "content-type": "application/json" } });
        return jsonResponse({ ...CANNED_JOB, job_id: "eval-queued", status: "queued", result_id: null, request: JSON.parse(String(init.body)) });
      }
      if (url.endsWith("/admin/evaluations/runs")) return jsonResponse({ jobs: [] });
      if (url.endsWith("/documents/facets")) return jsonResponse(EMPTY_DOCUMENT_FACETS_FIXTURE);
      if (url.includes("/documents?")) return jsonResponse({ documents: [], total: 0, next_cursor: null });
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  /** A recorded corpus job whose backfill must finish before evaluation. */
  function preparingJob(): OperatorJob {
    return {
      job_id: "embedding-active", domain: "corpus", kind: "backfill_embeddings", request: {},
      status: "running", stage: "embed", current: 90, total: 100, detail_current: null, detail_total: null,
      message: "Embedding", error_code: null, result_refs: {}, queue_position: null, can_cancel: true, can_retry: false,
      created_at: "2026-09-07T10:00:00Z", started_at: "2026-09-07T10:00:00Z", finished_at: null, updated_at: "2026-09-07T10:00:01Z",
    };
  }

  async function openEvaluation() {
    fireEvent.click(screen.getByRole("button", { name: "Pipeline" }));
    fireEvent.click(screen.getByRole("button", { name: "Select Evaluate" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Run quick evaluation" })).toBeEnabled());
  }

  it("queues behind embedding with a waiting toast and keeps the submitted profile", async () => {
    const fetchMock = stubQueue({ pending_embeddings: 10 });
    const profile = { ...DEFAULT_PROFILE, k: 9 };
    render(<NotificationProvider><Harness live ready={false} readiness={READY_RUNTIME} profile={profile} jobBoard={{ jobs: [preparingJob()], active_count: 1, queued_count: 0 }} /></NotificationProvider>);
    await openEvaluation();
    fireEvent.click(screen.getByRole("button", { name: "Run quick evaluation" }));
    expect(await screen.findByText("Embedding is in progress. The evaluation was added to the job queue and starts when embedding finishes.")).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body)).profile).toEqual(profile);
  });

  it("reports a healthy queue then detects the same local request without a second POST", async () => {
    const fetchMock = stubQueue();
    render(<NotificationProvider><Harness live readiness={READY_RUNTIME} /></NotificationProvider>);
    await openEvaluation();
    fireEvent.click(screen.getByRole("button", { name: "Run quick evaluation" }));
    expect(await screen.findByText("Evaluation queued.")).toBeInTheDocument();
    await openEvaluation();
    fireEvent.click(screen.getByRole("button", { name: "Run quick evaluation" }));
    await waitFor(() => expect(screen.getAllByText("The same evaluation is already queued.").length).toBeGreaterThan(0));
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith("/admin/evaluations/runs") && init?.method === "POST")).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Open Jobs" }).length).toBeGreaterThan(0);
  });

  it("handles an authoritative duplicate response with a notice and Jobs action", async () => {
    stubQueue({}, true);
    render(<NotificationProvider><Harness live readiness={READY_RUNTIME} /></NotificationProvider>);
    await openEvaluation();
    fireEvent.click(screen.getByRole("button", { name: "Run quick evaluation" }));
    await waitFor(() => expect(screen.getAllByText("The same evaluation is already queued.").length).toBeGreaterThan(0));
    expect(screen.getAllByRole("button", { name: "Open Jobs" }).length).toBeGreaterThan(0);
  });

  it.each([
    [{ database_connected: false }, "Database is unreachable"],
    [{ schema_status: "empty" }, "Database schema is empty"],
    [{ schema_status: "drifted" }, "Database schema is incompatible"],
    [{ writable: false }, "Source directory is not writable"],
    [{ bm25_ready: false, pending_embeddings: 10 }, "Complete BM25 (step 4) before evaluating."],
  ] as const)("disables the action and reports the current blocker: %j", async (corpus, reason) => {
    const fetchMock = stubQueue(corpus);
    render(<Harness live ready={false} profile={{ ...DEFAULT_PROFILE, lexical_ranker: "bm25" }} jobBoard={{ jobs: [preparingJob()], active_count: 1, queued_count: 0 }} />);
    fireEvent.click(screen.getByRole("button", { name: "Select Evaluate" }));
    await waitFor(() => expect(screen.getAllByText(reason).length).toBeGreaterThan(0));
    expect(screen.getByRole("button", { name: "Run quick evaluation" })).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith("/admin/evaluations/runs") && init?.method === "POST")).toHaveLength(0);
  });
});

describe("refresh hygiene", () => {
  afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });

  const failure = (code: string, message: string) => new Response(JSON.stringify({ error: { code, message } }), { status: 503, headers: { "content-type": "application/json" } });

  function stubAdmin(override: (url: string) => Response | undefined) {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/admin/evaluations/preparation")) return jsonResponse({ suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] });
      if (url.endsWith("/admin/evaluations/suites")) return jsonResponse(CANNED_SUITES);
      const custom = override(url);
      if (custom) return custom;
      if (url.endsWith("/admin/corpus")) return jsonResponse({ mode: "live", ...CANNED_CORPUS });
      if (url.endsWith("/documents/facets")) return jsonResponse(EMPTY_DOCUMENT_FACETS_FIXTURE);
      if (url.endsWith("/admin/evaluations/runs")) return jsonResponse({ jobs: [] });
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  const corpusJob: OperatorJob = { job_id: "corpus-progress", domain: "corpus", kind: "ingest_manifest", request: {}, status: "running", stage: "parse", current: 1, total: 9, detail_current: null, detail_total: null, message: "Parsing", error_code: null, result_refs: {}, queue_position: null, can_cancel: true, can_retry: false, created_at: "2026-09-01T12:00:00Z", started_at: "2026-09-01T12:00:01Z", finished_at: null, updated_at: "2026-09-01T12:00:02Z" };

  it("keeps the last corpus state, shows an inline notice and still fetches snapshots when the snapshot read fails", async () => {
    const fetchMock = stubAdmin((url) => url.endsWith("/admin/corpus") ? failure("database_unavailable", "Database is busy") : undefined);
    render(<NotificationProvider><Harness live /></NotificationProvider>);
    await screen.findByText("Corpus status could not be refreshed: Database is busy");
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/admin/snapshots"))).toBe(true));
    expect(screen.getByText("Corpus status could not be refreshed: Database is busy").closest(".notification-stack")).toHaveAttribute("data-placement", "overlay");
  });

  it("surfaces a facet failure as a toast with the server message", async () => {
    stubAdmin((url) => url.endsWith("/documents/facets") ? failure("schema_not_ready", "Schema is not ready") : undefined);
    render(<NotificationProvider><Harness live /></NotificationProvider>);
    await screen.findByText("Document filters could not be loaded: Schema is not ready");
  });

  it("keeps manual refresh failures in one toast per failing source", async () => {
    stubAdmin((url) => url.endsWith("/admin/corpus") ? failure("database_unavailable", "Database is busy") : undefined);
    render(<NotificationProvider><Harness live /></NotificationProvider>);
    await screen.findByText("Corpus status could not be refreshed: Database is busy");
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText("Corpus status could not be refreshed: Database is busy");
    expect(screen.getAllByText("Corpus status could not be refreshed: Database is busy")).toHaveLength(1);
  });

  it("does not refetch evaluation runs when only a corpus job reports progress", async () => {
    const fetchMock = stubAdmin(() => undefined);
    const board = (rows: OperatorJob[]) => ({ jobs: rows, active_count: rows.filter((row) => row.status === "running").length, queued_count: 0 });
    const { rerender } = render(<Harness live jobBoard={board([corpusJob])} />);
    const runsCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/admin/evaluations/runs")).length;
    await waitFor(() => expect(runsCalls()).toBeGreaterThan(0));
    await act(async () => undefined);
    const before = runsCalls();
    rerender(<Harness live jobBoard={board([{ ...corpusJob, current: 2, updated_at: "2026-09-01T12:00:03Z" }])} />);
    rerender(<Harness live jobBoard={board([{ ...corpusJob, current: 3, updated_at: "2026-09-01T12:00:04Z" }])} />);
    await act(async () => undefined);
    expect(runsCalls()).toBe(before);
    rerender(<Harness live jobBoard={board([corpusJob, { ...corpusJob, job_id: "eval-1", domain: "evaluation", kind: "quick" }])} />);
    await waitFor(() => expect(runsCalls()).toBe(before + 1));
  });
});


it.each([false, true])("queues exact sparse pairs and reports partial indexing submission: %s", async (failIndex) => {
  const sources = ["NVDA", "AMD"].flatMap((issuer) => [2023, 2024].map((year) => ({ manifest: "manifest.json", document_id: `${issuer}-${year}`, registry: "sec", issuer, name: issuer, fiscal_year: year, ready: true, on_disk: !(issuer === "NVDA" && year === 2024) })));
  const submitted: Array<Record<string, unknown>> = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/admin/evaluations/preparation")) return jsonResponse({ suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] });
    if (url.endsWith("/admin/evaluations/suites")) return jsonResponse(CANNED_SUITES);
    if (url.endsWith("/admin/corpus/jobs") && init?.method === "POST") { const body = JSON.parse(String(init.body)); submitted.push(body); if (failIndex && body.kind === "ingest_selected" && body.identifiers[0] === "NVDA") return new Response(JSON.stringify({ error: { code: "unavailable", message: "Indexing unavailable" } }), { status: 503 }); return jsonResponse({ job_id: String(submitted.length), status: "queued" }); }
    if (url.endsWith("/admin/corpus")) return jsonResponse({ mode: "live", ...CANNED_CORPUS, sources, status: { ...CANNED_CORPUS.status, writable: true, database_connected: true, schema_status: "compatible" } });
    if (url.endsWith("/documents/facets")) return jsonResponse(EMPTY_DOCUMENT_FACETS_FIXTURE);
    return jsonResponse([]);
  }));
  render(<NotificationProvider><Harness live /></NotificationProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Select Filings" }));
  await screen.findByRole("button", { name: /^NVDA FY2024/ });
  await waitFor(() => expect(screen.getByRole("button", { name: "Clear selection" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
  fireEvent.click(screen.getByRole("button", { name: /^AMD FY2023/ }));
  fireEvent.click(screen.getByRole("button", { name: /^NVDA FY2024/ }));
  fireEvent.click(screen.getByRole("button", { name: "Sync selection" }));
  await waitFor(() => expect(submitted).toEqual([{ kind: "acquire_edgar", identifiers: ["NVDA"], years: [2024] }]));
  await waitFor(() => expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled());
  sources.find((row) => row.issuer === "NVDA" && row.fiscal_year === 2024)!.on_disk = true;
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() => expect(screen.getByRole("button", { name: /^NVDA FY2024/ })).toHaveAccessibleName("NVDA FY2024 · On disk"));
  fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
  fireEvent.click(screen.getByRole("button", { name: "Parse & chunk selected sources" }));
  await waitFor(() => expect(submitted.slice(1)).toEqual([
    { kind: "ingest_selected", identifiers: ["AMD"], years: [2023], document_ids: ["AMD-2023"] },
    { kind: "ingest_selected", identifiers: ["NVDA"], years: [2024], document_ids: ["NVDA-2024"] },
  ]));
  if (failIndex) expect(await screen.findByText(/Indexing stopped after 1 queued jobs/)).toBeInTheDocument();
  cleanup(); vi.unstubAllGlobals();
});


describe("connection readiness presentation", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/admin/evaluations/preparation")) return jsonResponse({ suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] });
      if (url.endsWith("/admin/evaluations/suites")) return jsonResponse(CANNED_SUITES);
      if (url.endsWith("/admin/corpus")) return jsonResponse({
        ...CANNED_CORPUS,
        status: READY_RUNTIME.corpus,
        acquisition_draft: { identifiers: ["NVDA"], years: [2024], pairs: [{ registry: "sec", issuer: "NVDA", year: 2024 }], revision: "one-filing" },
        sources: [{ manifest: "manifest.json", document_id: "NVDA-FY2024", filing_id: "NVDA-FY2024", registry: "sec", issuer: "NVDA", name: "NVIDIA", fiscal_year: 2024, ready: true, can_redownload: false, on_disk: true }],
      });
      if (url.endsWith("/documents/facets")) return jsonResponse(EMPTY_DOCUMENT_FACETS_FIXTURE);
      if (url.includes("/documents?")) return jsonResponse({ documents: [], total: 0, next_cursor: null });
      if (url.endsWith("/admin/evaluations/runs")) return jsonResponse({ jobs: [] });
      if (url.endsWith("/admin/snapshots")) return jsonResponse([]);
      return jsonResponse({});
    }));
  });

  it("does not expose ready stages or invent an environment while the initial connection is checking", async () => {
    const { container } = render(<Harness live healthKind="checking" />);
    await screen.findByRole("button", { name: "NVDA FY2024 · On disk" });
    expect(screen.queryByText("hybrid ready")).toBeNull();
    expect(screen.queryByText("Corpus ready")).toBeNull();
    expect(container.querySelectorAll(".pipeline-node.done")).toHaveLength(0);
    expect(container.querySelectorAll(".page-badges .mode-badge")).toHaveLength(1);
    expect(screen.queryByText("Checking mode…")).toBeNull();
    expect(screen.queryByText("Runtime connected")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
    expect(screen.getByRole("button", { name: "Parse & chunk selected sources" })).toBeDisabled();
  });

  it("neutralizes retained ready data and actions during waiting or API loss without losing the known environment", async () => {
    const readiness = { ...READY_RUNTIME, environment: "dev" as const };
    const { rerender, container } = render(<Harness live readiness={readiness} />);
    await screen.findByText("Corpus ready");
    expect(screen.getByText("hybrid ready")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
    expect(screen.getByRole("button", { name: "Parse & chunk selected sources" })).toBeEnabled();
    rerender(<Harness live readiness={readiness} connectionPending />);
    expect(container.querySelectorAll(".pipeline-node.done, .pipeline-node.action, .pipeline-node.running, .pipeline-node.queued")).toHaveLength(0);
    expect(screen.queryByText("hybrid ready")).toBeNull();
    expect(screen.queryByText("Corpus ready")).toBeNull();
    expect(screen.queryByText("Runtime connected")).toBeNull();
    expect(container.querySelector(".page-badges")).toHaveTextContent("DEV");
    expect(screen.getByRole("button", { name: "Parse & chunk selected sources" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Select Evaluate" }));
    expect(screen.getByText("Checking corpus…")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Run quick evaluation" })).toBeNull();
    rerender(<Harness live readiness={readiness} healthKind="api_down" connectionPending />);
    expect(screen.getAllByText("API unavailable").length).toBeGreaterThan(0);
    expect(screen.queryByText("hybrid ready")).toBeNull();
    expect(screen.queryByText("Database connected")).toBeNull();
    rerender(<Harness live readiness={readiness} healthKind="healthy" connectionPending={false} />);
    expect(screen.getByText("hybrid ready")).toBeVisible();
    expect(screen.getByText("Corpus ready")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
    expect(screen.getByRole("button", { name: "Parse & chunk selected sources" })).toBeEnabled();
  });
});


it("queues a staged recoverable source and enables parsing after the verified refresh", async () => {
  const submitted: { kind: string; identifiers: string[]; years: number[] }[] = [];
  let recovered = false;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/admin/evaluations/preparation")) return jsonResponse({ suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] });
    if (url.endsWith("/admin/evaluations/suites")) return jsonResponse(CANNED_SUITES);
    if (url.endsWith("/admin/corpus/jobs") && init?.method === "POST") {
      submitted.push(JSON.parse(String(init.body)));
      recovered = true;
      return jsonResponse({ job_id: "reacquisition", status: "queued" });
    }
    if (url.endsWith("/admin/corpus")) return jsonResponse({
      mode: "live", ...CANNED_CORPUS,
      status: { ...CANNED_CORPUS.status, database_connected: true, schema_status: "compatible", writable: true },
      acquisition_draft: { identifiers: ["AMD"], years: [2023], pairs: [{ registry: "sec", issuer: "AMD", year: 2023 }], revision: "repair-source" },
      sources: [
        { manifest: "manifest.json", document_id: "AMD-FY2023", filing_id: "AMD-FY2023", registry: "sec", issuer: "AMD", name: "AMD", fiscal_year: 2023, on_disk: true, ready: true, can_redownload: false },
        { manifest: "manifest.json", document_id: "NVDA-FY2024", filing_id: "NVDA-FY2024", registry: "sec", issuer: "NVDA", name: "NVIDIA", fiscal_year: 2024, on_disk: true, ready: recovered, can_redownload: !recovered, blocker: recovered ? null : "Download it again in Filings" },
      ],
    });
    if (url.endsWith("/documents/facets")) return jsonResponse(EMPTY_DOCUMENT_FACETS_FIXTURE);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<Harness live />);
  fireEvent.click(screen.getByRole("button", { name: "Select Filings" }));
  await screen.findByRole("button", { name: "NVDA FY2024 · Source blocked" });
  const company = screen.getByLabelText("Search/add company or year");
  fireEvent.change(company, { target: { value: "NVDA" } });
  fireEvent.keyDown(company, { key: "Enter" });
  const year = screen.queryByRole("button", { name: "FY2024" });
  if (year) fireEvent.click(year);
  fireEvent.click(screen.getByRole("button", { name: "Sync selection" }));
  await waitFor(() => expect(submitted).toHaveLength(1));
  expect(submitted[0]).toMatchObject({ kind: "acquire_edgar", identifiers: ["NVDA"], years: [2024] });
  fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
  expect(screen.getByRole("button", { name: "Parse & chunk selected sources" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Parse & chunk selected sources" })).toBeEnabled());
  expect(screen.getByRole("button", { name: "NVDA FY2024 · On disk" })).toHaveAttribute("aria-pressed", "true");
});

/** Serve lifecycle requests while retaining the server snapshot until a terminal job refresh. */
function stubSourceLifecycle(sources: Array<Record<string, unknown>>, submitted: Array<Record<string, unknown>>, previews: Array<Record<string, unknown>>) {
  const pairs = [{ registry: "sec", issuer: "NVDA", year: 2024 }, { registry: "dart", issuer: "005930", year: 2023 }];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/admin/evaluations/preparation")) return jsonResponse({ suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] });
    if (url.endsWith("/admin/evaluations/suites")) return jsonResponse(CANNED_SUITES);
    if (url.endsWith("/admin/corpus/sources/deletion-preview")) {
      previews.push(JSON.parse(String(init?.body)));
      return jsonResponse({ token: "exact-source-token", expires_at: Date.now() / 1000 + 300, retained_inputs: 1, retained_derived: true,
        documents: sources.filter((row) => row.on_disk).map((row) => ({ document_id: row.document_id, registry: row.registry, issuer: row.issuer, fiscal_year: row.fiscal_year, filing_id: row.filing_id })),
        files: [{ path: "data/corpus/sec/filing-a.html", byte_length: 10, retained: false }],
      });
    }
    if (url.endsWith("/admin/corpus/jobs") && init?.method === "POST") { submitted.push(JSON.parse(String(init.body))); return jsonResponse({ job_id: "source-job", status: "queued" }); }
    if (url.endsWith("/admin/corpus")) return jsonResponse({ mode: "live", ...CANNED_CORPUS, status: READY_RUNTIME.corpus, sources, acquisition_draft: { revision: "source-lifecycle", identifiers: ["NVDA", "005930"], years: [2023, 2024], pairs } });
    if (url.endsWith("/documents/facets")) return jsonResponse(EMPTY_DOCUMENT_FACETS_FIXTURE);
    if (url.includes("/documents?")) return jsonResponse({ documents: [], total: 0, next_cursor: null });
    if (url.endsWith("/admin/evaluations/runs")) return jsonResponse({ jobs: [] });
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Keep two SEC filings in one year separate from the DART acquisition batch. */
function lifecycleSources() {
  return [
    { registry: "sec", issuer: "NVDA", fiscal_year: 2024, document_id: "sec-filing-a", filing_id: "accession-a", manifest: "manifest.json", ready: true, can_redownload: false, on_disk: true },
    { registry: "sec", issuer: "NVDA", fiscal_year: 2024, document_id: "sec-filing-b", filing_id: "accession-b", manifest: "manifest.json", ready: true, can_redownload: false, on_disk: true },
    { registry: "dart", issuer: "005930", fiscal_year: 2023, document_id: "dart-filing-c", filing_id: "receipt-c", manifest: "manifest.json", ready: true, can_redownload: false, on_disk: true },
  ];
}

it("submits each exact filing identity while preserving the existing registry/year batches", async () => {
  const sources = lifecycleSources(); const submitted: Record<string, unknown>[] = [];
  stubSourceLifecycle([...sources, { ...sources[0], manifest: "duplicate.json" }], submitted, []);
  render(<Harness live readiness={READY_RUNTIME} />);
  fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Parse & chunk selected sources" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Parse & chunk selected sources" }));
  await waitFor(() => expect(submitted).toEqual([
    { kind: "ingest_selected", identifiers: ["NVDA"], years: [2024], document_ids: ["sec-filing-a", "sec-filing-b"] },
    { kind: "ingest_selected", identifiers: ["005930"], years: [2023], document_ids: ["dart-filing-c"] },
  ]));
});

it("queues reacquisition of changed bytes and blocks the whole intended parsing scope", async () => {
  const sources = lifecycleSources(); sources[0].ready = false;
  const submitted: Record<string, unknown>[] = [];
  stubSourceLifecycle(sources.map((row) => ({ ...row, can_redownload: !row.ready, blocker: row.ready ? null : "Source bytes changed" })), submitted, []);
  render(<Harness live readiness={READY_RUNTIME} />);
  fireEvent.click(screen.getByRole("button", { name: "Select Parse & chunk" }));
  await screen.findByText("accession-a: Source bytes changed");
  expect(screen.getByRole("button", { name: /^NVDA FY/ })).toHaveClass("source-blocked");
  fireEvent.click(screen.getByRole("button", { name: "Parse & chunk selected sources" }));
  expect(submitted).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "Change selection in Filings" }));
  expect(screen.getByRole("button", { name: /^NVDA FY2024/ })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "Sync selection" }));
  await waitFor(() => expect(submitted).toEqual([{ kind: "acquire_edgar", identifiers: ["NVDA"], years: [2024] }]));
});

it("separates deselection and cancellation from confirmed deletion without premature inventory changes", async () => {
  const sources = lifecycleSources(); sources[2].on_disk = false; sources[2].ready = false; sources[2].can_redownload = true;
  const submitted: Record<string, unknown>[] = []; const previews: Record<string, unknown>[] = []; const refresh = vi.fn();
  const fetchMock = stubSourceLifecycle(sources, submitted, previews);
  render(<Harness live readiness={READY_RUNTIME} onRefreshJobs={refresh} />);
  fireEvent.click(screen.getByRole("button", { name: "Select Filings" }));
  const trigger = await screen.findByRole("button", { name: "Delete all downloaded originals" });
  await waitFor(() => expect(trigger).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
  expect(trigger).toBeEnabled(); expect(previews).toEqual([]); expect(submitted).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "NVDA FY2024 · On disk" }));
  fireEvent.click(trigger);
  await screen.findByRole("button", { name: "Confirm deletion of originals" });
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
  expect(submitted).toEqual([]);
  expect(screen.getByRole("button", { name: "NVDA FY2024 · On disk" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(trigger);
  fireEvent.click(await screen.findByRole("button", { name: "Confirm deletion of originals" }));
  await screen.findByText("Source deletion queued. Files are not deleted yet; check Jobs for the result.");
  expect(previews).toEqual([{ document_ids: sources.map((source) => source.document_id) }, { document_ids: sources.map((source) => source.document_id) }]);
  expect(submitted).toEqual([{ kind: "delete_sources", identifiers: [], years: [], deletion_token: "exact-source-token", confirm_delete: true }]);
  expect(refresh).toHaveBeenCalledOnce();
  expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/admin/corpus"))).toHaveLength(1);
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close" }));
  expect(screen.getByRole("button", { name: "NVDA FY2024 · On disk" })).toHaveAttribute("aria-pressed", "true");
});

it.each(["queued", "running"] as const)("locks deletion while a corpus job is %s", async (status) => {
  const submitted: Record<string, unknown>[] = []; const previews: Record<string, unknown>[] = [];
  stubSourceLifecycle(lifecycleSources(), submitted, previews);
  const job: OperatorJob = { job_id: "other-corpus-job", domain: "corpus", kind: "backfill_embeddings", request: {}, status, stage: "embed", current: 1, total: 10, detail_current: null, detail_total: null, message: "Embedding", error_code: null, result_refs: {}, queue_position: null, can_cancel: true, can_retry: false, created_at: "2026-09-08T12:00:00Z", started_at: null, finished_at: null, updated_at: "2026-09-08T12:00:00Z" };
  render(<Harness live readiness={READY_RUNTIME} jobBoard={{ jobs: [job], active_count: 1, queued_count: 0 }} />);
  fireEvent.click(screen.getByRole("button", { name: "Select Filings" }));
  await screen.findByRole("button", { name: "NVDA FY2024 · On disk" });
  fireEvent.click(screen.getByRole("button", { name: "Delete all downloaded originals" }));
  expect(screen.getByRole("button", { name: "Delete all downloaded originals" })).toBeDisabled();
  expect(previews).toEqual([]); expect(submitted).toEqual([]);
});

it("opens the golden-set manager from pipeline evaluation setup", async () => {
  const onNavigate = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/admin/evaluations/suites")) return jsonResponse(CANNED_SUITES);
    if (url.endsWith("/admin/evaluations/preparation")) return jsonResponse({ suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] });
    if (url.endsWith("/admin/corpus")) return jsonResponse({ mode: "live", ...CANNED_CORPUS, status: READY_RUNTIME.corpus });
    if (url.endsWith("/documents/facets")) return jsonResponse(EMPTY_DOCUMENT_FACETS_FIXTURE);
    if (url.endsWith("/admin/evaluations/runs")) return jsonResponse({ jobs: [] });
    return jsonResponse([]);
  }));
  render(<Harness live readiness={READY_RUNTIME} onNavigate={onNavigate} />);
  fireEvent.click(screen.getByRole("button", { name: "Select Evaluate" }));
  fireEvent.click(await screen.findByRole("button", { name: "Manage golden sets" }));
  expect(onNavigate).toHaveBeenCalledExactlyOnceWith({ view: "measure", tab: "golden" });
});
