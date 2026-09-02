import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ONBOARDING_KEY, saveConversations } from "@/lib/storage";
import type { Readiness } from "@/lib/types";
import { TOUR_TARGETS } from "./onboarding";
import { ServiceShell, terminalAnswer } from "./service-shell";

const OPERATOR_URL = "http://operator.test";

const READY_RUNTIME: Readiness = {
  status: "ready",
  mode: "runtime",
  admin_mode: "readonly",
  policy_revision: "test",
  models: {},
  review_enabled: true,
  active_review_model: "gpt-5.6-terra",
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
    writable: false,
  },
};

const EMPTY_CORPUS: Readiness["corpus"] = {
  availability: "ready", database_connected: true, schema_status: "compatible", schema_message: "ok",
  documents: 0, chunks: 0, embedded_chunks: 0, pending_embeddings: 0, bm25_ready: false, writable: true,
};

function liveReadiness(corpus: Readiness["corpus"]): Readiness {
  return { ...READY_RUNTIME, status: corpus.documents ? "ready" : "degraded", admin_mode: "live", corpus };
}

/** Live-build API stub: runtime endpoints plus empty `/admin/*` and operator lists; `ready` lets a test hold back `/ready`. */
function stubLiveApi(corpus: Readiness["corpus"], ready: () => Promise<Readiness> = async () => liveReadiness(corpus)) {
  vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live");
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    let payload: unknown = {};
    if (url.endsWith("/health")) payload = { status: "ok" };
    else if (url.endsWith("/ready")) payload = await ready();
    else if (url.endsWith("/limits")) payload = { daily_cost_reset_at_utc: "2026-09-02T00:00:00Z" };
    else if (url.endsWith("/snapshots")) payload = url.includes("/admin/") ? [] : { snapshots: [] };
    else if (url.endsWith("/admin/jobs")) payload = { jobs: [], active_count: 0, queued_count: 0 };
    else if (url.endsWith("/admin/evaluations/runs")) payload = { jobs: [] };
    else if (url.endsWith("/admin/corpus")) payload = { status: { ...corpus, provider: "deterministic" }, manifests: [], documents: [] };
    else if (url.endsWith("/admin/documents/facets")) payload = {};
    else if (url.startsWith(OPERATOR_URL)) payload = [];
    return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** One answered review in storage, so the evidence toggle exists and the welcome suggestions do not. */
function seedAnsweredConversation() {
  saveConversations([{
    id: "seeded", title: "NVIDIA data center", createdAt: "2026-09-01T00:00:00Z", updatedAt: "2026-09-01T00:00:00Z", profile: null,
    messages: [
      { id: "q", role: "user", text: "What drove data center revenue?" },
      {
        id: "a", role: "assistant", text: "Data center revenue grew on Hopper demand.", evidenceLabel: "Cited evidence", citations: 1,
        evidence: [{
          chunk_id: 1, doc_id: "NVDA-FY2024-10K", item: "Item 7", kind: "text", citation: "[NVDA FY2024 §7 c1]", start_char: 0, end_char: 120,
          source_sha256: "abc", body: "Data Center revenue was up 217%.", context_header: "Item 7", score: 0.9,
        }],
      },
    ],
  }]);
}

/** Passive effects such as first-run routing run after the DOM a `findBy*` query resolved on; flush them before asserting the view. */
async function flushEffects() {
  await act(async () => undefined);
}

/** Records which tour targets the shell renders right now. */
function noteTargets(seen: Set<string>) {
  for (const name of TOUR_TARGETS) if (document.querySelector(`[data-tour="${name}"]`)) seen.add(name);
}

/** Public-build API stub: runtime endpoints plus the public `/snapshots` list; everything else is `{}`. */
function stubPublicApi() {
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    let payload: unknown = {};
    if (url.endsWith("/health")) payload = { status: "ok" };
    else if (url.endsWith("/ready")) payload = READY_RUNTIME;
    else if (url.endsWith("/capabilities")) payload = {
      can_edit_prompt_policy: false, can_edit_run_limits: false, can_edit_golden: false,
      can_build_snapshot: false, can_run_evaluation: false, can_change_custom_retrieval: false,
      can_query_snapshot: false, can_use_operations: false, can_compare_published_snapshots: true,
    };
    else if (url.endsWith("/limits")) payload = {
      per_minute: 5, per_day: 25, remaining_minute: 5, remaining_day: 25, max_input_tokens: 12000,
      max_output_tokens: 600, max_cost_usd: "0.04", daily_cost_usd: "1.00", remaining_daily_cost_usd: "1.00",
      retry_after_seconds: 0, minute_reset_seconds: 0, day_reset_seconds: 0,
      daily_cost_reset_at_utc: "2026-09-02T00:00:00Z", scope: "single_process",
    };
    else if (url.endsWith("/snapshots")) payload = { snapshots: [] };
    return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("service shell", () => {
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

  it("navigates between Build, Measure and System from the sidebar", async () => {
    const fetchMock = stubPublicApi();
    render(<ServiceShell />);
    await waitFor(() => expect(screen.getByRole("button", { name: "healthy" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Build" }));
    expect(screen.getByRole("heading", { name: "From filings to verified answers." })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Build" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Read-only portfolio")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Measure" }));
    expect(screen.getByRole("heading", { name: "Measure retrieval before trusting it." })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Playground" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "System" }));
    expect(screen.getByRole("heading", { name: "Runtime readiness" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "System status" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "Operations" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Usage" })).not.toBeInTheDocument();

    // The sidebar action comes first in DOM order; the untitled conversation row shares its name.
    fireEvent.click(screen.getAllByRole("button", { name: "New review" })[0]);
    expect(screen.getByPlaceholderText("Ask a question about the filing corpus")).toBeInTheDocument();

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchMock.mock.calls.every(([value]) => !String(value).includes("/admin/"))).toBe(true);
  });

  it("renders the review shell and opens documentation in a new window", async () => {
    render(<ServiceShell />);

    await waitFor(() =>
      expect(screen.getByPlaceholderText("Ask a question about the filing corpus")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Data & help" }));
    const documentation = screen.getByText("Documentation").closest("a");

    expect(screen.getByText("Review filings with verifiable evidence.")).toBeInTheDocument();
    expect(documentation).toHaveAttribute("target", "_blank");
    expect(documentation).toHaveAttribute("href", "/docreview-rag-agent/docs/");
  });

  it("shows the evidence-only banner and fallback when the answer model is off", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/review/stream")) {
        return new Response(
          JSON.stringify({ error: { code: "provider_unavailable", message: "Review engine 'openai' is not configured." } }),
          { status: 503, headers: { "content-type": "application/json" } },
        );
      }
      let payload: unknown = {};
      if (url.endsWith("/health")) payload = { status: "ok" };
      else if (url.endsWith("/ready")) payload = { ...READY_RUNTIME, review_enabled: false, active_review_model: null };
      else if (url.endsWith("/capabilities")) payload = { can_change_custom_retrieval: false, can_compare_published_snapshots: true };
      else if (url.endsWith("/limits")) payload = { daily_cost_reset_at_utc: "2026-09-02T00:00:00Z" };
      else if (url.endsWith("/snapshots")) payload = { snapshots: [] };
      else if (url.endsWith("/retrieve")) payload = {
        results: [],
        candidates: [
          { chunk_id: 1, doc_id: "NVDA-FY2025", item: "7", kind: "text", citation: "NVDA FY2025 Item 7", start_char: 0, end_char: 120, source_sha256: "a", body: "Data center revenue grew.", context_header: "Item 7", score: 0.9 },
          { chunk_id: 2, doc_id: "NVDA-FY2025", item: "7", kind: "table", citation: "NVDA FY2025 Item 7 table", start_char: 120, end_char: 240, source_sha256: "a", body: "Revenue by segment.", context_header: "Item 7", score: 0.8 },
        ],
        candidate_token: null,
        candidate_expires_at: 0,
        resolved_scope: null,
      };
      return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ServiceShell />);

    await waitFor(() => expect(screen.getByText(/Answer model is off — evidence only\./)).toBeInTheDocument());
    const textarea = screen.getByPlaceholderText("Ask a question about the filing corpus");
    fireEvent.change(textarea, { target: { value: "What drove NVIDIA data center revenue growth?" } });
    fireEvent.keyDown(textarea, { key: "Enter" });

    await waitFor(() => expect(screen.getByText(/See Build › step 6\./)).toBeInTheDocument());
    expect(screen.getByText("Answer not generated")).toBeInTheDocument();
    expect(screen.getByText("Retrieved candidates — answer not generated · 2")).toBeInTheDocument();
    expect(screen.getByText("table")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([value]) => String(value).endsWith("/retrieve"))).toBe(true);
    expect(fetchMock.mock.calls.every(([value]) => !String(value).includes("/admin/"))).toBe(true);
  });

  it("changes the corpus scope from the composer toolbar", async () => {
    stubPublicApi();
    render(<ServiceShell />);
    await waitFor(() => expect(screen.getByRole("button", { name: "healthy" })).toBeInTheDocument());

    const scope = screen.getByRole("group", { name: "Corpus scope" });
    expect(within(scope).getByRole("button", { name: "Auto" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(scope).getByRole("button", { name: "SEC" }));
    expect(within(scope).getByRole("button", { name: "SEC" })).toHaveAttribute("aria-pressed", "true");
    expect(within(scope).getByRole("button", { name: "Auto" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("Read-only corpus")).toBeInTheDocument();
  });

  it("shows invalidated provider authentication instead of an evidence fallback", () => {
    const answer = terminalAnswer({
      status: "error",
      report: null,
      failure: {
        code: "provider_failure",
        status: "provider_error",
        details: ["AuthenticationError: token_invalidated"],
      },
    });

    expect(answer).toBe(
      "OpenAI API authentication failed. Update the server-side API key and retry.",
    );
  });

  it("tour targets exist on the screens the tour opens", async () => {
    stubPublicApi();
    window.localStorage.removeItem(ONBOARDING_KEY);
    seedAnsweredConversation();
    render(<ServiceShell />);
    const seen = new Set<string>();

    expect(await screen.findByText("Step 1 of 7")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "From filings to verified answers." })).toBeInTheDocument();
    noteTargets(seen);

    fireEvent.click(screen.getByText("Next"));
    expect(screen.getByText("Step 2 of 7")).toBeInTheDocument();
    expect(document.querySelector(".tour-spotlight")).not.toBeNull();
    noteTargets(seen);
    fireEvent.click(screen.getByText("Next"));
    expect(screen.getByText("Step 3 of 7")).toBeInTheDocument();
    noteTargets(seen);

    fireEvent.click(screen.getByText("Next"));
    expect(screen.getByText("Step 4 of 7")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Ask a question about the filing corpus")).toBeInTheDocument();
    noteTargets(seen);
    // Back to a Build target that is absent at click time: the shell navigates first, then the spotlight lands on it.
    fireEvent.click(screen.getByText("Back"));
    expect(screen.getByText("Step 3 of 7")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "From filings to verified answers." })).toBeInTheDocument();
    expect(document.querySelector('[data-tour="next-step"]')).not.toBeNull();
    expect(document.querySelector(".tour-spotlight")).not.toBeNull();
    fireEvent.click(screen.getByText("Next"));
    fireEvent.click(screen.getByText("Next"));
    expect(screen.getByText("Step 5 of 7")).toBeInTheDocument();
    noteTargets(seen);
    fireEvent.click(screen.getByText("Next"));
    expect(screen.getByText("Step 6 of 7")).toBeInTheDocument();
    expect(document.querySelector(".tour-spotlight")).not.toBeNull();
    noteTargets(seen);
    fireEvent.click(screen.getByText("Next"));
    expect(screen.getByText("Step 7 of 7")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Measure retrieval before trusting it." })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Measure" })).toHaveAttribute("aria-pressed", "true");
    noteTargets(seen);

    // The answered review hides the welcome suggestions; the operator run below covers those and Operations.
    expect(TOUR_TARGETS.filter((name) => !seen.has(name))).toEqual(["evidence-fallback", "operations"]);

    fireEvent.click(screen.getByText("Finish"));
    expect(window.localStorage.getItem(ONBOARDING_KEY)).toBe("done");
    expect(screen.queryByText("Step 7 of 7")).toBeNull();
  });

  it("spotlights the Operations tab on the optional last step of the operator build", async () => {
    vi.stubEnv("NEXT_PUBLIC_OPERATOR_BASE_URL", OPERATOR_URL);
    vi.stubEnv("NEXT_PUBLIC_OPERATOR_TOKEN", "operator-token");
    stubLiveApi({ ...READY_RUNTIME.corpus, writable: true });
    window.localStorage.removeItem(ONBOARDING_KEY);
    render(<ServiceShell />);
    const seen = new Set<string>();

    expect(await screen.findByText("Step 1 of 8")).toBeInTheDocument();
    for (let step = 1; step <= 7; step += 1) {
      noteTargets(seen);
      fireEvent.click(screen.getByText("Next"));
    }
    expect(screen.getByText("Step 8 of 8")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Operations" })).toHaveAttribute("aria-pressed", "true");
    expect(document.querySelector('[data-tour="operations"]')).not.toBeNull();
    expect(document.querySelector(".tour-spotlight")).not.toBeNull();
    noteTargets(seen);
    // A fresh review has no answer yet, so only the evidence toggle is missing here.
    expect(TOUR_TARGETS.filter((name) => !seen.has(name))).toEqual(["evidence-toggle"]);

    fireEvent.click(screen.getByText("Finish"));
    expect(window.localStorage.getItem(ONBOARDING_KEY)).toBe("done");
  });

  it("starts on Build when the live corpus is empty", async () => {
    stubLiveApi(EMPTY_CORPUS);
    render(<ServiceShell />);

    expect(await screen.findByRole("heading", { name: "From filings to verified answers." })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Build/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Local operator")).toBeInTheDocument();
  });

  it("stays on Review when the live corpus already has filings", async () => {
    stubLiveApi({ ...READY_RUNTIME.corpus, writable: true });
    render(<ServiceShell />);

    expect(await screen.findByRole("button", { name: "29 filings · hybrid ready" })).toBeInTheDocument();
    await flushEffects();
    expect(screen.getByPlaceholderText("Ask a question about the filing corpus")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Build/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("stays on Review when a restored review already has messages", async () => {
    stubLiveApi(EMPTY_CORPUS);
    seedAnsweredConversation();
    render(<ServiceShell />);

    expect(await screen.findByRole("button", { name: "Corpus empty" })).toBeInTheDocument();
    await flushEffects();
    expect(screen.getByText("Data center revenue grew on Hopper demand.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Build/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("keeps the view the user chose while the first readiness is still loading", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    stubLiveApi(EMPTY_CORPUS, async () => { await gate; return liveReadiness(EMPTY_CORPUS); });
    render(<ServiceShell />);

    fireEvent.click(await screen.findByRole("button", { name: "Measure" }));
    expect(screen.getByRole("heading", { name: "Measure retrieval before trusting it." })).toBeInTheDocument();
    release();

    expect(await screen.findByText("db degraded")).toBeInTheDocument();
    await flushEffects();
    expect(screen.getByRole("heading", { name: "Measure retrieval before trusting it." })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Build/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("renders a conversation reply without a verdict pill", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/review/stream")) {
        const frames = [
          'event: node\ndata: {"node":"gate","evidence_count":0,"relevant_count":0,"step_count":1}',
          'event: report\ndata: {"run":{"status":"ok","report":{"report_kind":"conversation","answer":"Hello! Ask me about a filing.","response_source":"engine"},"failure":null,"total_requests":1}}',
          "event: done\ndata: {}",
        ];
        return new Response(`${frames.join("\n\n")}\n\n`, { status: 200, headers: { "content-type": "text/event-stream" } });
      }
      let payload: unknown = {};
      if (url.endsWith("/health")) payload = { status: "ok" };
      else if (url.endsWith("/ready")) payload = READY_RUNTIME;
      else if (url.endsWith("/capabilities")) payload = { can_change_custom_retrieval: false, can_compare_published_snapshots: true };
      else if (url.endsWith("/limits")) payload = { daily_cost_reset_at_utc: "2026-09-02T00:00:00Z" };
      else if (url.endsWith("/snapshots")) payload = { snapshots: [] };
      return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ServiceShell />);

    const textarea = await screen.findByPlaceholderText("Ask a question about the filing corpus");
    fireEvent.change(textarea, { target: { value: "hi there" } });
    fireEvent.keyDown(textarea, { key: "Enter" });

    await waitFor(() => expect(screen.getByText("Hello! Ask me about a filing.")).toBeInTheDocument());
    expect(document.querySelector(".verdict")).toBeNull();
    expect(screen.queryByText("Answer not generated")).toBeNull();
  });
});
