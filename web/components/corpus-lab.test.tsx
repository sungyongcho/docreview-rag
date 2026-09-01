import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CANNED_SUITES } from "@/lib/canned";
import { DEFAULT_PROFILE } from "@/lib/types";
import { CorpusLab, deploymentLabel } from "./corpus-lab";

const EMPTY_USAGE_FIXTURE = {
  runs: 0,
  requests: 0,
  input_tokens: 0,
  cached_input_tokens: 0,
  cache_write_input_tokens: 0,
  output_tokens: 0,
  reasoning_tokens: 0,
  estimated_cost_usd: "0",
  latest_run_at: null,
  models: [],
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

describe("Corpus Lab", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("keeps real corpus operations disabled in the public read-only mode", () => {
    render(
      <CorpusLab
        live={false}
        profile={DEFAULT_PROFILE}
        onProfileChange={vi.fn()}
        onApplyProfile={vi.fn()}
        onApplySnapshot={vi.fn()}
        jobBoard={{ jobs: [], active_count: 0, queued_count: 0 }}
        jobsLoading={false}
        onRetryJob={vi.fn()}
        onCancelJob={vi.fn()}
        onRefreshJobs={vi.fn()}
      />,
    );

    expect(screen.getByText("Read-only portfolio")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Acquire missing filings" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Ingest manifest" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Usage" })).not.toBeInTheDocument();
  });

  it("shows locally persisted usage only in live operator mode", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      let payload: unknown = {};
      if (url.endsWith("/admin/evaluations/suites")) payload = CANNED_SUITES;
      else if (url.endsWith("/admin/evaluations/runs")) payload = { jobs: [] };
      else if (url.endsWith("/admin/corpus/jobs")) payload = { history: [] };
      else if (url.endsWith("/admin/corpus")) payload = { status: {}, documents: [] };
      else if (url.endsWith("/admin/usage")) payload = {
        runs: 2, requests: 3, input_tokens: 100, cached_input_tokens: 20,
        cache_write_input_tokens: 10, output_tokens: 30, reasoning_tokens: 5,
        estimated_cost_usd: "0.01", latest_run_at: null,
        models: [{ model_name: "gpt-5.6-terra", requests: 3, input_tokens: 100,
          cached_input_tokens: 20, cache_write_input_tokens: 10, output_tokens: 30,
          reasoning_tokens: 5, estimated_cost_usd: "0.01" }],
      };
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }));
    render(
      <CorpusLab
        live
        profile={DEFAULT_PROFILE}
        onProfileChange={vi.fn()}
        onApplyProfile={vi.fn()}
        onApplySnapshot={vi.fn()}
        jobBoard={{ jobs: [], active_count: 0, queued_count: 0 }}
        jobsLoading={false}
        onRetryJob={vi.fn()}
        onCancelJob={vi.fn()}
        onRefreshJobs={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Usage" }));

    await waitFor(() => expect(screen.getByText("gpt-5.6-terra")).toBeInTheDocument());
    expect(screen.getAllByText("$0.01")).toHaveLength(2);
  });

  it("shows active progress and queue position in Overview and Job Center", () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      let payload: unknown = {};
      if (url.endsWith("/admin/evaluations/suites")) payload = CANNED_SUITES;
      else if (url.endsWith("/admin/evaluations/runs")) payload = { jobs: [] };
      else if (url.endsWith("/admin/corpus")) payload = { status: {}, documents: [] };
      else if (url.includes("/admin/documents?")) payload = { documents: [], total: 0, next_cursor: null };
      else if (url.endsWith("/admin/snapshots")) payload = [];
      else if (url.includes("/admin/golden/")) payload = [];
      else if (url.endsWith("/admin/usage")) payload = { ...EMPTY_USAGE_FIXTURE };
      return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
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
    render(
      <CorpusLab
        live
        profile={DEFAULT_PROFILE}
        onProfileChange={vi.fn()}
        onApplyProfile={vi.fn()}
        onApplySnapshot={vi.fn()}
        jobBoard={{ jobs: [active], active_count: 1, queued_count: 0 }}
        jobsLoading={false}
        onRetryJob={vi.fn()}
        onCancelJob={vi.fn()}
        onRefreshJobs={vi.fn()}
      />,
    );

    expect(screen.getByText("50 / 100 · 50%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View all jobs" }));
    expect(screen.getByRole("heading", { name: "Job Center" })).toBeInTheDocument();
    expect(screen.getAllByText("Embedded 50").length).toBeGreaterThan(0);
  });

  it("filters, groups, and renders structured document index detail", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      let payload: unknown = {};
      if (url.endsWith("/admin/evaluations/suites")) payload = CANNED_SUITES;
      else if (url.endsWith("/admin/evaluations/runs")) payload = { jobs: [] };
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
      else if (url.includes("/admin/golden/")) payload = [];
      else if (url.endsWith("/admin/usage")) payload = { ...EMPTY_USAGE_FIXTURE };
      return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <CorpusLab
        live
        profile={DEFAULT_PROFILE}
        onProfileChange={vi.fn()}
        onApplyProfile={vi.fn()}
        onApplySnapshot={vi.fn()}
        jobBoard={{ jobs: [], active_count: 0, queued_count: 0 }}
        jobsLoading={false}
        onRetryJob={vi.fn()}
        onCancelJob={vi.fn()}
        onRefreshJobs={vi.fn()}
      />,
    );

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

  it("shows canonical golden questions before a mutable draft exists", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      let payload: unknown = {};
      if (url.endsWith("/admin/evaluations/suites")) payload = CANNED_SUITES;
      else if (url.endsWith("/admin/evaluations/runs")) payload = { jobs: [] };
      else if (url.endsWith("/admin/corpus")) payload = { status: {}, documents: [] };
      else if (url.includes("/admin/documents?")) payload = { documents: [], total: 0, next_cursor: null };
      else if (url.endsWith("/admin/documents/facets")) payload = EMPTY_DOCUMENT_FACETS_FIXTURE;
      else if (url.endsWith("/admin/golden/sec-en/revisions")) payload = [];
      else if (url.endsWith("/admin/golden/sec-en/canonical")) payload = {
        suite_id: "sec-en",
        filename: "retrieval.json",
        sha256: "a".repeat(64),
        payload: [{
          id: "test-01", question: "Which policy is absent?", category: "absent",
          facet: "policy", tags: ["negative"], answers: [], expected_label: "NOT_IN_DOCS",
          reference_answer: "NOT_IN_DOCS", note: "Deliberate negative.",
          curation_status: "agent-curated", approval_status: "pending-author-approval",
          human_verified: false,
        }],
      };
      else if (url.endsWith("/admin/snapshots")) payload = [];
      else if (url.endsWith("/admin/usage")) payload = { ...EMPTY_USAGE_FIXTURE };
      return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
    }));
    render(
      <CorpusLab
        live
        profile={DEFAULT_PROFILE}
        onProfileChange={vi.fn()}
        onApplyProfile={vi.fn()}
        onApplySnapshot={vi.fn()}
        jobBoard={{ jobs: [], active_count: 0, queued_count: 0 }}
        jobsLoading={false}
        onRetryJob={vi.fn()}
        onCancelJob={vi.fn()}
        onRefreshJobs={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Golden Tests" }));
    expect(await screen.findByText("Which policy is absent?")).toBeInTheDocument();
    expect(screen.getByText("retrieval.json")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "test-01" }));
    expect(screen.getByText("Read-only source")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save case" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Create draft" })).toBeEnabled();
  });
});
  it("derives a text-only deployment label from the current host", () => {
    expect(deploymentLabel("localhost")).toBe("DEV");
    expect(deploymentLabel("127.0.0.1")).toBe("DEV");
    expect(deploymentLabel("review.example.com")).toBe("PROD");
  });
