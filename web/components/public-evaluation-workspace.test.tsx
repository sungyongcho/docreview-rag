import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { PublishedSnapshot } from "@/lib/types";
import { PublicEvaluationWorkspace } from "./public-evaluation-workspace";

const snapshots: PublishedSnapshot[] = [1, 2].map(id => ({
  snapshot_id: id, label: `Published run ${id}`, status: "ready", public: true,
  corpus_fingerprint: "a".repeat(64), profile: {}, golden_revision_id: 3,
  document_count: 1, created_at: "2026-09-01T00:00:00Z",
  eval_result: { result_id: id + 10, suite: "sec-en", config: { golden_sha256: "b".repeat(64) },
    metrics: { mrr: 0.625 }, created_at: "2026-09-01T00:00:00Z" },
}));
const question = { id: "case-01", question: "What changed in revenue?", category: "simple_lookup",
  facet: "factual", tags: [], expected_label: "SUPPORTED", reference_answer: "Recorded reference answer",
  answers: [{ doc_id: "NVDA-FY2024", source_sha256: "c".repeat(64), start_char: 10, end_char: 25 }] };
const dataset = { snapshot_id: 1, suite: "sec-en", golden_sha256: "b".repeat(64), revision_id: 3,
  version: 2, total: 26, offset: 0, limit: 25, cases: [question] };
const evaluation = { snapshot_id: 1, eval_result_id: 11, suite: "sec-en", created_at: "2026-09-01T00:00:00Z",
  config: { k: 5, mode: "hybrid" }, metrics: { mrr: 0.625 }, total: 26, offset: 0, limit: 25,
  cases: [{ case_id: "case-01", question: question.question, latency_ms: 12.5,
    first_relevant_rank: 2, recall_at_k: 0.5, hit_at_k: 1, reciprocal_rank: 0.5 }] };
const comparison = { comparable: true, warning: null,
  metrics: [{ name: "mrr", baseline: 0.5, candidate: 0.625, delta: 0.125 }],
  cases: [{ case_id: "case-01", baseline_question: question.question, candidate_question: question.question,
    baseline_rank: 3, candidate_rank: 2, transition: "stable_hit", rank_delta: -1 }] };
let requests: { url: URL; method: string }[];
let failure = false;

beforeEach(() => {
  localStorage.clear(); requests = []; failure = false;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    requests.push({ url, method: init?.method ?? "GET" });
    if (failure) return new Response(JSON.stringify({ error: { message: "Unavailable" } }), { status: 409 });
    const body = url.pathname.endsWith("/dataset") ? dataset : url.pathname.endsWith("/evaluation") ? evaluation : comparison;
    return new Response(JSON.stringify(body), { status: 200 });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

/** Wait for debounced server requests without coupling tests to the timer implementation. */
async function requested(path: string, params: Record<string, string> = {}) {
  await waitFor(() => expect(requests.some(({ url, method }) => method === "GET" && url.pathname.endsWith(path)
    && Object.entries(params).every(([key, value]) => url.searchParams.get(key) === value))).toBe(true));
}

it("reads exact expected evidence and sends dataset search, sort and page parameters as GET", async () => {
  render(<PublicEvaluationWorkspace tab="golden" snapshots={snapshots} loading={false} error={false} onRefresh={vi.fn()} />);
  await requested("/public/snapshots/1/dataset", { offset: "0", limit: "25" });
  fireEvent.click(await screen.findByRole("button", { name: "case-01" }));
  expect(screen.getByText("Recorded reference answer")).toBeVisible();
  expect(screen.getByText(/NVDA-FY2024/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /Create draft/ }));
  fireEvent.click(screen.getByRole("button", { name: /Evaluate this dataset/ }));
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await requested("/public/snapshots/1/dataset", { offset: "25" });
  fireEvent.change(screen.getByLabelText("Search"), { target: { value: "revenue" } });
  fireEvent.change(screen.getByLabelText("Sort by"), { target: { value: "question" } });
  await requested("/public/snapshots/1/dataset", { offset: "0", query: "revenue", sort: "question" });
  expect(requests.every(row => row.method === "GET")).toBe(true);
});

it("reads evaluation pages while settings remain a browser-only experiment and keep recorded scores", async () => {
  render(<PublicEvaluationWorkspace tab="runs" snapshots={snapshots} loading={false} error={false} onRefresh={vi.fn()} />);
  await requested("/public/snapshots/1/evaluation");
  expect(await screen.findByText("0.625")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Explore evaluation settings" }));
  fireEvent.change(screen.getByLabelText("Evaluation mode"), { target: { value: "matrix" } });
  fireEvent.change(screen.getByLabelText("Chunk targets (tokens)"), { target: { value: "512 1024" } });
  fireEvent.change(screen.getByLabelText("k"), { target: { value: "9" } });
  fireEvent.click(screen.getByText("Request preview · not submitted"));
  expect(screen.getByText(/"target_tokens":/)).toHaveTextContent('"k": 9');
  expect(screen.getByText("0.625")).toBeVisible();
  const recorded = screen.getByRole("heading", { name: "Recorded configuration" }).parentElement!;
  expect(within(recorded).getByText("5")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Save exploration in this browser" }));
  expect(screen.getByText("Exploration saved in this browser. No evaluation was run.")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /Queue evaluation/ }));
  fireEvent.click(screen.getByRole("button", { name: /Save result as snapshot/ }));
  expect(requests).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await requested("/public/snapshots/1/evaluation", { offset: "25" });
  fireEvent.change(screen.getByLabelText("Search"), { target: { value: "case-01" } });
  await requested("/public/snapshots/1/evaluation", { offset: "0", query: "case-01" });
  expect(requests.every(row => row.method === "GET")).toBe(true);
});

it("compares only on demand and reuses the same stored result without another request", async () => {
  render(<PublicEvaluationWorkspace tab="compare" snapshots={snapshots} loading={false} error={false} onRefresh={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("Baseline"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("Candidate"), { target: { value: "2" } });
  expect(requests).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Compare selected results" }));
  await requested("/snapshots/compare", { baseline_id: "1", candidate_id: "2" });
  expect(await screen.findByText("Recorded results")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Compare selected results" }));
  expect(requests).toHaveLength(1);
  fireEvent.change(screen.getByLabelText("Search ID or question"), { target: { value: "revenue" } });
  fireEvent.click(screen.getByText(/case-01 ·/));
  expect(screen.getByText(/3 → 2/)).toBeVisible();
  expect(requests).toHaveLength(1);
});

it("opens an explicitly labeled interactive example without fetching or treating it as real evidence", () => {
  render(<PublicEvaluationWorkspace tab="compare" snapshots={[]} loading={false} error={false} onRefresh={vi.fn()} />);
  expect(screen.queryByText("Example baseline")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Explore an example" }));
  expect(screen.getAllByText("Illustrative example only — not an evaluation result.").length).toBeGreaterThan(0);
  fireEvent.change(screen.getByLabelText("Baseline"), { target: { value: "candidate" } });
  expect(screen.getByRole("table")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Return to published results" }));
  expect(screen.queryByRole("table")).toBeNull();
  expect(requests).toHaveLength(0);
});

it("does not replace failed published evidence with an illustrative example", async () => {
  failure = true;
  render(<PublicEvaluationWorkspace tab="golden" snapshots={snapshots} loading={false} error={false} onRefresh={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("could not be verified or loaded");
  expect(screen.queryByText("Recorded reference answer")).toBeNull();
  expect(screen.queryByText(/Illustrative example only/)).toBeNull();
});


it("restores the versioned browser experiment before runtime permissions arrive", async () => {
  const { browserStorage, configureBrowserStorage } = await import("@/lib/storage");
  const { DEFAULT_PROFILE } = await import("@/lib/types");
  configureBrowserStorage("prod");
  browserStorage().setItem("docreview:public-evaluation-experiment:v1", JSON.stringify({ mode: "matrix", targets: "512 1024", profile: DEFAULT_PROFILE }));
  configureBrowserStorage(undefined);
  render(<PublicEvaluationWorkspace tab="runs" snapshots={[]} loading={false} error={false} onRefresh={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Explore evaluation settings" }));
  expect(screen.getByLabelText("Evaluation mode")).toHaveValue("matrix");
  expect(screen.getByLabelText("Chunk targets (tokens)")).toHaveValue("512 1024");
  expect(requests).toHaveLength(0);
});
