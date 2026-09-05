import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CANNED_JOB, CANNED_SUITES } from "@/lib/canned";
import type { Readiness } from "@/lib/types";
import { DEFAULT_PROFILE } from "@/lib/types";
import { BuildWorkspace, type BuildTab, type BuildWorkspaceProps } from "./build-workspace";

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

function jsonResponse(payload: unknown) {
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
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("keeps real corpus operations disabled in the public read-only mode", () => {
    render(<Harness live={false} />);

    expect(screen.getByText("Read-only portfolio")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download missing filings" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Ingest all manifests" })).toBeDisabled();
  });

  it("shows active progress on the pipeline and opens the Job Center from it", () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      let payload: unknown = {};
      if (url.endsWith("/admin/evaluations/runs")) payload = { jobs: [] };
      else if (url.endsWith("/admin/corpus")) payload = { status: {}, documents: [] };
      else if (url.endsWith("/admin/documents/facets")) payload = EMPTY_DOCUMENT_FACETS_FIXTURE;
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
    expect(screen.getAllByText("Embedded 50").length).toBeGreaterThan(0);
  });

  it("filters, groups, and renders structured document index detail", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      let payload: unknown = {};
      if (url.endsWith("/admin/evaluations/runs")) payload = { jobs: [] };
      else if (url.endsWith("/admin/corpus")) payload = { status: {}, documents: [] };
      else if (url.endsWith("/admin/documents/facets")) payload = {
        registries: [{ value: "sec", count: 1 }],
        issuers: [{ value: "ACME", count: 1 }],
        years: [{ value: "2024", count: 1 }],
        languages: [{ value: "en", count: 1 }],
        forms: [{ value: "10-K", count: 1 }],
        parse_statuses: [{ value: "parsed", count: 1 }],
        embedding_statuses: [{ value: "complete", count: 1 }],
        snapshots: [{ value: "3", count: 1, label: "Baseline · ready" }],
      };
      else if (url.includes("/admin/documents?")) payload = {
        documents: [{
          doc_id: "ACME-FY2024", registry: "sec", language: "en", issuer: "ACME",
          issuer_id: "123", fiscal_year: 2024, form: "10-K", filing_date: "2025-02-01",
          report_period: "2024-12-31", filing_id: "filing-1", source_url: "https://example.invalid/acme",
          parse_status: "parsed", source_length: 1000, source_sha256: "d".repeat(64),
          chunk_count: 2, embedded_chunks: 2, text_chunks: 1, table_chunks: 1,
          embedding_status: "complete", snapshot_count: 1,
        }],
        total: 1,
        next_cursor: null,
      };
      else if (url.endsWith("/admin/documents/ACME-FY2024")) payload = {
        document: {
          doc_id: "ACME-FY2024", registry: "sec", language: "en", issuer: "ACME",
          issuer_id: "123", fiscal_year: 2024, form: "10-K", parse_status: "parsed",
          filing_date: "2025-02-01", report_period: "2024-12-31", filing_id: "filing-1",
          source_url: "https://example.invalid/acme", source_length: 1000,
          source_sha256: "d".repeat(64), chunk_count: 2,
        },
        chunks: [{ chunk_id: 7, ordinal: 0, citation: "ACME FY2024 · Item 7", span: "chars 0-20", source_sha256: "d".repeat(64), body: "Revenue grew." }],
        text_chunks: 1,
        table_chunks: 1,
        embedded_chunks: 2,
        item_counts: [{ item: "7", count: 2 }],
        embedding_identities: [{ provider: "deterministic", model: "token-hash-384", dimensions: 384, count: 2 }],
        snapshot_memberships: [{ snapshot_id: 3, label: "Baseline", status: "ready", public: true, created_at: "2026-09-01T12:00:00Z" }],
      };
      else if (url.endsWith("/admin/snapshots")) payload = [];
      return jsonResponse(payload);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Harness live />);

    fireEvent.click(screen.getByRole("button", { name: "Documents" }));
    expect(await screen.findByRole("combobox", { name: "Filter company" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Filter company" }), { target: { value: "ACME" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Group documents" }), { target: { value: "issuer" } });
    await waitFor(() => expect(fetchMock.mock.calls.some(([value]) => String(value).includes("issuer=ACME"))).toBe(true));
    expect(await screen.findByText("Company · ACME")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "ACME-FY2024" }));

    expect(await screen.findByRole("heading", { name: "Filing identity" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Index revisions & snapshot membership" })).toBeInTheDocument();
    expect(screen.getByText("Revision #3 · Baseline")).toBeInTheDocument();
    expect(screen.getByText("ACME FY2024 · Item 7")).toBeInTheDocument();
  });

  it("orders build steps from the administrator snapshot", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
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
        manifests: [
          { name: "manifest.json", registry: "sec", documents: 21, valid: true, sources_present: 21 },
          { name: "dart-manifest.json", registry: "dart", documents: 9, valid: true, sources_present: 9 },
        ],
        documents: [],
      };
      else if (url.endsWith("/admin/documents/facets")) payload = {
        ...EMPTY_DOCUMENT_FACETS_FIXTURE,
        registries: [{ value: "sec", count: 20 }, { value: "dart", count: 9 }],
      };
      else if (url.endsWith("/admin/snapshots")) payload = [];
      return jsonResponse(payload);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Harness live readiness={READY_RUNTIME} />);

    expect(await screen.findByText("1 listed filing not ingested yet (SEC)")).toBeInTheDocument();
    expect(screen.getByText("Corpus ready · evaluation recorded")).toBeInTheDocument();
    expect(screen.getByText("30 / 30 filings on disk")).toBeInTheDocument();
    const ingestButtons = screen.getAllByRole("button", { name: "Ingest all manifests" });
    for (const button of ingestButtons) expect(button).toBeEnabled();
    fireEvent.click(ingestButtons[0]);

    await waitFor(() => {
      const queued = fetchMock.mock.calls.filter(([value, init]) => String(value).endsWith("/admin/corpus/jobs") && (init as RequestInit | undefined)?.method === "POST");
      expect(queued).toHaveLength(2);
    });
    const bodies = fetchMock.mock.calls
      .filter(([value, init]) => String(value).endsWith("/admin/corpus/jobs") && (init as RequestInit | undefined)?.method === "POST")
      .map(([, init]) => JSON.parse(String((init as RequestInit).body)) as Record<string, unknown>);
    expect(bodies).toEqual([
      { kind: "ingest_manifest", manifest: "manifest.json" },
      { kind: "ingest_manifest", manifest: "dart-manifest.json" },
    ]);
  });

  it("never calls the administrator API in the public build", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      const payload: unknown = url.endsWith("/snapshots") ? { snapshots: [] } : {};
      return jsonResponse(payload);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Harness live={false} />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchMock.mock.calls.every(([value]) => !String(value).includes("/admin/"))).toBe(true);
    expect(screen.getAllByText("Portfolio fixture").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Compare published snapshots" })).toBeInTheDocument();
    expect(screen.getAllByText("Runs on the local operator build.").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Documents" }));
    expect(screen.getByText("NVDA-FY2024")).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchMock.mock.calls.every(([value]) => !String(value).includes("/admin/"))).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Jobs" }));
    expect(screen.getByText("Jobs run on the local operator build.")).toBeInTheDocument();
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

    expect(screen.getByText("No answer model")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Re-check" }));
    expect(onRecheck).toHaveBeenCalledTimes(1);
  });

  it("routes cross-workspace links through onNavigate", () => {
    const onNavigate = vi.fn();
    render(<Harness live={false} onNavigate={onNavigate} />);

    fireEvent.click(screen.getByRole("button", { name: "Compare published snapshots" }));
    expect(onNavigate).toHaveBeenCalledWith({ view: "measure", tab: "snapshots" });
    // The next-step callout and the Ask stage card both offer the same action.
    fireEvent.click(screen.getAllByRole("button", { name: "Ask a question" })[0]);
    expect(onNavigate).toHaveBeenCalledWith({ view: "review" });
  });

  it("queues a quick evaluation with a non-empty chunk target list", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      let payload: unknown = {};
      if (url.endsWith("/admin/evaluations/runs") && init?.method === "POST") payload = { ...CANNED_JOB, job_id: "eval-new", status: "queued", result_id: null, result_ids: [] };
      else if (url.endsWith("/admin/evaluations/runs")) payload = { jobs: [] };
      else if (url.endsWith("/admin/corpus")) payload = {
        status: {
          database_connected: true, schema_status: "compatible", schema_message: "ok",
          documents: 30, chunks: 22367, embedded_chunks: 22367, pending_embeddings: 0,
          bm25_ready: true, writable: true, provider: "deterministic",
        },
        manifests: [{ name: "manifest.json", registry: "sec", documents: 21, valid: true, sources_present: 21 }],
        documents: [],
      };
      else if (url.endsWith("/admin/documents/facets")) payload = { ...EMPTY_DOCUMENT_FACETS_FIXTURE, registries: [{ value: "sec", count: 21 }, { value: "dart", count: 9 }] };
      else if (url.includes("/admin/golden/")) payload = [];
      else if (url.endsWith("/admin/snapshots")) payload = [];
      return jsonResponse(payload);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Harness live readiness={READY_RUNTIME} />);

    // The next-step callout and the Evaluate card offer the same action.
    const buttons = await screen.findAllByRole("button", { name: "Run quick evaluation" });
    fireEvent.click(buttons[0]);

    await waitFor(() => {
      const posted = fetchMock.mock.calls.find(([value, init]) => String(value).endsWith("/admin/evaluations/runs") && (init as RequestInit | undefined)?.method === "POST");
      expect(posted).toBeDefined();
      const body = JSON.parse(String((posted?.[1] as RequestInit).body)) as Record<string, unknown>;
      expect(body.mode).toBe("quick");
      expect(body.golden_revision_id).toBeNull();
      expect(Array.isArray(body.target_text_chars) && (body.target_text_chars as number[]).length > 0).toBe(true);
    });
  });
});
