import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HELP_KEY, ONBOARDING_KEY, loadConversations, saveConversations, saveDefaultProfile, loadDefaultProfile } from "@/lib/storage";
import type { DocumentFacets, Readiness } from "@/lib/types";
import { DEFAULT_SESSION_PROFILE } from "@/lib/types";
import { CANNED_JOB, CANNED_SUITES } from "@/lib/canned";
import { enterProductionPreview, exitProductionPreview } from "@/lib/production-preview";
import { TOUR_TARGETS } from "./onboarding";
import { ServiceShell, terminalAnswer } from "./service-shell";

beforeEach(() => { window.history.replaceState(null, "", "/"); });

/** Wait for the same asynchronous browser traversal used by the application arrows. */
async function traverseHistory(direction: "Back" | "Forward") {
  const position = window.history.state?.docreviewNavigation?.position;
  fireEvent.click(screen.getByRole("button", { name: direction }));
  await waitFor(() => expect(window.history.state?.docreviewNavigation?.position).not.toBe(position));
  await act(async () => {});
}

const OPERATOR_URL = "http://operator.test";
const EMPTY_DOCUMENT_FACETS: DocumentFacets = {
  registries: [], issuers: [], years: [], languages: [], forms: [], parse_statuses: [], embedding_statuses: [], snapshots: [],
};

const READY_RUNTIME: Readiness = {
  environment: "prod",
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
  return { ...READY_RUNTIME, environment: "dev", status: corpus.documents ? "ready" : "degraded", admin_mode: "live", corpus };
}

/** Live-build API stub: runtime endpoints plus empty `/admin/*` and operator lists; `ready` lets a test hold back `/ready`. */
function stubLiveApi(corpus: Readiness["corpus"], ready: () => Promise<Readiness> = async () => liveReadiness(corpus)) {
  vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live");
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    let payload: unknown = {};
    if (url.endsWith("/health")) payload = { status: "ok" };
    else if (url.endsWith("/ready")) payload = await ready();
    else if (url.endsWith("/capabilities")) payload = { environment: "dev", can_configure_local_llm: true, can_edit_prompt_policy: true, can_edit_run_limits: true, can_edit_golden: true, can_build_snapshot: true, can_run_evaluation: true, can_change_custom_retrieval: true, can_query_snapshot: true, can_use_operations: true, can_compare_published_snapshots: true };
    else if (url.endsWith("/limits")) payload = { daily_cost_reset_at_utc: "2026-09-02T00:00:00Z", max_input_tokens: 12000, max_output_tokens: 600, remaining_minute: 5, per_minute: 5, remaining_day: 25, per_day: 25, minute_reset_seconds: 0, day_reset_seconds: 0, max_cost_usd: "0.04", remaining_daily_cost_usd: "1.00", daily_cost_usd: "1.00" };
    else if (url.endsWith("/snapshots")) payload = url.includes("/admin/") ? [] : { snapshots: [] };
    else if (url.endsWith("/admin/jobs")) payload = { jobs: [], active_count: 0, queued_count: 0 };
    else if (url.endsWith("/admin/evaluations/runs")) payload = { jobs: [] };
    else if (url.endsWith("/admin/corpus")) payload = { status: { ...corpus, provider: "deterministic" }, manifests: [], documents: [] };
    else if (url.endsWith("/documents/facets")) payload = EMPTY_DOCUMENT_FACETS;
    else if (url.includes("/documents?")) payload = { documents: [], total: 0, next_cursor: null };
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
          source_sha256: "abc", body: "Data Center revenue was up 217%.", context_header: "Item 7", score: 0.9, section_title: "Management's Discussion and Analysis",
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
      environment: "prod", can_configure_local_llm: false,
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
    else if (url.endsWith("/public/documents/facets")) payload = EMPTY_DOCUMENT_FACETS;
    else if (url.includes("/public/documents?")) payload = { documents: [], total: 0, next_cursor: null };
    return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

it("keeps restored development settings intact in prod, blocks both review paths, and creates safe new conversations", async () => {
  cleanup();
  window.localStorage.clear();
  window.localStorage.setItem(ONBOARDING_KEY, "done");
  vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live");
  vi.stubEnv("NEXT_PUBLIC_OPERATOR_BASE_URL", OPERATOR_URL);
  vi.stubEnv("NEXT_PUBLIC_OPERATOR_TOKEN", "test-token");
  const original = { ...DEFAULT_SESSION_PROFILE, engine: "local" as const, local_model: "saved-model", prompt_policy: { ...DEFAULT_SESSION_PROFILE.prompt_policy, additional_instructions: "Saved experiment" } };
  saveDefaultProfile(original);
  saveConversations([{ id: "saved-dev", title: "Saved dev review", createdAt: "2026-09-04", updatedAt: "2026-09-04", profile: original, messages: [{ id: "evidence", role: "assistant", text: "Prior evidence", question: "Saved question", candidateToken: "saved-token", pinnedChunkIds: [1], evidence: [{ chunk_id: 1, doc_id: "doc", item: "7", kind: "text", citation: "c1", start_char: 0, end_char: 1, source_sha256: "abc", body: "Evidence", context_header: "7", score: 1, section_title: null }] }] }]);
  const fetchMock = stubPublicApi();
  vi.resetModules();
  const { ServiceShell: LiveShell } = await import("./service-shell");
  try {
    render(<LiveShell />);
    await screen.findByRole("button", { name: "Saved dev review" });
    expect(screen.getByRole("alert")).toHaveTextContent("Its saved settings have not been changed.");
    fireEvent.change(screen.getByPlaceholderText("Ask a question about the filing corpus"), { target: { value: "New question" } });
    expect(screen.getByRole("button", { name: "Send question" })).toBeDisabled();
    fireEvent.keyDown(screen.getByPlaceholderText("Ask a question about the filing corpus"), { key: "Enter" });
    expect(screen.queryByLabelText("Answer engine")).not.toBeInTheDocument();
    const modeBadge = screen.getByRole("note", { name: "PROD MODE" });
    expect(modeBadge).toHaveAttribute("title", "Server environment: PROD MODE");
    expect(modeBadge.nextElementSibling).toHaveClass("sidebar-nav");
    expect(screen.getByRole("button", { name: "Toggle sidebar" })).toHaveAttribute("title", "PROD MODE");
    expect(screen.getByRole("button", { name: /Review again with selected evidence/, hidden: true })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(screen.queryByRole("button", { name: "Local LLM" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Prompt" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close settings" }));
    fireEvent.click(screen.getByRole("button", { name: /^System ·/ }));
    expect(screen.queryByRole("button", { name: "Operations" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Local model policy" })).not.toBeInTheDocument();
    expect(screen.getAllByText("PROD").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "New review" }));
    expect(loadConversations().find((item) => item.id === "saved-dev")?.profile).toEqual(original);
    expect(loadConversations().find((item) => item.id !== "saved-dev")?.profile).toEqual(DEFAULT_SESSION_PROFILE);
    expect(loadDefaultProfile()).toEqual(original);
    expect(fetchMock.mock.calls.every(([url]) => !String(url).includes("/admin/") && !String(url).startsWith(OPERATOR_URL) && !String(url).includes("/review/stream"))).toBe(true);
  } finally { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules(); window.localStorage.clear(); }
});

it("makes no administrator or local connection calls before capabilities are known", async () => {
  cleanup(); window.localStorage.clear(); window.localStorage.setItem(ONBOARDING_KEY, "done");
  const fetchMock = stubLiveApi(READY_RUNTIME.corpus);
  const ordinaryFetch = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => String(input).endsWith("/capabilities") ? new Promise<Response>(() => undefined) : ordinaryFetch(input, init));
  vi.resetModules();
  const { ServiceShell: LiveShell } = await import("./service-shell");
  try {
    render(<LiveShell />);
    await screen.findByRole("button", { name: "System · healthy" });
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(screen.queryByRole("button", { name: "Prompt" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Local LLM" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send question" })).toBeDisabled();
    expect(fetchMock.mock.calls.every(([url]) => !String(url).includes("/admin/") && !String(url).startsWith(OPERATOR_URL))).toBe(true);
  } finally { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules(); }
});

it("keeps the sidebar mode unknown until the server reports development", async () => {
  cleanup(); window.localStorage.clear(); window.localStorage.setItem(ONBOARDING_KEY, "done");
  const fetchMock = stubLiveApi(READY_RUNTIME.corpus);
  const ordinaryFetch = fetchMock.getMockImplementation()!;
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).endsWith("/capabilities") || String(input).endsWith("/ready")) await pending;
    return ordinaryFetch(input, init);
  });
  vi.resetModules();
  const { ServiceShell: LiveShell } = await import("./service-shell");
  try {
    render(<LiveShell />);
    expect(screen.getByRole("note", { name: "CHECKING MODE" })).toBeInTheDocument();
    expect(screen.queryByRole("note", { name: "DEV MODE" })).not.toBeInTheDocument();
    await act(async () => release());
    const modeBadge = await screen.findByRole("note", { name: "DEV MODE" });
    expect(modeBadge).toHaveAttribute("title", "Server environment: DEV MODE");
    expect(modeBadge.nextElementSibling).toHaveClass("sidebar-nav");
    fireEvent.click(screen.getByRole("button", { name: "Toggle sidebar" }));
    expect(screen.getByRole("button", { name: "Toggle sidebar" })).toHaveAttribute("title", "DEV MODE");
    expect(screen.queryByText(/LOCAL MODEL/)).not.toBeInTheDocument();
  } finally { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules(); }
});

describe("service shell", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem(ONBOARDING_KEY, "done");
    let nextId = 0;
    vi.stubGlobal("crypto", { randomUUID: () => `fixture-id-${++nextId}` });
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    // The build-mode constant is module level, so a stubbed build must not leak forward.
    vi.resetModules();
  });

  it("closes navigation with its own button, backdrop, or Escape and restores toggle focus", async () => {
    stubPublicApi();
    render(<ServiceShell />);
    await screen.findByRole("button", { name: "System · healthy" });
    const toggle = screen.getByRole("button", { name: "Toggle sidebar" });
    const navigation = document.getElementById("service-navigation")!;
    fireEvent.click(screen.getByRole("button", { name: "Close sidebar" }));
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(navigation).toHaveAttribute("inert");
    expect(toggle).toHaveFocus();
    fireEvent.click(toggle);
    fireEvent.keyDown(navigation, { key: "Escape" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole("button", { name: "Close navigation overlay" }));
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
  });

  it("navigates between Build, Measure and System from the sidebar", async () => {
    const fetchMock = stubPublicApi();
    render(<ServiceShell />);
    await waitFor(() => expect(screen.getByRole("button", { name: "System · healthy" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Build" }));
    expect(screen.getByRole("heading", { name: "From filings to verified answers." })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Build" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Read-only portfolio")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Measure" }));
    expect(screen.getByRole("heading", { name: "Measure retrieval before trusting it." })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1. Search trial" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: /^System ·/ }));
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

  it("returns from corpus readiness with the original conversation, draft, profile, and scroll", async () => {
    const fetchMock = stubLiveApi({ ...READY_RUNTIME.corpus, writable: true });
    seedAnsweredConversation();
    render(<ServiceShell />);
    await screen.findByText("Corpus total · 29 filings");
    const readiness = screen.getByRole("button", { name: "View corpus readiness" });
    const question = screen.getByPlaceholderText("Ask a question about the filing corpus");
    fireEvent.change(question, { target: { value: "Keep this unfinished question" } });
    fireEvent.click(within(screen.getByRole("group", { name: "Corpus scope" })).getByRole("button", { name: "SEC" }));
    const original = loadConversations();
    const messages = document.querySelector<HTMLElement>(".messages")!;
    messages.scrollTop = 280;
    expect(fetchMock.mock.calls.some(([url]) => /\/admin\/(corpus|evaluations\/runs)$/.test(String(url)))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Close sidebar" }));
    readiness.focus();
    fireEvent.click(readiness);
    expect(screen.getByRole("heading", { name: "From filings to verified answers." })).toBeVisible();
    const back = screen.getByRole("button", { name: "Back" });
    expect(back).toHaveAttribute("type", "button");
    expect(back).toHaveAttribute("title", expect.stringContaining("Conversation"));
    back.focus();
    expect(back).toHaveFocus();
    messages.scrollTop = 0;
    await traverseHistory("Back");
    expect(question).toBeVisible();
    expect(question).toHaveValue("Keep this unfinished question");
    expect(messages.scrollTop).toBe(280);
    expect(readiness).toHaveFocus();
    expect(loadConversations()).toEqual(original);
    expect(within(screen.getByRole("group", { name: "Corpus scope" })).getByRole("button", { name: "SEC" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Forward" })).toBeEnabled();
  });

  it("suspends pinned scope help while another workspace is visible", async () => {
    stubPublicApi();
    render(<ServiceShell />);
    await screen.findByRole("button", { name: "System · healthy" });
    fireEvent.click(screen.getByRole("button", { name: "About corpus scope" }));
    expect(screen.getByRole("tooltip")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Build" }));
    expect(screen.queryByRole("tooltip")).toBeNull();
    const back = screen.getByRole("button", { name: "Back" });
    back.focus();
    fireEvent.keyDown(back, { key: "Escape" });
    expect(back).toHaveFocus();
    await traverseHistory("Back");
    expect(screen.getByRole("tooltip")).toBeVisible();
    fireEvent.keyDown(screen.getByRole("button", { name: "About corpus scope" }), { key: "Escape" });
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("explains pinning and saved-result limitations without changing the existing answer", async () => {
    stubPublicApi();
    seedAnsweredConversation();
    render(<ServiceShell />);
    fireEvent.click(await screen.findByText("Retrieved evidence candidates · 1"));
    expect(screen.getByText("Pinning does not guarantee that the answer cites this evidence.")).toBeVisible();
    expect(screen.getByText("Selections apply when you review again. The current answer stays unchanged, and a new answer is added.")).toBeVisible();
    expect(screen.getByText("This saved result cannot change evidence. Run the question again to retrieve a fresh selection.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Pin" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Exclude" })).toBeDisabled();
    expect(screen.getByText("Data center revenue grew on Hopper demand.")).toBeVisible();
  });

  it("preserves document filters, selection, and scroll through the related pipeline and another workspace", async () => {
    const fetchMock = stubLiveApi({ ...READY_RUNTIME.corpus, writable: true });
    const ordinaryFetch = fetchMock.getMockImplementation()!;
    const filing = { doc_id: "NVDA-2025", registry: "sec", language: "en", issuer: "NVDA", issuer_id: "NVDA", fiscal_year: 2025, form: "10-K", filing_date: "2026-01-01", report_period: "2025-12-31", filing_id: "NVDA-2025", source_url: "https://example.com/filing", parse_status: "parsed", source_length: 1000, source_sha256: "abc", chunk_count: 4, embedded_chunks: 4, text_chunks: 3, table_chunks: 1, embedding_status: "complete", snapshot_count: 0 };
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const payload = url.includes("/documents?") ? { documents: [filing], total: 1, next_cursor: null }
        : url.endsWith("/documents/NVDA-2025") ? { document: filing, chunks: [], text_chunks: 3, table_chunks: 1, embedded_chunks: 4, item_counts: [], embedding_identities: [], snapshot_memberships: [] } : null;
      return payload ? new Response(JSON.stringify(payload), { headers: { "content-type": "application/json" } }) : ordinaryFetch(input, init);
    });
    render(<ServiceShell />);
    await screen.findByText("Corpus total · 29 filings");
    fireEvent.click(screen.getByRole("button", { name: "Build" }));
    fireEvent.click(within(screen.getByRole("navigation", { name: "Build sections" })).getByRole("button", { name: "Documents" }));
    fireEvent.click(await screen.findByRole("button", { name: "NVDA-2025" }));
    await screen.findByRole("heading", { name: "Related work & next step" });
    const search = screen.getByRole("textbox", { name: "Search documents" });
    fireEvent.change(search, { target: { value: "NVDA" } });
    const build = document.querySelector<HTMLElement>(".build-workspace")!;
    build.scrollTop = 360;
    fireEvent.click(screen.getByRole("button", { name: "Next step" }));
    expect(screen.getByRole("button", { name: "Pipeline" })).toHaveAttribute("aria-pressed", "true");
    build.scrollTop = 0;
    await traverseHistory("Back");
    expect(search).toBeVisible();
    expect(search).toHaveValue("NVDA");
    expect(screen.getByRole("heading", { name: "Related work & next step" })).toBeVisible();
    expect(build.scrollTop).toBe(360);
    fireEvent.click(screen.getByRole("button", { name: "Measure" }));
    await traverseHistory("Back");
    expect(search).toHaveValue("NVDA");
    expect(screen.getByRole("button", { name: "Documents" })).toHaveAttribute("aria-pressed", "true");
    expect(build.scrollTop).toBe(360);
  });

  it("keeps the Back destination and edited question when discarding a golden draft is cancelled", async () => {
    const fetchMock = stubLiveApi({ ...READY_RUNTIME.corpus, writable: true });
    const ordinaryFetch = fetchMock.getMockImplementation()!;
    const question = { id: "draft-01", question: "Original question", category: "simple_lookup", facet: "factual", answers: [], reference_answer: "Original answer" };
    const revision = { revision_id: 7, suite_id: "sec-en", version: 1, status: "draft", payload: [question], sha256: "b".repeat(64), parent_id: null, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z" };
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const payload = url.endsWith("/admin/evaluations/suites") ? CANNED_SUITES : url.endsWith("/canonical") ? { suite_id: "sec-en", filename: "retrieval.json", sha256: "a".repeat(64), payload: [question] } : url.endsWith("/revisions") ? [revision] : null;
      return payload ? new Response(JSON.stringify(payload), { headers: { "content-type": "application/json" } }) : ordinaryFetch(input, init);
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<ServiceShell />);
    await screen.findByText("Corpus total · 29 filings");
    fireEvent.click(screen.getByRole("button", { name: "Measure" }));
    fireEvent.click(screen.getByRole("button", { name: "2. Golden dataset" }));
    await screen.findByRole("option", { name: "v1 · draft" });
    fireEvent.change(screen.getByLabelText("Golden revision"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "draft-01" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Question" }), { target: { value: "Unsaved question" } });
    const rejectedPosition = window.history.state.docreviewNavigation.position;
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(window.history.state.docreviewNavigation.position).toBe(rejectedPosition));
    expect(screen.getByRole("textbox", { name: "Question" })).toHaveValue("Unsaved question");
    expect(screen.getByRole("button", { name: "Back" })).toBeVisible();
    confirm.mockReturnValue(true);
    await traverseHistory("Back");
    expect(screen.getByRole("button", { name: "1. Search trial" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Back" })).toBeVisible();
    confirm.mockRestore();
  });

  it("returns a recovery URL to its requested Build step without running jobs", async () => {
    const originalUrl = window.location.href;
    window.history.replaceState({}, "", "/?recovery_stage=evaluate");
    try {
      const requests = stubLiveApi(EMPTY_CORPUS);
      render(<ServiceShell />);
      await waitFor(() => expect(document.getElementById("stage-7")).toBeInTheDocument());
      expect(await screen.findByRole("button", { name: "Build, needs attention" })).toHaveAttribute("aria-pressed", "true");
      expect(requests.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    } finally { window.history.replaceState({}, "", originalUrl); }
  });

  it("restores the selected evaluation and API editor when returning between workspaces", async () => {
    const fetchMock = stubLiveApi({ ...READY_RUNTIME.corpus, writable: true });
    const ordinaryFetch = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const payload = url.endsWith("/admin/evaluations/suites") ? CANNED_SUITES
        : url.endsWith("/admin/evaluations/runs") ? { jobs: [CANNED_JOB] }
        : url.endsWith("/admin/evaluations/results/16") ? { result_id: 16, suite: "sec-ko", config: {}, metrics: { mrr: 0.8 }, cases: [], raw_artifact_path: "stored.json", created_at: CANNED_JOB.created_at } : null;
      return payload ? new Response(JSON.stringify(payload), { headers: { "content-type": "application/json" } }) : ordinaryFetch(input, init);
    });
    render(<ServiceShell />);
    await screen.findByText("Corpus total · 29 filings");
    fireEvent.click(screen.getByRole("button", { name: "Measure" }));
    fireEvent.click(screen.getByRole("button", { name: "3. Run evaluation" }));
    fireEvent.click(await screen.findByRole("radio", { name: `Select ${CANNED_JOB.job_id}` }));
    await screen.findByRole("heading", { name: "Result details · #16" });
    fireEvent.click(screen.getByRole("button", { name: /^System ·/ }));
    fireEvent.click(screen.getByRole("button", { name: "API inspector" }));
    const request = screen.getByRole("textbox");
    fireEvent.change(request, { target: { value: '{"suite_id":"sec-ko"}' } });
    fireEvent.click(screen.getByRole("button", { name: "System status" }));
    await traverseHistory("Back");
    expect(request).toBeVisible();
    expect(request).toHaveValue('{"suite_id":"sec-ko"}');
    await traverseHistory("Back");
    await traverseHistory("Back");
    expect(screen.getByRole("button", { name: "3. Run evaluation" })).toHaveAttribute("aria-pressed", "true");
    // Result detail intentionally replaces the run list while preserving the selected result.
    expect(screen.queryByRole("radio", { name: `Select ${CANNED_JOB.job_id}` })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back to evaluations" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Result details · #16" })).toBeVisible();
  });

  it("renders the review shell with guides and development links in the same tab", async () => {
    render(<ServiceShell />);

    await waitFor(() =>
      expect(screen.getByPlaceholderText("Ask a question about the filing corpus")).toBeInTheDocument(),
    );
    const guides = screen.getByText("Guides & development", { exact: true });
    expect(guides.closest("details")).not.toHaveAttribute("open");
    expect(screen.getByRole("link", { name: "Development log" })).not.toBeVisible();
    const build = screen.getByRole("button", { name: /^Build(?:, needs attention)?$/ });
    expect(guides.closest(".sidebar-nav")).toBe(build.parentElement);
    expect(guides.compareDocumentPosition(build) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(guides);
    const documentation = screen.getByRole("link", { name: "User guide" });

    expect(screen.getByText("Review filings with verifiable evidence.")).toBeInTheDocument();
    expect(documentation).not.toHaveAttribute("target");
    expect(documentation).toHaveAttribute("href", "/docreview-rag-agent/docs/en/");
    expect(screen.getByRole("navigation", { name: "Guides & development" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Development log" })).toHaveAttribute("href", "/docreview-rag-agent/docs/en/development/");
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
      else if (url.endsWith("/capabilities")) payload = { environment: "prod", can_configure_local_llm: false, can_change_custom_retrieval: false, can_compare_published_snapshots: true };
      else if (url.endsWith("/limits")) payload = { daily_cost_reset_at_utc: "2026-09-02T00:00:00Z", max_input_tokens: 12000, max_output_tokens: 600, remaining_minute: 5, per_minute: 5, remaining_day: 25, per_day: 25, minute_reset_seconds: 0, day_reset_seconds: 0, max_cost_usd: "0.04", remaining_daily_cost_usd: "1.00", daily_cost_usd: "1.00" };
      else if (url.endsWith("/snapshots")) payload = { snapshots: [] };
      else if (url.endsWith("/retrieve")) payload = {
        results: [],
        candidates: [
          { chunk_id: 1, doc_id: "NVDA-FY2025", item: "7", kind: "text", citation: "NVDA FY2025 Item 7", start_char: 0, end_char: 120, source_sha256: "a", body: "Data center revenue grew.", context_header: "Item 7", score: 0.9, section_title: "Management's Discussion and Analysis" },
          { chunk_id: 2, doc_id: "NVDA-FY2025", item: "7", kind: "table", citation: "NVDA FY2025 Item 7 table", start_char: 120, end_char: 240, source_sha256: "a", body: "Revenue by segment.", context_header: "Item 7", score: 0.8, section_title: null },
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
    await waitFor(() => expect(screen.getByRole("button", { name: "System · healthy" })).toBeInTheDocument());

    const scope = screen.getByRole("group", { name: "Corpus scope" });
    expect(within(scope).getByRole("button", { name: "Auto" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(scope).getByRole("button", { name: "SEC" }));
    expect(within(scope).getByRole("button", { name: "SEC" })).toHaveAttribute("aria-pressed", "true");
    expect(within(scope).getByRole("button", { name: "Auto" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("Published corpus")).toBeInTheDocument();
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
    expect(screen.getByRole("button", { name: /^Build(?:, needs attention)?$/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Local operator")).toBeInTheDocument();
  });

  it("stays on Review when the live corpus already has filings", async () => {
    stubLiveApi({ ...READY_RUNTIME.corpus, writable: true });
    render(<ServiceShell />);

    expect(await screen.findByText("Corpus total · 29 filings")).toBeInTheDocument();
    await flushEffects();
    expect(screen.getByPlaceholderText("Ask a question about the filing corpus")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Build(?:, needs attention)?$/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("stays on Review when a restored review already has messages", async () => {
    stubLiveApi(EMPTY_CORPUS);
    seedAnsweredConversation();
    render(<ServiceShell />);

    expect(await screen.findByText("Corpus empty")).toBeInTheDocument();
    await flushEffects();
    expect(screen.getByText("Data center revenue grew on Hopper demand.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Build(?:, needs attention)?$/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("keeps the view the user chose while the first readiness is still loading", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    stubLiveApi(EMPTY_CORPUS, async () => { await gate; return liveReadiness(EMPTY_CORPUS); });
    render(<ServiceShell />);

    fireEvent.click(await screen.findByRole("button", { name: "Measure" }));
    expect(screen.getByRole("heading", { name: "Measure retrieval before trusting it." })).toBeInTheDocument();
    release();

    expect(await screen.findByText("preparation needed")).toBeInTheDocument();
    await flushEffects();
    expect(screen.getByRole("heading", { name: "Measure retrieval before trusting it." })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Build(?:, needs attention)?$/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("toggles Help from the topbar button and the ? key, and persists it", async () => {
    stubPublicApi();
    render(<ServiceShell />);
    await waitFor(() => expect(screen.getByRole("button", { name: "System · healthy" })).toBeInTheDocument());

    const toggle = screen.getByRole("button", { name: "Toggle help" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("complementary", { name: "Help" })).toBeNull();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("complementary", { name: "Help" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Choose a topic" })).toBeInTheDocument();
    expect(document.querySelector(".help-marker, .help-target-highlight")).toBeNull();
    expect(within(screen.getByRole("region", { name: "Recommended" })).getByRole("button", { name: "Corpus scope" })).toBeInTheDocument();
    expect(window.localStorage.getItem(HELP_KEY)).toBe("open");

    fireEvent.keyDown(window, { key: "?" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("complementary", { name: "Help" })).toBeNull();
    expect(window.localStorage.getItem(HELP_KEY)).toBeNull();
    fireEvent.keyDown(window, { key: "?" });
    expect(screen.getByRole("complementary", { name: "Help" })).toBeInTheDocument();

    // Help follows the workspace, including document-specific controls.
    fireEvent.click(screen.getByRole("button", { name: "Build" }));
    expect(screen.getByRole("heading", { name: "Choose a topic" })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Recommended" })).queryByRole("button", { name: "Next step" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Documents" }));
    expect(screen.getByRole("heading", { name: "Choose a topic" })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Recommended" })).getByRole("button", { name: "Document inventory" })).toBeInTheDocument();
    expect(document.querySelector(".help-marker")).toBeNull();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("complementary", { name: "Help" })).toBeNull();
  });

  it("restores a persisted open Help and ignores ? typed into the composer", async () => {
    stubPublicApi();
    window.localStorage.setItem(HELP_KEY, "open");
    render(<ServiceShell />);

    expect(await screen.findByRole("complementary", { name: "Help" })).toBeInTheDocument();
    const textarea = screen.getByPlaceholderText("Ask a question about the filing corpus");
    fireEvent.keyDown(textarea, { key: "?" });
    expect(screen.getByRole("complementary", { name: "Help" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Toggle help" })).toHaveAttribute("aria-pressed", "true");
  });

  it("closes Help when the tour opens and keeps it closed while the tour runs", async () => {
    stubPublicApi();
    window.localStorage.setItem(HELP_KEY, "open");
    render(<ServiceShell />);
    expect(await screen.findByRole("complementary", { name: "Help" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Data & help" }));
    fireEvent.click(screen.getByRole("button", { name: "Show tutorial" }));
    expect(screen.getByText("Step 1 of 7")).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Help" })).toBeNull();
    expect(window.localStorage.getItem(HELP_KEY)).toBeNull();
    fireEvent.keyDown(window, { key: "?" });
    expect(screen.queryByRole("complementary", { name: "Help" })).toBeNull();

    for (let step = 0; step < 6; step += 1) fireEvent.click(screen.getByText("Next"));
    expect(screen.getByText("Need details on any screen? Press ? for Help.")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Finish"));
    fireEvent.keyDown(window, { key: "?" });
    expect(screen.getByRole("complementary", { name: "Help" })).toBeInTheDocument();
  });

  it("marks the sidebar while a local model is answering, and only in an operator build", async () => {
    stubPublicApi();
    // A public bundle cannot select the engine, so the badge cannot exist there.
    saveConversations([{
      id: "local", title: "Local", createdAt: "2026-09-01T00:00:00Z", updatedAt: "2026-09-01T00:00:00Z",
      messages: [], profile: { ...DEFAULT_SESSION_PROFILE, engine: "local" },
    }]);
    render(<ServiceShell />);
    expect(await screen.findByPlaceholderText("Ask a question about the filing corpus")).toBeInTheDocument();
    expect(screen.queryByText("LOCAL MODEL")).toBeNull();
    cleanup();

    vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live");
    vi.resetModules();
    const operator = await import("./service-shell");
    stubLiveApi({ ...READY_RUNTIME.corpus, writable: true });
    render(<operator.ServiceShell />);

    const badge = (await screen.findByText(/^LOCAL MODEL/)).closest('[role="note"]');
    expect(badge).toHaveTextContent("LOCAL MODEL");
    // The explanation is real text, so a keyboard or screen-reader user reaches it.
    expect(badge).toHaveTextContent(/selected model server/);
  });

  it("drops the sidebar mark when the session goes back to OpenAI", async () => {
    vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live");
    vi.resetModules();
    const operator = await import("./service-shell");
    stubLiveApi({ ...READY_RUNTIME.corpus, writable: true });
    saveConversations([{
      id: "openai", title: "OpenAI", createdAt: "2026-09-01T00:00:00Z", updatedAt: "2026-09-01T00:00:00Z",
      messages: [], profile: { ...DEFAULT_SESSION_PROFILE, engine: "openai" },
    }]);
    render(<operator.ServiceShell />);

    expect(await screen.findByPlaceholderText("Ask a question about the filing corpus")).toBeInTheDocument();
    expect(await screen.findByRole("note", { name: "DEV MODE" })).toBeInTheDocument();
    expect(screen.queryAllByRole("note").filter((note) => note.textContent?.includes("LOCAL MODEL"))).toHaveLength(0);
  });

  it("leaves Help alone while a modal owns the screen", async () => {
    stubPublicApi();
    window.localStorage.setItem(HELP_KEY, "open");
    render(<ServiceShell />);
    expect(await screen.findByRole("complementary", { name: "Help" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    const dialog = screen.getByRole("dialog");
    // ? behind the scrim would flip a panel the user cannot see, and Escape belongs to the dialog.
    fireEvent.keyDown(dialog, { key: "?" });
    expect(screen.getByRole("button", { name: "Toggle help" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("complementary", { name: "Help" })).toBeInTheDocument();
    expect(window.localStorage.getItem(HELP_KEY)).toBe("open");
  });

  it("hooks help onto the newest answered message only", async () => {
    stubPublicApi();
    seedAnsweredConversation();
    // A second answer: the marker must sit beside it, not beside the first one scrolled away above.
    const stored = JSON.parse(window.localStorage.getItem("docreview:conversations:v2")!) as Array<{ messages: unknown[] }>;
    const answered = stored[0].messages[1] as Record<string, unknown>;
    stored[0].messages.push({ ...answered, id: "a2", text: "Gross margin rose on mix." });
    window.localStorage.setItem("docreview:conversations:v2", JSON.stringify(stored));
    render(<ServiceShell />);
    await waitFor(() => expect(screen.getByText("Gross margin rose on mix.")).toBeInTheDocument());

    const hooks = document.querySelectorAll('[data-help="review.evidence"]');
    const blocks = document.querySelectorAll("details.evidence");
    expect(blocks).toHaveLength(2);
    expect(hooks).toHaveLength(1);
    expect(hooks[0]).toBe(blocks[1]);
  });

  it("shows a failed run's own numbers and a way to the limit it hit", async () => {
    const failure = {
      code: "budget_exceeded", resource: "wall_clock_s", limit: 120, observed: 138.6, blocked_node: "check",
    };
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/review/stream")) {
        const frames = [
          'event: node\ndata: {"node":"grade","evidence_count":4,"relevant_count":2,"step_count":1}',
          `event: report\ndata: ${JSON.stringify({ run: { run_id: "run-42", status: "budget_exceeded", report: null, failure, total_requests: 2, total_input_tokens: 2539, total_output_tokens: 589, total_time_seconds: 369.1, node_path: ["gate", "retrieve", "grade"] } })}`,
          "event: done\ndata: {}",
        ];
        return new Response(`${frames.join("\n\n")}\n\n`, { status: 200, headers: { "content-type": "text/event-stream" } });
      }
      let payload: unknown = {};
      if (url.endsWith("/health")) payload = { status: "ok" };
      else if (url.endsWith("/ready")) payload = READY_RUNTIME;
      else if (url.endsWith("/capabilities")) payload = { environment: "prod", can_configure_local_llm: false, can_change_custom_retrieval: false, can_compare_published_snapshots: true };
      else if (url.endsWith("/limits")) payload = { daily_cost_reset_at_utc: "2026-09-02T00:00:00Z", max_input_tokens: 12000, max_output_tokens: 600, remaining_minute: 5, per_minute: 5, remaining_day: 25, per_day: 25, minute_reset_seconds: 0, day_reset_seconds: 0, max_cost_usd: "0.04", remaining_daily_cost_usd: "1.00", daily_cost_usd: "1.00" };
      else if (url.endsWith("/snapshots")) payload = { snapshots: [] };
      return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ServiceShell />);

    const textarea = await screen.findByPlaceholderText("Ask a question about the filing corpus");
    fireEvent.change(textarea, { target: { value: "why did it stop" } });
    fireEvent.keyDown(textarea, { key: "Enter" });

    await waitFor(() => expect(screen.getByText(/wall-clock limit of 120s/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Run details" }));
    fireEvent.click(screen.getByRole("tab", { name: "Trace" }));
    // The run identifier is the only handle for correlating this with the server traces.
    expect(screen.getByText("run-42")).toBeInTheDocument();
    expect(screen.getByText("138.6")).toBeInTheDocument();
    expect(screen.getByText("gate → retrieve → grade")).toBeInTheDocument();
    expect(screen.getByText("wall_clock_s")).toBeInTheDocument();

    // Public builds show read-only allowances in System rather than editable run limits.
    fireEvent.click(screen.getByRole("button", { name: "Open run limits" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Limits & availability" })).toBeInTheDocument();
    expect(screen.getByText("Input token ceiling")).toBeInTheDocument();
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
      else if (url.endsWith("/capabilities")) payload = { environment: "prod", can_configure_local_llm: false, can_change_custom_retrieval: false, can_compare_published_snapshots: true };
      else if (url.endsWith("/limits")) payload = { daily_cost_reset_at_utc: "2026-09-02T00:00:00Z", max_input_tokens: 12000, max_output_tokens: 600, remaining_minute: 5, per_minute: 5, remaining_day: 25, per_day: 25, minute_reset_seconds: 0, day_reset_seconds: 0, max_cost_usd: "0.04", remaining_daily_cost_usd: "1.00", daily_cost_usd: "1.00" };
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

it("automatically stores a single local model and blocks sending after it disappears", async () => {
  window.localStorage.clear();
  window.localStorage.setItem(ONBOARDING_KEY, "done");
  const model = { name: "answer", selectable: true, size_bytes: 123, family: "test", parameter_size: "4B", quantization_level: "Q4", capabilities: ["completion"], loaded: true };
  let local: NonNullable<Readiness["review_engines"]>[string] = { enabled: true, protocol: "ollama", models: [model] };
  stubLiveApi(READY_RUNTIME.corpus, async () => ({ ...liveReadiness(READY_RUNTIME.corpus), review_engines: { local } }));
  vi.resetModules();
  const { ServiceShell: LiveShell } = await import("./service-shell");
  saveConversations([{ id: "local", title: "Local question", createdAt: "2026-09-01", updatedAt: "2026-09-01", messages: [], profile: { ...DEFAULT_SESSION_PROFILE, engine: "local" } }]);
  render(<LiveShell />);
  await waitFor(() => expect(loadConversations()[0].profile?.local_model).toBe("answer"));
  expect(loadConversations()[0].profile?.engine).toBe("local");
  fireEvent.change(screen.getByPlaceholderText("Ask a question about the filing corpus"), { target: { value: "test question" } });
  expect(screen.getByRole("button", { name: "Send question" })).toBeEnabled();
  local = { enabled: false, reason: "unreachable", models: [] };
  await act(async () => { window.dispatchEvent(new Event("online")); });
  await waitFor(() => expect(screen.getByRole("button", { name: "Send question" })).toBeDisabled());
  expect(loadConversations()[0].profile?.local_model).toBe("answer");
  expect(loadConversations()[0].profile?.engine).toBe("local");
  local = { enabled: true, protocol: "ollama", models: [model] };
  await act(async () => { window.dispatchEvent(new Event("online")); });
  await waitFor(() => expect(screen.getByRole("button", { name: "Send question" })).toBeEnabled());
});

it("preserves streamed messages and the submitted settings while background discovery updates a profile", async () => {
  cleanup();
  window.localStorage.clear();
  window.localStorage.setItem(ONBOARDING_KEY, "done");
  let local: NonNullable<Readiness["review_engines"]>[string] = { enabled: false, reason: "not_configured", models: [] };
  const fetchMock = stubLiveApi(READY_RUNTIME.corpus, async () => ({ ...liveReadiness(READY_RUNTIME.corpus), review_engines: { local } }));
  const ordinaryFetch = fetchMock.getMockImplementation()!;
  let finish!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  let submitted: { session_profile: typeof DEFAULT_SESSION_PROFILE } | undefined;
  fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).endsWith("/review/stream")) {
      submitted = JSON.parse(String(init?.body));
      return pending;
    }
    return ordinaryFetch(input, init);
  });
  vi.resetModules();
  const { ServiceShell: LiveShell } = await import("./service-shell");
  try {
    saveConversations([{ id: "keep", title: "New review", createdAt: "2026-09-04", updatedAt: "2026-09-04", messages: [], profile: DEFAULT_SESSION_PROFILE }]);
    render(<LiveShell />);
    await waitFor(() => expect(screen.getByRole("button", { name: "System · healthy" })).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText("Ask a question about the filing corpus"), { target: { value: "Keep this question" } });
    fireEvent.click(screen.getByRole("button", { name: "Send question" }));
    await waitFor(() => expect(submitted).toBeDefined());
    expect(screen.getByText("Waiting for the server")).toBeVisible();
    expect(screen.getByRole("list", { name: "Evidence review progress" }).children).toHaveLength(6);
    fireEvent.click(screen.getByRole("button", { name: "Review settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Evidence" }));
    fireEvent.change(screen.getByLabelText("Conversation history turns"), { target: { value: "4" } });
    local = { enabled: true, protocol: "ollama", models: [{ name: "answer", selectable: true, size_bytes: null, family: null, parameter_size: null, quantization_level: null, capabilities: ["completion"], loaded: false }] };
    await act(async () => { window.dispatchEvent(new Event("online")); });
    finish(new Response('event: report\ndata: {"run":{"run_id":"concurrency-check","status":"budget_exceeded","report":null,"failure":{"code":"budget_exceeded","resource":"iterations","limit":3,"observed":4,"blocked_node":"grade"}}}\n\nevent: done\ndata: {}\n\n', { headers: { "content-type": "text/event-stream" } }));
    await waitFor(() => { expect(loadConversations()[0].messages).toHaveLength(2); expect(loadConversations()[0].messages[1].pending).toBe(false); });
    await waitFor(() => expect(loadConversations()[0].profile?.local_model).toBe("answer"));
    expect(loadConversations()[0].messages[0].text).toBe("Keep this question");
    expect(loadConversations()[0].profile?.prompt_policy.history_turns).toBe(4);
    expect(submitted?.session_profile.prompt_policy.history_turns).toBe(6);
    expect(loadConversations()[0].profile?.engine).toBe("openai");
    expect(screen.queryByText("Waiting for the server")).not.toBeInTheDocument();
    expect(loadConversations()[0].messages[1].execution).toMatchObject({
      node: "waiting", observed: [], outcome: "failed", retries: 0,
    });
    expect(screen.getByText("Execution summary")).toBeInTheDocument();
  } finally {
    cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules();
  }
});

describe("unified conversation drawer", () => {
beforeEach(() => {
  cleanup();
  window.localStorage.clear();
  window.localStorage.setItem(ONBOARDING_KEY, "done");
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

it("opens the unified public filter editor from an offscreen Help destination", async () => {
  const fetchMock = stubPublicApi();
  render(<ServiceShell />);
  await screen.findByRole("button", { name: "System · healthy" });
  fireEvent.click(screen.getByRole("button", { name: "Build" }));
  fireEvent.click(screen.getByRole("button", { name: "Toggle help" }));
  fireEvent.change(await screen.findByRole("textbox", { name: "Search help" }), { target: { value: "review.rag" } });
  const topic = document.querySelector<HTMLButtonElement>('.help-topic-row[data-help-item="review.rag"]');
  expect(topic).not.toBeNull();
  fireEvent.click(topic!);
  fireEvent.click(document.querySelector<HTMLButtonElement>(".help-go-button")!);
  const dialog = await screen.findByRole("dialog", { name: "Conversation settings" });
  expect(within(dialog).getByRole("button", { name: "Filters" })).toHaveAttribute("aria-pressed", "true");
  expect(within(dialog).queryByRole("button", { name: "Search" })).not.toBeInTheDocument();
  expect(within(dialog).queryByRole("button", { name: "Run limits" })).not.toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/admin/"))).toBe(false);
});

it("preserves the question and blocks Send until an invalid drawer draft is discarded", async () => {
  stubPublicApi();
  render(<ServiceShell />);
  await screen.findByRole("button", { name: "System · healthy" });
  const question = screen.getByPlaceholderText("Ask a question about the filing corpus");
  fireEvent.change(question, { target: { value: "Keep my question" } });
  const send = screen.getByRole("button", { name: "Send question" });
  const stored = loadConversations();
  expect(send).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Review settings" }));
  const company = screen.getByLabelText("Companies");
  fireEvent.keyDown(window, { key: "?" });
  expect(screen.queryByRole("complementary", { name: "Help" })).not.toBeInTheDocument();
  await waitFor(() => expect(company).toBeEnabled());
  fireEvent.change(company, { target: { value: "unfinished company" } });
  expect(send).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Close conversation settings" }));
  expect(screen.queryByRole("dialog", { name: "Conversation settings" })).not.toBeInTheDocument();
  expect(send).toBeEnabled();
  expect(question).toHaveValue("Keep my question");
  expect(loadConversations()).toEqual(stored);
});
});

it("keeps confirmed routing with its submitted profile while next-request controls and preview change", async () => {
  cleanup();
  window.localStorage.clear();
  window.localStorage.setItem(ONBOARDING_KEY, "done");
  const fetchMock = stubPublicApi();
  const ordinaryFetch = fetchMock.getMockImplementation()!;
  let stream!: ReadableStreamDefaultController<Uint8Array>;
  let submitted: { session_profile: typeof DEFAULT_SESSION_PROFILE } | undefined;
  const encoder = new TextEncoder();
  const scope = { source: "alias", filters: { registries: ["dart"], issuers: ["005930"], fiscal_years: [2024] } };
  fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).endsWith("/review/stream")) {
      submitted = JSON.parse(String(init?.body));
      return Promise.resolve(new Response(new ReadableStream<Uint8Array>({ start(controller) { stream = controller; } }), { headers: { "content-type": "text/event-stream" } }));
    }
    return ordinaryFetch(input, init);
  });
  try {
    render(<ServiceShell />);
    await screen.findByRole("button", { name: "System · healthy" });
    const input = screen.getByPlaceholderText("Ask a question about the filing corpus");
    fireEvent.change(input, { target: { value: "삼성전자 매출" } });
    fireEvent.click(screen.getByRole("button", { name: "Send question" }));
    await waitFor(() => expect(submitted).toBeDefined());
    expect(screen.getByText("Waiting for server-confirmed routing")).toBeVisible();
    await act(async () => { stream.enqueue(encoder.encode(`event: stage\ndata: ${JSON.stringify({ node: "route", phase: "end", status: "completed", elapsed_ms: 5, resolved_scope: scope })}\n\n`)); });
    expect(screen.getByText(/Source: DART · Company: 005930 · Fiscal year: 2024/)).toBeVisible();
    fireEvent.change(input, { target: { value: "Next draft stays here" } });
    fireEvent.click(within(screen.getByRole("group", { name: "Corpus scope" })).getByRole("button", { name: "SEC" }));
    fireEvent.change(screen.getByLabelText("Retrieval preset"), { target: { value: "accuracy" } });
    fireEvent.click(screen.getByRole("button", { name: "Settings details / request preview" }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(input).toHaveValue("Next draft stays here");
    expect(submitted?.session_profile.corpus_scope).toBe("auto");
    expect(submitted?.session_profile.retrieval_preset).toBe("balanced");
    await act(async () => {
      stream.enqueue(encoder.encode(`event: report\ndata: ${JSON.stringify({ run: { status: "error", failure: { code: "node_error", message: "Regression fixture" }, execution: { effective_settings: { resolved_scope: scope } } } })}\n\nevent: done\ndata: {}\n\n`));
      stream.close();
    });
    await waitFor(() => { expect(loadConversations()[0].messages).toHaveLength(2); expect(loadConversations()[0].messages[1].pending).toBe(false); });
    const conversation = loadConversations()[0];
    expect(conversation.messages[0].text).toBe("삼성전자 매출");
    expect(conversation.messages[1].execution).toMatchObject({ selectedScope: "auto", resolvedScope: scope });
    expect(conversation.profile).toMatchObject({ corpus_scope: "sec", retrieval_preset: "accuracy" });
    expect(input).toHaveValue("Next draft stays here");
  } finally { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); }
});

describe("isolated production presentation preview", () => {
  beforeEach(() => {
    exitProductionPreview();
    window.localStorage.clear();
    window.localStorage.setItem(ONBOARDING_KEY, "done");
  });
  afterEach(() => { cleanup(); exitProductionPreview(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

  it("retains the DEV draft, profile, history, and scroll behind the preview frame", async () => {
    stubLiveApi({ ...READY_RUNTIME.corpus, writable: true });
    seedAnsweredConversation();
    render(<ServiceShell />);
    await screen.findByText("Corpus total · 29 filings");
    const question = screen.getByPlaceholderText("Ask a question about the filing corpus");
    fireEvent.change(question, { target: { value: "Keep this DEV draft" } });
    fireEvent.click(within(screen.getByRole("group", { name: "Corpus scope" })).getByRole("button", { name: "SEC" }));
    const original = JSON.stringify(window.localStorage);
    const messages = document.querySelector<HTMLElement>(".messages")!;
    messages.scrollTop = 240;
    const trigger = screen.getByRole("button", { name: "Production preview" });
    trigger.focus();
    fireEvent.click(trigger);
    expect(screen.getByTitle("Production preview interface")).toHaveAttribute("src", "/docreview-rag-agent/production-preview/?locale=en&theme=system");
    expect(question).not.toBeVisible();
    expect(screen.getByText("Data center revenue grew on Hopper demand.")).not.toBeVisible();
    expect(screen.queryByRole("button", { name: "System · healthy" })).toBeNull();
    expect(screen.getByText(/The backend is still DEV/)).toBeVisible();
    expect(JSON.stringify(window.localStorage)).toBe(original);
    fireEvent.click(screen.getByRole("button", { name: "Exit preview" }));
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(question).toBeVisible();
    expect(question).toHaveValue("Keep this DEV draft");
    expect(messages.scrollTop).toBe(240);
    expect(within(screen.getByRole("group", { name: "Corpus scope" })).getByRole("button", { name: "SEC" })).toHaveAttribute("aria-pressed", "true");
    expect(JSON.stringify(window.localStorage)).toBe(original);
  });

  it("mounts a fresh public session without reading DEV history or calling private readiness", async () => {
    const fetchMock = stubLiveApi({ ...READY_RUNTIME.corpus, writable: true });
    seedAnsweredConversation();
    const original = JSON.stringify(window.localStorage);
    enterProductionPreview("document");
    render(<ServiceShell publicPreview />);
    await screen.findByText("Published corpus");
    expect(screen.queryByText("Data center revenue grew on Hopper demand.")).toBeNull();
    expect(screen.queryByText("NVIDIA data center")).toBeNull();
    expect(screen.queryByText(/Corpus total · 29/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Production preview" })).toBeNull();
    expect(screen.queryByLabelText("Answer engine")).toBeNull();
    const question = screen.getByPlaceholderText("Ask a question about the filing corpus");
    fireEvent.change(question, { target: { value: "Preview draft only" } });
    expect(screen.getByRole("button", { name: "Send question" })).toBeDisabled();
    fireEvent.keyDown(question, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Review settings" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/public/documents/facets"))).toBe(true));
    expect(fetchMock.mock.calls.every(([url]) => !String(url).includes("/admin/") && !String(url).endsWith("/ready") && !String(url).includes("/review/stream"))).toBe(true);
    expect(JSON.stringify(window.localStorage)).toBe(original);
  });
});


describe("in-message review lifecycle", () => {
  beforeEach(() => {
    cleanup(); window.localStorage.clear(); window.localStorage.setItem(ONBOARDING_KEY, "done");
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

  /** Keep the streaming response open so the pending message can be inspected between events. */
  async function startReview(question = "Explain this filing", revalidate = false) {
    if (revalidate) {
      seedAnsweredConversation();
      const saved = loadConversations();
      saved[0].messages[1] = { ...saved[0].messages[1], question, candidateToken: "fixture-token", pinnedChunkIds: [1], excludedChunkIds: [] };
      saveConversations(saved);
    }
    const fetchMock = stubPublicApi();
    const ordinaryFetch = fetchMock.getMockImplementation()!;
    let stream!: ReadableStreamDefaultController<Uint8Array>;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith("/review/stream")) {
        return Promise.resolve(new Response(new ReadableStream<Uint8Array>({ start(controller) { stream = controller; init?.signal?.addEventListener("abort", () => controller.error(new DOMException("Aborted", "AbortError")), { once: true }); } }), { headers: { "content-type": "text/event-stream" } }));
      }
      return ordinaryFetch(input, init);
    });
    render(<ServiceShell />);
    await screen.findByRole("button", { name: "System · healthy" });
    const input = screen.getByPlaceholderText("Ask a question about the filing corpus");
    if (revalidate) {
      fireEvent.click(await screen.findByText(/Retrieved evidence candidates/));
      fireEvent.click(screen.getByRole("button", { name: "Review again with selected evidence" }));
    } else {
      fireEvent.change(input, { target: { value: question } });
      await waitFor(() => expect(screen.getByRole("button", { name: "Send question" })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: "Send question" }));
    }
    await screen.findByText("Waiting for the server");
    const message = document.querySelector<HTMLElement>(".message.assistant.pending")!;
    const summary = message.querySelector<HTMLDetailsElement>(".review-execution-summary")!;
    const progress = message.querySelector<HTMLElement>(".review-progress")!;
    return { stream, message, summary, progress, input, question, id: message.dataset.messageId!, encoder: new TextEncoder() };
  }

  it.each(["SUPPORTED", "NOT_IN_DOCS"])("keeps the same message, summary DOM and open state through %s", async (label) => {
    const request = await startReview();
    const pending = loadConversations()[0].messages;
    expect(pending).toHaveLength(2);
    expect(pending[0]).toMatchObject({ role: "user", text: request.question });
    expect(pending[1]).toMatchObject({ id: request.id, role: "assistant", pending: true });
    expect(pending[0].id).not.toBe(pending[1].id);
    expect(request.message.closest(".messages-inner")).not.toBeNull();
    expect(document.querySelector(".composer-wrap .review-progress")).toBeNull();
    expect(within(request.message).getByRole("button", { name: "Stop request" })).toBeVisible();
    expect(request.summary.open).toBe(true);
    const nodes = label === "SUPPORTED" ? ["gate", "retrieve", "grade", "check"] : ["gate", "retrieve", "grade"];
    await act(async () => { for (const node of nodes) request.stream.enqueue(request.encoder.encode(`event: stage\ndata: ${JSON.stringify({ node, phase: "end", status: "completed", evidence_count: 3, relevant_count: label === "SUPPORTED" ? 2 : 0, step_count: 1 })}\n\n`)); });
    expect(request.message.querySelector(".review-progress")).toBe(request.progress);
    const viewport = document.querySelector<HTMLElement>(".messages")!;
    Object.defineProperty(viewport, "scrollHeight", { configurable: true, value: 700 });
    Object.defineProperty(viewport, "clientHeight", { configurable: true, value: 200 });
    const reasons = label === "NOT_IN_DOCS" ? [{ code: "relevance_below_threshold", candidate_count: 3, relevant_count: 0, minimum_required: 1 }] : [];
    await act(async () => { request.stream.enqueue(request.encoder.encode(`event: report\ndata: ${JSON.stringify({ run: { status: "ok", report: { label, answer: label === "SUPPORTED" ? "The cited result." : "NOT_IN_DOCS", reasons, citations: [] } } })}\n\nevent: done\ndata: {}\n\n`)); request.stream.close(); });
    await waitFor(() => expect(loadConversations()[0].messages[1].pending).toBe(false));
    expect(document.querySelector(`[data-message-id="${request.id}"]`)).toBe(request.message);
    expect(request.message.querySelector(".review-execution-summary")).toBe(request.summary);
    expect(request.message.querySelector(".review-progress")).toBe(request.progress);
    expect(request.summary.open).toBe(true);
    expect(within(request.message).queryByRole("button", { name: "Stop request" })).toBeNull();
    expect(viewport.scrollTop).toBe(700);
    expect(request.message.querySelectorAll(".review-progress-steps li.skipped")).toHaveLength(label === "NOT_IN_DOCS" ? 1 : 0);
  });

  it("updates cancellation in place and does not force a reader back to the bottom", async () => {
    const request = await startReview();
    const viewport = document.querySelector<HTMLElement>(".messages")!;
    Object.defineProperty(viewport, "scrollHeight", { configurable: true, value: 1000 });
    Object.defineProperty(viewport, "clientHeight", { configurable: true, value: 200 });
    viewport.scrollTop = 50;
    fireEvent.scroll(viewport);
    fireEvent.click(within(request.message).getByRole("button", { name: "Stop request" }));
    await waitFor(() => expect(loadConversations()[0].messages[1].pending).toBe(false));
    expect(loadConversations()[0].messages[1]).toMatchObject({ id: request.id, execution: { outcome: "cancelled" } });
    expect(request.message.querySelector(".review-progress")).toBe(request.progress);
    expect(viewport.scrollTop).toBe(50);
    expect(document.querySelectorAll(".message.assistant")).toHaveLength(1);
    expect(request.summary.open).toBe(true);
  });

  it("keeps infrastructure failure in the pending message and restores the question for retry", async () => {
    const request = await startReview();
    await act(async () => request.stream.error(new TypeError("Network unavailable")));
    await waitFor(() => expect(loadConversations()[0].messages[1].pending).toBe(false));
    expect(loadConversations()[0].messages[1]).toMatchObject({ id: request.id, text: "Network unavailable", execution: { outcome: "failed" } });
    expect(request.input).toHaveValue(request.question);
    expect(request.message.querySelector(".review-progress")).toBe(request.progress);
    expect(request.summary.open).toBe(true);
    expect(document.querySelectorAll(".message.assistant")).toHaveLength(1);
  });

  it("finalizes the original message after switching conversations without changing the new draft", async () => {
    const request = await startReview();
    const originalId = loadConversations()[0].id;
    fireEvent.click(screen.getByRole("button", { name: "New review" }));
    fireEvent.change(request.input, { target: { value: "Different conversation draft" } });
    await act(async () => { request.stream.enqueue(request.encoder.encode('event: report\ndata: {"run":{"status":"ok","report":{"report_kind":"conversation","answer":"Original conversation answer."}}}\n\nevent: done\ndata: {}\n\n')); request.stream.close(); });
    await waitFor(() => expect(loadConversations().find((conversation) => conversation.id === originalId)?.messages[1].pending).toBe(false));
    const original = loadConversations().find((conversation) => conversation.id === originalId)!;
    expect(original.messages[1]).toMatchObject({ id: request.id, text: "Original conversation answer." });
    expect(request.input).toHaveValue("Different conversation draft");
    expect(screen.queryByText("Original conversation answer.")).toBeNull();
  });


  it.each([0, 2])("reuses only pre-question context for selected evidence with a %i-turn bound", async (historyTurns) => {
    seedAnsweredConversation();
    const saved = loadConversations();
    const question = "And 2024?";
    const prior = [{ id: "prior-user", role: "user" as const, text: "Explain NVIDIA data center revenue in its filings." }, { id: "prior-answer", role: "assistant" as const, text: "The filings describe its data center revenue." }];
    saved[0].profile = { ...DEFAULT_SESSION_PROFILE, prompt_policy: { ...DEFAULT_SESSION_PROFILE.prompt_policy, history_turns: historyTurns } };
    saved[0].messages = [
      { id: "old-user", role: "user", text: "Older question" },
      { id: "old-answer", role: "assistant", text: "Older answer" },
      ...prior,
      { id: "follow-up", role: "user", text: question },
      { ...saved[0].messages[1], question, candidateToken: "follow-up-token", pinnedChunkIds: [1], excludedChunkIds: [] },
      { id: "later-user", role: "user", text: question },
      { id: "later-answer", role: "assistant", text: "A later exchange must not change the snapshot context." },
    ];
    saveConversations(saved);
    const fetchMock = stubLiveApi({ ...READY_RUNTIME.corpus, writable: true });
    const ordinaryFetch = fetchMock.getMockImplementation()!;
    let submitted: { conversation_history: Array<{ role: string; text: string }> } | undefined;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith("/review/stream")) {
        submitted = JSON.parse(String(init?.body));
        return Promise.resolve(new Response('event: report\ndata: {"run":{"status":"ok","report":{"label":"SUPPORTED","answer":"Re-reviewed contextual answer.","citations":[]}}}\n\nevent: done\ndata: {}\n\n', { headers: { "content-type": "text/event-stream" } }));
      }
      return ordinaryFetch(input, init);
    });
    render(<ServiceShell />);
    await screen.findByRole("button", { name: "System · healthy" });
    fireEvent.click(await screen.findByText(/Retrieved evidence candidates/));
    fireEvent.click(screen.getByRole("button", { name: "Review again with selected evidence" }));
    await screen.findByText("Re-reviewed contextual answer.");
    expect(submitted?.conversation_history).toEqual(historyTurns === 0 ? [] : prior.map(({ role, text }) => ({ role, text })));
  });

  it("re-reviews selected evidence in one new message and keeps an explicitly collapsed summary collapsed", async () => {
    const request = await startReview("Review the selected filing", true);
    expect(loadConversations()[0].messages).toHaveLength(3);
    expect(screen.getByText("Re-checking selected evidence")).toBeVisible();
    fireEvent.click(within(request.summary).getByText("Execution summary"));
    await waitFor(() => expect(request.summary.open).toBe(false));
    await act(async () => { request.stream.enqueue(request.encoder.encode('event: report\ndata: {"run":{"status":"ok","report":{"label":"SUPPORTED","answer":"Re-reviewed answer.","citations":[]}}}\n\nevent: done\ndata: {}\n\n')); request.stream.close(); });
    await waitFor(() => expect(loadConversations()[0].messages[2].pending).toBe(false));
    expect(loadConversations()[0].messages[2].id).toBe(request.id);
    expect(loadConversations()[0].messages[1].text).toBe("Data center revenue grew on Hopper demand.");
    expect(request.message.querySelector(".review-execution-summary")).toBe(request.summary);
    expect(request.message.querySelector(".review-progress")).toBe(request.progress);
    expect(request.summary.open).toBe(false);
  });
  it("cancels a pending request when its conversation is deleted instead of stranding the composer", async () => {
    const request = await startReview();
    const originalId = loadConversations()[0].id;
    fireEvent.click(screen.getByRole("button", { name: `Delete ${request.question}` }));
    fireEvent.change(request.input, { target: { value: "Question after deletion" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Send question" })).toBeEnabled());
    expect(loadConversations().some((conversation) => conversation.id === originalId)).toBe(false);
    expect(document.querySelector(".message.pending")).toBeNull();
    expect(loadConversations()[0].messages).toHaveLength(0);
  });

  it("restores an orphaned pending message as failed without replaying a request", async () => {
    saveConversations([{ id: "orphan", title: "Interrupted", createdAt: "2026-09-06", updatedAt: "2026-09-06", profile: DEFAULT_SESSION_PROFILE, messages: [{ id: "question", role: "user", text: "Interrupted question" }, { id: "pending", role: "assistant", text: "", pending: true, execution: { node: "retrieve", evidence: 3, relevant: 0, steps: 0, observed: ["gate", "retrieve"], completedNodes: ["gate"], outcome: "running" } }] }]);
    const fetchMock = stubPublicApi();
    render(<ServiceShell />);
    await screen.findByText("The request was interrupted. Send the question again.");
    expect(loadConversations()[0].messages[1]).toMatchObject({ id: "pending", pending: false, execution: { outcome: "failed" } });
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/review/stream"))).toBe(false);
    expect(screen.queryByRole("button", { name: "Stop request" })).toBeNull();
  });
});


describe("right-side run details", () => {
  beforeEach(() => {
    cleanup(); window.localStorage.clear(); window.localStorage.setItem(ONBOARDING_KEY, "done");
    stubPublicApi();
    saveConversations([{ id: "runs", title: "Two questions", createdAt: "2026-09-07", updatedAt: "2026-09-07", profile: DEFAULT_SESSION_PROFILE, messages: [
      { id: "q1", role: "user", text: "First filing question" },
      { id: "answer-first", role: "assistant", text: "First answer", diagnostics: [{ label: "Run ID", value: "run-first" }], execution: { node: "report", evidence: 0, relevant: 0, steps: 0, outcome: "completed" } },
      { id: "q2", role: "user", text: "Second filing question" },
      { id: "answer-second", role: "assistant", text: "Second answer", diagnostics: [{ label: "Run ID", value: "run-second" }], execution: { node: "report", evidence: 0, relevant: 0, steps: 0, outcome: "completed" } },
    ] }]);
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

  it("moves details out of the answer and restores each question's last section", async () => {
    render(<ServiceShell />);
    const buttons = await screen.findAllByRole("button", { name: "Run details" });
    const composer = screen.getByPlaceholderText("Ask a question about the filing corpus");
    fireEvent.change(composer, { target: { value: "Keep this unsent draft" } });
    expect(screen.queryByText("run-first")).not.toBeInTheDocument();
    expect(document.querySelectorAll(".review-execution-summary")).toHaveLength(2);
    expect(document.querySelector(".message .execution-performance")).toBeNull();
    fireEvent.click(buttons[0]);
    let panel = screen.getByRole("dialog", { name: "Run details" });
    expect(within(panel).getByText("Q. First filing question")).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("tab", { name: "Trace" }));
    expect(within(panel).getByText("run-first")).toBeInTheDocument();
    fireEvent.click(buttons[1]);
    panel = screen.getByRole("dialog", { name: "Run details" });
    expect(within(panel).getByText("Q. Second filing question")).toBeInTheDocument();
    expect(within(panel).getByRole("tab", { name: "Performance" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(buttons[0]);
    expect(screen.getByRole("tab", { name: "Trace" })).toHaveAttribute("aria-selected", "true");
    fireEvent.pointerDown(composer);
    expect(screen.queryByRole("dialog", { name: "Run details" })).toBeNull();
    expect(composer).toHaveValue("Keep this unsent draft");
    fireEvent.click(buttons[0]);
    expect(screen.getByRole("tab", { name: "Trace" })).toHaveAttribute("aria-selected", "true");
  });

  it("keeps only one right panel open and closes help from the composer", async () => {
    render(<ServiceShell />);
    const buttons = await screen.findAllByRole("button", { name: "Run details" });
    fireEvent.click(screen.getByRole("button", { name: "Toggle help" }));
    expect(screen.getByRole("complementary", { name: "Help" })).toBeInTheDocument();
    fireEvent.click(buttons[0]);
    expect(screen.queryByRole("complementary", { name: "Help" })).toBeNull();
    expect(screen.getByRole("dialog", { name: "Run details" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Toggle help" }));
    expect(screen.queryByRole("dialog", { name: "Run details" })).toBeNull();
    expect(screen.getByRole("complementary", { name: "Help" })).toBeInTheDocument();
    fireEvent.pointerDown(screen.getByPlaceholderText("Ask a question about the filing corpus"));
    expect(screen.queryByRole("complementary", { name: "Help" })).toBeNull();
    expect(window.localStorage.getItem(HELP_KEY)).toBeNull();
  });
});


describe("browser navigation history", () => {
  beforeEach(() => {
    cleanup(); window.localStorage.clear(); window.localStorage.setItem(ONBOARDING_KEY, "done"); stubPublicApi();
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

  it("shares back/forward and list jumps with URL history and clears forward on new navigation", async () => {
    render(<ServiceShell />);
    await screen.findByRole("button", { name: "System · healthy" });
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Forward" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Build" }));
    fireEvent.click(screen.getByRole("button", { name: "Documents" }));
    fireEvent.click(screen.getByRole("button", { name: "System · healthy" }));
    expect(new URLSearchParams(window.location.search).get("view")).toBe("system");
    await traverseHistory("Back");
    expect(new URLSearchParams(window.location.search).get("tab")).toBe("documents");
    expect(screen.getByRole("button", { name: "Documents" })).toHaveAttribute("aria-pressed", "true");
    await traverseHistory("Forward");
    expect(new URLSearchParams(window.location.search).get("view")).toBe("system");
    fireEvent.click(screen.getByRole("button", { name: "System · Status" }));
    const list = screen.getByRole("listbox", { name: "Navigation history" });
    fireEvent.click(within(list).getByRole("option", { name: /Conversation/ }));
    await waitFor(() => expect(new URLSearchParams(window.location.search).get("view")).toBe("review"));
    expect(screen.getByRole("button", { name: "Forward" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Measure" }));
    expect(screen.getByRole("button", { name: "Forward" })).toBeDisabled();
    window.history.back();
    await waitFor(() => expect(new URLSearchParams(window.location.search).get("view")).toBe("review"));
    expect(screen.getByPlaceholderText("Ask a question about the filing corpus")).toBeVisible();
    window.history.forward();
    await waitFor(() => expect(new URLSearchParams(window.location.search).get("view")).toBe("measure"));
  });

  it("restores a reloaded URL while preserving unrelated parameters and base path", async () => {
    window.history.replaceState(null, "", "/docreview-rag-agent/?view=measure&tab=snapshots&locale=ko#saved");
    render(<ServiceShell />);
    await screen.findByRole("button", { name: "System · healthy" });
    await waitFor(() => expect(screen.getByRole("button", { name: "4. Compare and save" })).toHaveAttribute("aria-pressed", "true"));
    expect(window.location.pathname).toBe("/docreview-rag-agent/");
    expect(new URLSearchParams(window.location.search).get("locale")).toBe("ko");
    expect(window.location.hash).toBe("#saved");
    cleanup(); render(<ServiceShell />);
    await waitFor(() => expect(screen.getByRole("button", { name: "4. Compare and save" })).toHaveAttribute("aria-pressed", "true"));
  });

  it("falls back to a saved conversation when a shared URL names an unknown local id", async () => {
    seedAnsweredConversation();
    window.history.replaceState(null, "", "/?view=review&conversation=unavailable");
    render(<ServiceShell />);
    await screen.findByText("Data center revenue grew on Hopper demand.");
    expect(new URLSearchParams(window.location.search).get("conversation")).toBe("seeded");
    expect(screen.getByRole("button", { name: "Conversation · NVIDIA data center" })).toBeVisible();
  });
});


it.each(["en", "ko"] as const)("shows the measured CPU warning before sending and opens the right settings in %s", async (locale) => {
  cleanup(); window.localStorage.clear(); window.localStorage.setItem(ONBOARDING_KEY, "done");
  window.localStorage.setItem("docreview.locale", locale);
  const model = { name: "answer", selectable: true, loaded: true, size_bytes: 100, family: null, parameter_size: null, quantization_level: null, capabilities: ["completion"], cpu_performance: { tokens_per_second: 10, measured_at: new Date().toISOString() } };
  let local: NonNullable<Readiness["review_engines"]>[string] = { enabled: true, protocol: "ollama", models: [model] };
  const fetchMock = stubLiveApi(READY_RUNTIME.corpus, async () => ({ ...liveReadiness(READY_RUNTIME.corpus), review_engines: { local } }));
  const original = { ...DEFAULT_SESSION_PROFILE, engine: "local" as const, local_model: "answer" };
  saveConversations([{ id: "cpu", title: "CPU review", createdAt: "2026-09-07", updatedAt: "2026-09-07", messages: [], profile: original }]);
  vi.resetModules();
  const { ServiceShell: LiveShell } = await import("./service-shell");
  const { I18nProvider, translate } = await import("@/lib/i18n");
  const t = (key: string) => translate(locale, key);
  try {
    render(<I18nProvider><LiveShell /></I18nProvider>);
    const warning = await screen.findByRole("status", { name: t("Slow local CPU model") });
    expect(warning).toHaveTextContent("10 tok/s");
    expect(warning).toHaveTextContent("15 tok/s");
    fireEvent.change(screen.getByPlaceholderText(t("Ask a question about the filing corpus")), { target: { value: "Revenue?" } });
    expect(screen.getByRole("button", { name: t("Send question") })).toBeEnabled();
    fireEvent.click(within(warning).getByRole("button", { name: t("Run limits") }));
    expect(await screen.findByLabelText(t("Maximum wall clock seconds"))).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: t("Close conversation settings") }));
    fireEvent.click(within(warning).getByRole("button", { name: t("Evidence") }));
    expect(await screen.findByLabelText(t("Maximum evidence characters"))).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: t("Close conversation settings") }));
    expect(loadConversations()[0].profile).toEqual(original);
    expect(fetchMock.mock.calls.every(([url]) => !String(url).includes("/review/stream"))).toBe(true);
    fireEvent.change(screen.getByLabelText(t("Answer engine")), { target: { value: "openai" } });
    expect(screen.queryByRole("status", { name: t("Slow local CPU model") })).toBeNull();
    fireEvent.change(screen.getByLabelText(t("Answer engine")), { target: { value: "local" } });
    expect(await screen.findByRole("status", { name: t("Slow local CPU model") })).toBeInTheDocument();
    local = { ...local, models: [{ ...model, cpu_performance: null }] };
    await act(async () => { window.dispatchEvent(new Event("online")); });
    await waitFor(() => expect(screen.queryByRole("status", { name: t("Slow local CPU model") })).toBeNull());
  } finally { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules(); window.localStorage.clear(); }
});
