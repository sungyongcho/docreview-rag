import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CANNED_JOB, CANNED_SUITES } from "@/lib/canned";
import { I18nProvider } from "@/lib/i18n";
import type { OperatorJob } from "@/lib/types";
import { DEFAULT_PROFILE, DEFAULT_SESSION_PROFILE } from "@/lib/types";
import { MeasureWorkspace, type MeasureTab } from "./measure-workspace";

type StubHandler = (url: string, init?: RequestInit) => unknown;

function stubFetch(handler: StubHandler) {
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const custom = handler(String(input).replace(/\/?(\?|$)/, "$1"), init);
    const payload = String(input).replace(/\/?(\?|$)/, "$1").endsWith("/admin/evaluations/preparation") ? (custom && typeof custom === "object" && "state" in custom ? custom : { suite_id: JSON.parse(String(init?.body)).suite_id, kind: "builtin", verification_status: "pending_review", state: "ready", source_checks: [], blockers: [] }) : custom ?? {};
    return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Owns the tab like the shell does so tab-strip clicks work in tests. */
function Host({ live, ready = true, initialTab = "playground", onApplyProfile = vi.fn(), onRefreshJobs = vi.fn(), initialResultId = null, onOpenPreparation = vi.fn() }: { onOpenPreparation?: (stage: 1 | 2 | 3 | 4 | "setup") => void; initialResultId?: number | null; live: boolean; ready?: boolean; initialTab?: MeasureTab; onApplyProfile?: () => void; onRefreshJobs?: () => void }) {
  const [tab, setTab] = useState<MeasureTab>(initialTab);
  const [resultId, setResultId] = useState<number | null>(initialResultId);
  return (
    <MeasureWorkspace
      live={live}
      focusResultId={resultId}
      onResultSelectionChange={setResultId}
      ready={ready}
      onOpenPreparation={onOpenPreparation}
      profile={DEFAULT_PROFILE}
      onProfileChange={vi.fn()}
      onApplyProfile={onApplyProfile}
      onApplySnapshot={vi.fn()}
      jobBoard={{ jobs: [], active_count: 0, queued_count: 0 }}
      onRefreshJobs={onRefreshJobs}
      tab={tab}
      onTabChange={setTab}
    />
  );
}

describe("Measure workspace", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows canonical golden questions before a mutable draft exists", async () => {
    stubFetch((url) => {
      if (url.endsWith("/admin/evaluations/suites")) return CANNED_SUITES;
      if (url.endsWith("/admin/evaluations/runs")) return { jobs: [] };
      if (url.endsWith("/admin/golden/sec-en/revisions")) return [];
      if (url.endsWith("/admin/golden/sec-en/canonical")) return {
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
      if (url.endsWith("/admin/snapshots")) return [];
      return {};
    });
    render(<Host live />);

    expect(screen.getByText("Local operator")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Golden dataset" }));
    expect(await screen.findByText("Which policy is absent?")).toBeInTheDocument();
    expect(screen.getByText("retrieval.json")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "test-01" }));
    expect(screen.getByText("Read-only source")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save draft" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Question" })).toHaveAttribute("readonly");
    fireEvent.click(screen.getByRole("button", { name: "Question list" }));
    expect(screen.getAllByRole("button", { name: "Create draft" })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "View source JSON" }));
    expect(screen.getByRole("heading", { name: "Source JSON · read-only" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create draft" })).toBeEnabled();
    expect(screen.getByText("Hit, first rank, and reciprocal rank measure retrieval—not final-answer factuality.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Queue evaluation" })).not.toBeInTheDocument();
  });

  it("queues a quick evaluation from Runs and stays on the Results list", async () => {
    const onRefreshJobs = vi.fn();
    const queued = { ...CANNED_JOB, job_id: "queued-1", status: "queued", stage: "queued", message: "Waiting", result_id: null, result_ids: [], baseline_id: null };
    const fetchMock = stubFetch((url, init) => {
      if (url.endsWith("/admin/evaluations/suites")) return CANNED_SUITES;
      if (url.endsWith("/admin/evaluations/runs") && init?.method === "POST") return queued;
      if (url.endsWith("/admin/evaluations/runs")) return { jobs: [CANNED_JOB] };
      if (url.endsWith("/admin/snapshots")) return [];
      if (url.includes("/admin/golden/")) return [];
      return {};
    });
    render(<Host live initialTab="runs" onRefreshJobs={onRefreshJobs} />);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Result details" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "New evaluation" }));
    expect(screen.getByRole("dialog", { name: "New evaluation" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Queue evaluation" })).toBeEnabled());
    expect(screen.getByText("Retrieval profile · hybrid · ts_rank_cd · k 5")).toBeInTheDocument();
    const queue = screen.getByRole("button", { name: "Queue evaluation" });
    expect(queue).toBeEnabled();
    fireEvent.click(queue);

    await waitFor(() => {
      const posts = fetchMock.mock.calls.filter(([value, init]) => String(value).replace(/\/?(\?|$)/, "$1").endsWith("/admin/evaluations/runs") && (init as RequestInit | undefined)?.method === "POST");
      expect(posts).toHaveLength(1);
    });
    const [, init] = fetchMock.mock.calls.find(([value, init]) => String(value).replace(/\/?(\?|$)/, "$1").endsWith("/admin/evaluations/runs") && (init as RequestInit | undefined)?.method === "POST")!;
    const body = JSON.parse(String((init as RequestInit).body)) as Record<string, unknown>;
    expect(body.mode).toBe("quick");
    expect(body.suite_id).toBe("sec-en");
    expect(body.profile).toEqual(DEFAULT_PROFILE);
    await waitFor(() => expect(onRefreshJobs).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use selected set" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Evaluation runs" })).toBeInTheDocument();
    expect(await screen.findAllByText("Waiting")).toHaveLength(2);
  });

  it.each(["explicit", "default"] as const)("applies the selected result with its %s retrieval profile", async (profileSource) => {
    const onApplyProfile = vi.fn();
    const request = { ...CANNED_JOB.request };
    if (profileSource === "default") delete request.profile;
    else request.profile = { ...DEFAULT_PROFILE, k: 9 };
    stubFetch((url) => {
      if (url.endsWith("/admin/evaluations/suites")) return CANNED_SUITES;
      if (url.endsWith("/admin/evaluations/runs")) return { jobs: [{ ...CANNED_JOB, request }] };
      if (url.endsWith("/admin/snapshots")) return [];
      if (url.endsWith("/admin/evaluations/results/16")) return { result_id: 16, suite: "sec-ko", config: {}, metrics: { mrr: 0.8 }, cases: [], raw_artifact_path: "stored.json", created_at: CANNED_JOB.created_at };
      if (url.includes("/admin/golden/")) return [];
      return {};
    });
    render(<Host live initialTab="runs" onApplyProfile={onApplyProfile} />);

    fireEvent.click(await screen.findByRole("radio", { name: `Select ${CANNED_JOB.job_id}` }));
    fireEvent.click(await screen.findByRole("button", { name: "Use selected set" }));
    expect(onApplyProfile).toHaveBeenCalledWith(profileSource === "default" ? DEFAULT_PROFILE : { ...DEFAULT_PROFILE, k: 9 }, "sec-ko:16");
  });

  it("retains a focused stored result without an empty-list panel and returns to the list", async () => {
    stubFetch((url) => {
      if (url.endsWith("/admin/evaluations/runs")) return { jobs: [] };
      if (url.endsWith("/admin/evaluations/results/113")) return { result_id: 113, suite: "sec-ko", config: { k: 5 }, metrics: { mrr: 0.8 }, cases: [], created_at: "2026-09-06T12:00:00Z" };
      return [];
    });
    render(<Host live initialTab="runs" initialResultId={113} />);
    await waitFor(() => expect(screen.getByText("Recorded configuration")).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Result details" })).toBeInTheDocument();
    expect(screen.queryByText(/No evaluations yet/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New evaluation" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Golden dataset" }));
    fireEvent.click(screen.getByRole("button", { name: "Run evaluation" }));
    expect(screen.getByRole("heading", { name: "Result details" })).toBeVisible();
    expect(screen.queryByText(/No evaluations yet/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to evaluations" }));
    expect(await screen.findByText(/No evaluations yet/)).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Result details" })).not.toBeInTheDocument();
  });

  it("shows list loading and failure without claiming no evaluations exist", async () => {
    let rejectJobs!: (reason: Error) => void;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      if (String(input).replace(/\/?(\?|$)/, "$1").endsWith("/admin/evaluations/runs")) return new Promise((_resolve, reject) => { rejectJobs = reject; });
      return Promise.resolve(new Response("[]", { status: 200 }));
    }));
    render(<Host live initialTab="runs" />);
    expect(screen.getByText("Loading evaluations…")).toBeVisible();
    expect(screen.queryByText(/No evaluations yet/)).not.toBeInTheDocument();
    await act(async () => rejectJobs(new Error("Operator offline")));
    expect(await screen.findByText("Evaluations could not be loaded.")).toBeVisible();
    expect(screen.queryByText(/No evaluations yet/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
  });

  it("keeps the requested result identity visible when detail loading fails", async () => {
    let rejectResult!: (reason: Error) => void;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      if (String(input).replace(/\/?(\?|$)/, "$1").endsWith("/admin/evaluations/results/113")) return new Promise((_resolve, reject) => { rejectResult = reject; });
      return Promise.resolve(new Response(String(input).replace(/\/?(\?|$)/, "$1").endsWith("/admin/evaluations/runs") ? '{"jobs":[]}' : "[]", { status: 200 }));
    }));
    render(<Host live initialTab="runs" initialResultId={113} />);
    expect(screen.getByText("Loading evaluation result…")).toBeVisible();
    await act(async () => rejectResult(new Error("Result unavailable")));
    expect(await screen.findByText("Evaluation detail could not be loaded.")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Result details" })).toBeVisible();
    expect(screen.queryByText(/No evaluations yet/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back to evaluations" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
  });

  it("locks Playground and Runs in the public build without calling the administrator API", async () => {
    const fetchMock = stubFetch((url) => (url.endsWith("/snapshots") ? { snapshots: [] } : {}));
    render(<Host live={false} />);

    expect(screen.getByText("Read-only portfolio")).toBeInTheDocument();
    for (const label of ["Search trial", "Golden dataset", "Run evaluation", "Compare & snapshots"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Preview review" })).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(screen.getByRole("button", { name: "Run evaluation" }));
    expect(screen.getByRole("button", { name: "Explore evaluation settings" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Explore evaluation settings" }));
    expect(screen.getByText("Settings exploration only. These changes do not execute on the server or change recorded results.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Queue evaluation" })).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(within(screen.getByRole("group", { name: "Evaluation workflow" })).getByRole("button", { name: "Compare & snapshots" }));
    expect(screen.getByRole("button", { name: "Explore an example" })).toBeDisabled();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Explore an example" }));
    expect(screen.getByText("The recorded comparison pair is not available yet.")).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchMock.mock.calls.every(([value]) => !String(value).replace(/\/?(\?|$)/, "$1").includes("/admin/"))).toBe(true);
  });
});


describe("localized Measure metadata", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.localStorage.removeItem("docreview.locale");
  });

  it("translates run state and profile enums while preserving suite IDs and job messages", async () => {
    window.localStorage.setItem("docreview.locale", "ko");
    stubFetch((url) => {
      if (url.endsWith("/admin/evaluations/suites")) return CANNED_SUITES;
      if (url.endsWith("/admin/evaluations/runs")) return { jobs: [{ ...CANNED_JOB, status: "queued", message: "Original worker message" }] };
      return [];
    });
    render(<I18nProvider><Host live initialTab="runs" /></I18nProvider>);
    expect(await screen.findByText("Original worker message")).toBeInTheDocument();
    expect(screen.getAllByText("대기 중").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: /New evaluation|새 평가/ }));
    expect(screen.getByText(/하이브리드 검색 · ts_rank_cd · k 5/)).toBeInTheDocument();
    expect(screen.getByText("retrieval_ko.json · 빠른 평가")).toBeInTheDocument();
  });

  it("translates golden classifications without changing question text or tags", async () => {
    window.localStorage.setItem("docreview.locale", "ko");
    stubFetch((url) => {
      if (url.endsWith("/admin/evaluations/suites")) return CANNED_SUITES;
      if (url.endsWith("/admin/evaluations/runs")) return { jobs: [] };
      if (url.endsWith("/canonical")) return { suite_id: "sec-en", filename: "retrieval.json", sha256: "a".repeat(64), payload: [
        { id: "enum-test", question: "Keep this source question", category: "simple_lookup", facet: "policy", tags: ["raw-user-tag"], answers: [] },
      ] };
      return [];
    });
    render(<I18nProvider><Host live initialTab="golden" /></I18nProvider>);
    expect(await screen.findByText("Keep this source question")).toBeInTheDocument();
    expect(screen.getByText("단순 조회")).toBeInTheDocument();
    expect(screen.getByText("정책")).toBeInTheDocument();
    expect(screen.getByText("raw-user-tag")).toBeInTheDocument();
    expect(screen.getByText("retrieval.json")).toBeInTheDocument();
  });
});

describe("evaluation preparation boundaries", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); window.localStorage.clear(); });

  it("keeps unsaved draft edits when a dataset switch is declined and can recover incomplete JSON", async () => {
    const question = { id: "draft-01", question: "Original question", category: "simple_lookup", facet: "factual", answers: [], reference_answer: "Original answer" };
    const revision = { filename: "custom.json", revision_id: 7, suite_id: "sec-en", version: 1, status: "draft", payload: [question], sha256: "b".repeat(64), parent_id: null, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z" };
    const fetchMock = stubFetch((url) => {
      if (url.endsWith("/admin/evaluations/suites")) return CANNED_SUITES;
      if (url.endsWith("/admin/evaluations/runs")) return { jobs: [] };
      if (url.endsWith("/admin/golden/sec-en/revisions")) return [revision];
      if (url.endsWith("/canonical")) return { suite_id: "sec-en", filename: "retrieval.json", sha256: "a".repeat(64), payload: [question] };
      return [];
    });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<Host live initialTab="golden" />);
    await screen.findByRole("option", { name: "custom.json" });
    fireEvent.change(screen.getByLabelText("Golden suite"), { target: { value: "file:7" } });
    fireEvent.click(screen.getByRole("button", { name: "draft-01" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Question" }), { target: { value: "Unsaved question" } });
    fireEvent.click(screen.getByRole("button", { name: "Question list" }));
    expect(screen.getByRole("dialog", { name: "Unsaved question changes" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Continue editing" }));
    expect(screen.getByRole("textbox", { name: "Question" })).toHaveValue("Unsaved question");
    fireEvent.click(screen.getByText("Technical details and question JSON"));
    fireEvent.change(screen.getByLabelText("Single-case JSON"), { target: { value: "{" } });
    expect(screen.getByLabelText("Single-case JSON")).toHaveValue("{");
    expect(screen.getByRole("button", { name: "Save draft" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Single-case JSON"), { target: { value: JSON.stringify({ ...question, question: "Recovered question" }) } });
    expect(screen.getByRole("textbox", { name: "Question" })).toHaveValue("Recovered question");
    expect(fetchMock.mock.calls.every(([url, init]) => !init?.method || init.method === "GET" || String(url).replace(/\/?(\?|$)/, "$1").endsWith("/admin/evaluations/preparation"))).toBe(true);
  });

  it("saves an incomplete question before restoring the list", async () => {
    const question = { id: "draft-01", question: "Original question", category: null, expected_label: null, answers: [] };
    let revision = { filename: "custom.json", revision_id: 7, suite_id: "sec-en", version: 1, status: "draft", payload: [question], sha256: "b".repeat(64), completion: {} };
    const fetchMock = stubFetch((url, init) => {
      if (url.endsWith("/admin/evaluations/suites")) return CANNED_SUITES;
      if (url.endsWith("/admin/evaluations/runs")) return { jobs: [] };
      if (url.endsWith("/admin/golden/sec-en/revisions")) return [revision];
      if (url.endsWith("/canonical")) return { suite_id: "sec-en", filename: "retrieval.json", sha256: "a".repeat(64), payload: [] };
      if (init?.method === "PUT") {
        const request = JSON.parse(String(init.body));
        expect(request.expected_sha256).toBe("b".repeat(64));
        revision = { ...revision, payload: [request.case], sha256: "c".repeat(64) };
        return revision;
      }
      return [];
    });
    render(<Host live initialTab="golden" />);
    await screen.findByRole("option", { name: "custom.json" });
    fireEvent.change(screen.getByLabelText("Golden suite"), { target: { value: "file:7" } });
    fireEvent.click(screen.getByRole("button", { name: "draft-01" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Question" }), { target: { value: "Saved incomplete question" } });
    fireEvent.click(screen.getByRole("button", { name: "Question list" }));
    fireEvent.click(screen.getByRole("button", { name: "Save draft and leave" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText("Saved incomplete question")).toBeVisible();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);
  });

  it("opens evaluation preparation from the dataset without queuing a job", async () => {
    const fetchMock = stubFetch((url) => {
      if (url.endsWith("/admin/evaluations/suites")) return CANNED_SUITES;
      if (url.endsWith("/admin/evaluations/runs")) return { jobs: [] };
      return [];
    });
    render(<Host live initialTab="golden" />);
    fireEvent.click(screen.getByRole("button", { name: "Evaluate this dataset" }));
    expect(screen.getByRole("dialog", { name: "New evaluation" })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.every(([url, init]) => !init?.method || init.method === "GET" || String(url).replace(/\/?(\?|$)/, "$1").endsWith("/admin/evaluations/preparation"))).toBe(true);
  });

  it.each([false, true])("opens snapshot cards and preserves comparison behavior (live=%s)", async (live) => {
    const snapshots = [1, 2, 3].map((id) => ({ snapshot_id: id, label: `Snapshot ${id}`, status: "ready", public: true, corpus_fingerprint: String(id).repeat(64), profile: DEFAULT_PROFILE, golden_revision_id: id, eval_result: { result_id: id, suite: "sec-en", config: { k: 5, golden_provenance: { filename: "retrieval.json", dataset_id: "builtin:sec-en" } }, metrics: { mrr: 0.5 }, created_at: "2026-09-01T00:00:00Z" }, document_count: 29, created_at: "2026-09-01T00:00:00Z" }));
    stubFetch((url) => {
      if (url.includes("/snapshots/compare")) return { baseline_id: 1, candidate_id: 2, directly_comparable: false, warning: "Golden source hashes differ.", metrics: [{ name: "mrr", baseline: 0.5, candidate: 0.7, delta: null }], common_case_count: 0, cases: [] };
      if (url.endsWith("/admin/snapshots")) return snapshots;
      if (url.endsWith("/snapshots")) return { snapshots };
      return [];
    });
    render(<Host live={live} initialTab="snapshots" />);
    await screen.findAllByRole("option", { name: "Snapshot 1 · retrieval.json" });
    const card = screen.getByRole("button", { name: "Snapshot details: Snapshot 1" });
    card.focus();
    fireEvent.click(card);
    const drawer = screen.getByRole("dialog", { name: "Snapshot details" });
    expect(within(drawer).getByText("Corpus fingerprint", { exact: false })).toBeInTheDocument();
    expect(Boolean(within(drawer).queryByRole("button", { name: "Use for review" }))).toBe(live);
    fireEvent.keyDown(drawer, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Snapshot details" })).toBeNull();
    expect(card).toHaveFocus();
    fireEvent.click(card);
    fireEvent.click(within(screen.getByRole("dialog", { name: "Snapshot details" })).getAllByRole("button", { name: "Close" })[0]);
    expect(screen.queryByRole("dialog", { name: "Snapshot details" })).toBeNull();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Baseline"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Candidate"), { target: { value: "2" } });
    expect(screen.getAllByText("Corpus fingerprint")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Compare stored results" }));
    expect(await screen.findByText("Golden source hashes differ.")).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Candidate"), { target: { value: "3" } });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

it("opens diagnosis from an unready evaluation without submitting work", async () => {
  const onOpenPreparation = vi.fn();
  const fetchMock = stubFetch(url => {
    if (url.endsWith("/admin/evaluations/preparation")) return { suite_id: "sec-en", kind: "builtin", verification_status: "pending_review", state: "unavailable", source_checks: [], blockers: [], next_step: "setup" };
    if (url.endsWith("/admin/evaluations/suites")) return CANNED_SUITES;
    if (url.endsWith("/admin/evaluations/runs")) return { jobs: [] };
    return [];
  });
  render(<I18nProvider><Host live ready={false} initialTab="runs" onOpenPreparation={onOpenPreparation} /></I18nProvider>);
  await screen.findByRole("button", { name: /New evaluation|새 평가/ });
  fireEvent.click(screen.getByRole("button", { name: /New evaluation|새 평가/ }));
  const buttons = await screen.findAllByRole("button", { name: /Open preparation step|준비 단계 열기/ });
  fireEvent.click(buttons[0]);
  expect(onOpenPreparation).toHaveBeenCalledWith("setup");
  expect(fetchMock.mock.calls.every(([url, init]) => !init?.method || init.method === "GET" || String(url).replace(/\/?(\?|$)/, "$1").endsWith("/admin/evaluations/preparation"))).toBe(true);
  cleanup();
});

describe("evaluation run refetch keyed on evaluation jobs", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("does not refetch evaluation runs when only a corpus job reports progress", async () => {
    const fetchMock = stubFetch((url) => {
      if (url.endsWith("/admin/evaluations/suites")) return CANNED_SUITES;
      if (url.endsWith("/admin/evaluations/runs")) return { jobs: [] };
      return {};
    });
    const corpusJob: OperatorJob = { job_id: "corpus-progress", domain: "corpus", kind: "ingest_manifest", request: {}, status: "running", stage: "parse", current: 1, total: 9, detail_current: null, detail_total: null, message: "Parsing", error_code: null, result_refs: {}, queue_position: null, can_cancel: true, can_retry: false, created_at: "2026-09-01T12:00:00Z", started_at: "2026-09-01T12:00:01Z", finished_at: null, updated_at: "2026-09-01T12:00:02Z" };
    const board = (rows: OperatorJob[]) => ({ jobs: rows, active_count: rows.length, queued_count: 0 });
    const view = (rows: OperatorJob[]) => (
      <MeasureWorkspace live ready onOpenPreparation={vi.fn()} profile={DEFAULT_PROFILE} onProfileChange={vi.fn()} onApplyProfile={vi.fn()} onApplySnapshot={vi.fn()} jobBoard={board(rows)} onRefreshJobs={vi.fn()} tab="runs" onTabChange={vi.fn()} />
    );
    const { rerender } = render(view([corpusJob]));
    const runsCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).replace(/\/?(\?|$)/, "$1").endsWith("/admin/evaluations/runs")).length;
    await waitFor(() => expect(runsCalls()).toBeGreaterThan(0));
    await act(async () => undefined);
    const before = runsCalls();
    rerender(view([{ ...corpusJob, current: 2, updated_at: "2026-09-01T12:00:03Z" }]));
    rerender(view([{ ...corpusJob, current: 3, updated_at: "2026-09-01T12:00:04Z" }]));
    await act(async () => undefined);
    expect(runsCalls()).toBe(before);
    rerender(view([corpusJob, { ...corpusJob, job_id: "eval-1", domain: "evaluation", kind: "quick" }]));
    await waitFor(() => expect(runsCalls()).toBe(before + 1));
  });
});

/** Keep management out of the ordered workflow while retaining accessible active states. */
it("keeps presets in management without a separate defaults tab", async () => {
  stubFetch(url => url.endsWith("/suites") ? CANNED_SUITES : url.endsWith("/runs") ? { jobs: [] } : []);
  render(<Host live initialTab="presets" />);
  const workflow = screen.getByRole("group", { name: "Evaluation workflow" });
  const management = screen.getByRole("group", { name: "Manage" });
  expect(within(workflow).getAllByRole("button")).toHaveLength(4);
  expect(workflow.querySelectorAll(".measure-step-chip")).toHaveLength(4);
  expect(management.querySelector(".measure-step-chip")).toBeNull();
  expect(document.querySelector('[data-help="measure.presets.manage"]')).not.toBeNull();
  expect(within(management).getByRole("button", { name: "Presets" })).toHaveAttribute("aria-pressed", "true");
  expect(within(management).queryByRole("button", { name: "Defaults" })).toBeNull();
});

/** Preserve browser presets in the management group without exposing DEV defaults. */
it("keeps the presets tab available in production without DEV defaults", () => {
  cleanup();
  stubFetch(url => url.endsWith("/suites") ? CANNED_SUITES : []);
  try {
    render(<Host live={false} initialTab="presets" />);
    const management = screen.getByRole("group", { name: "Manage" });
    expect(within(management).getByRole("button", { name: "Presets" })).toHaveAttribute("aria-pressed", "true");
    expect(within(management).queryByRole("button", { name: "Defaults" })).toBeNull();
    expect(within(screen.getByRole("group", { name: "Evaluation workflow" })).getAllByRole("button")).toHaveLength(4);
  } finally { cleanup(); vi.unstubAllGlobals(); }
});

it("creates a named empty JSON dataset beside the selector without a publication step", async () => {
  const created = { filename: "my-eval.json", revision_id: 77, suite_id: "sec-en", version: 1, status: "draft", payload: [], sha256: "b".repeat(64), parent_id: null, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z" };
  const fetchMock = stubFetch((url) => {
    if (url.endsWith("/admin/evaluations/suites")) return CANNED_SUITES;
    if (url.endsWith("/admin/evaluations/runs")) return { jobs: [] };
    if (url.endsWith("/canonical")) return { suite_id: "sec-en", filename: "retrieval.json", sha256: "a".repeat(64), payload: [] };
    if (url.endsWith("/drafts")) return created;
    return [];
  });
  render(<Host live initialTab="golden" />);
  await screen.findByRole("option", { name: /· retrieval\.json \(Built-in\)$/ });
  expect(screen.queryByLabelText("Golden revision")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Create draft" }));
  fireEvent.change(screen.getByLabelText("JSON filename"), { target: { value: "my-eval.json" } });
  fireEvent.change(screen.getByLabelText("Starting content"), { target: { value: "empty" } });
  fireEvent.click(screen.getByRole("button", { name: "Create file" }));
  await screen.findByRole("option", { name: "my-eval.json" });
  expect(screen.getByLabelText("Golden suite")).toHaveValue("file:77");
  const request = fetchMock.mock.calls.find(([url]) => String(url).replace(/\/?(\?|$)/, "$1").endsWith("/drafts"));
  expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({ filename: "my-eval.json", empty: true, parent_id: null });
  expect(screen.queryByRole("button", { name: "Publish JSON" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Add question" }));
  expect(screen.getByRole("textbox", { name: "Question" })).toHaveValue("");
});

it.each([true, false])("shows snapshot progress and a truthful terminal button state (success=%s)", async (success) => {
  cleanup(); window.localStorage.clear();
  let finish!: (response: Response) => void;
  const fetchMock = stubFetch(url => url.endsWith("/admin/evaluations/results/113") ? { result_id: 113, suite: "sec-en", config: {}, metrics: {}, cases: [], created_at: "2026-09-08T00:00:00Z" } : []);
  const ordinary = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => String(input).replace(/\/?(\?|$)/, "$1").endsWith("/admin/snapshots") && init?.method === "POST" ? new Promise<Response>(resolve => { finish = resolve; }) : ordinary(input, init));
  render(<Host live initialTab="runs" initialResultId={113} />);
  const input = await screen.findByLabelText("Snapshot label");
  fireEvent.change(input, { target: { value: "testing" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Save result as snapshot" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Save result as snapshot" }));
  const pending = screen.getByRole("button", { name: "Saving snapshot…" });
  expect(pending).toBeDisabled();
  expect(pending).toHaveAttribute("aria-busy", "true");
  fireEvent.click(pending);
  expect(fetchMock.mock.calls.filter(([url, init]) => String(url).replace(/\/?(\?|$)/, "$1").endsWith("/admin/snapshots") && init?.method === "POST")).toHaveLength(1);
  await act(async () => finish(new Response(JSON.stringify(success ? { snapshot_id: 1, label: "testing", status: "ready", public: false, document_count: 7, profile: {}, eval_result: { result_id: 113, suite: "sec-en", config: {}, metrics: {} } } : { error: { code: "snapshot_failed", message: "Snapshot failed." } }), { status: success ? 200 : 500, headers: { "content-type": "application/json" } })));
  if (success) {
    expect(screen.getByRole("button", { name: "Snapshot saved" })).toHaveClass("saved");
    expect(input).toHaveValue("");
  } else {
    expect(screen.getByRole("button", { name: "Retry snapshot save" })).toBeEnabled();
    expect(input).toHaveValue("testing");
    expect(screen.queryByText("Snapshot saved")).not.toBeInTheDocument();
  }
});

it("opens the existing snapshot from an evaluated result without another save request", async () => {
  cleanup(); window.localStorage.clear();
  const stored = { snapshot_id: 12, label: "Known search state", status: "ready", public: false, corpus_fingerprint: "a".repeat(64), profile: { retrieval_profile: { ...DEFAULT_PROFILE, k: 7 } }, golden_revision_id: null, eval_result: { result_id: 113, suite: "sec-en", config: { retrieval_profile: { ...DEFAULT_PROFILE, k: 7 } }, metrics: {}, created_at: "2026-09-08T00:00:00Z" }, document_count: 7, created_at: "2026-09-08T00:00:00Z" };
  const fetchMock = stubFetch(url => {
    if (url.endsWith("/admin/snapshots")) return [stored];
    if (url.endsWith("/admin/evaluations/suites")) return CANNED_SUITES;
    if (url.endsWith("/admin/evaluations/results/113")) return { ...stored.eval_result, cases: [] };
    return [];
  });
  render(<Host live initialTab="runs" initialResultId={113} />);
  fireEvent.click(await screen.findByRole("button", { name: "View saved snapshot" }));
  expect(screen.getByRole("heading", { name: "Snapshot management" })).toBeVisible();
  const row = document.getElementById("managed-snapshot-12")!;
  expect(row).toHaveFocus();
  fireEvent.click(row);
  expect(within(screen.getByRole("dialog", { name: "Snapshot details" })).getByText("retrieval.json")).toBeVisible();
  fireEvent.keyDown(screen.getByRole("dialog", { name: "Snapshot details" }), { key: "Escape" });
  expect(within(row).getByText(/k 7/)).toBeVisible();
  expect(screen.getByText("Stored in this database. Execution data reset deletes these snapshots.")).toBeVisible();
  expect(fetchMock.mock.calls.filter(([url, init]) => String(url).replace(/\/?(\?|$)/, "$1").endsWith("/admin/snapshots") && init?.method === "POST")).toHaveLength(0);
});

it("filters comparisons by dataset and clears both selections when the file changes", async () => {
  cleanup(); window.localStorage.clear();
  const jobs = [11, 12, 13].map((id) => ({ ...CANNED_JOB, job_id: `job-${id}`, status: "succeeded", result_id: id, result_ids: [id], request: { ...CANNED_JOB.request, suite_id: id === 13 ? "dart-ko" : "dart-en" }, created_at: `2026-09-08T12:00:${id}Z`, result_summaries: [{ result_id: id, created_at: `2026-09-08T12:00:${id}Z`, config: { golden_provenance: { filename: id === 13 ? "dart_retrieval_ko.json" : "dart_retrieval.json", dataset_id: id === 13 ? "builtin:dart-ko" : "builtin:dart-en", golden_sha256: id === 12 ? "b".repeat(64) : "a".repeat(64) }, retrieval_profile: DEFAULT_PROFILE } }] }));
  stubFetch(url => url.endsWith("/admin/evaluations/suites") ? CANNED_SUITES : url.endsWith("/admin/evaluations/runs") ? { jobs } : []);
  render(<Host live initialTab="compare" />);
  const dataset = await screen.findByLabelText("Evaluation dataset");
  await screen.findByRole("option", { name: /· dart_retrieval\.json \(Built-in\)$/ });
  expect(screen.getByLabelText("Baseline")).toBeDisabled();
  fireEvent.change(dataset, { target: { value: "builtin:dart-en" } });
  await waitFor(() => expect(screen.getByLabelText("Baseline").querySelectorAll("option")).toHaveLength(3));
  expect(screen.getByLabelText("Baseline")).not.toHaveTextContent("#11");
  fireEvent.change(screen.getByLabelText("Baseline"), { target: { value: "11" } });
  fireEvent.change(screen.getByLabelText("Candidate"), { target: { value: "12" } });
  expect(screen.getByText("Dataset contents changed between these evaluations. Choose runs with matching dataset contents.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Compare selected results" })).toBeDisabled();
  fireEvent.change(dataset, { target: { value: "builtin:dart-ko" } });
  expect(screen.getByLabelText("Baseline")).toHaveValue("");
  expect(screen.getByLabelText("Candidate")).toHaveValue("");
  expect(screen.getByText("This dataset needs two completed evaluations to compare.")).toBeVisible();
});

it("filters run history by file and status, searches settings, and sorts without changing identities", async () => {
  cleanup(); window.localStorage.clear();
  const jobs = [
    { ...CANNED_JOB, job_id: "older", request: { ...CANNED_JOB.request, suite_id: "dart-en" }, status: "succeeded", created_at: "2026-09-08T10:00:00Z" },
    { ...CANNED_JOB, job_id: "newer", request: { ...CANNED_JOB.request, suite_id: "dart-en" }, status: "queued", created_at: "2026-09-08T12:00:00Z" },
    { ...CANNED_JOB, job_id: "korean", request: { ...CANNED_JOB.request, suite_id: "dart-ko" }, status: "succeeded", created_at: "2026-09-08T11:00:00Z" },
  ];
  stubFetch(url => url.endsWith("/admin/evaluations/suites") ? CANNED_SUITES : url.endsWith("/admin/evaluations/runs") ? { jobs } : []);
  render(<Host live initialTab="runs" />);
  await screen.findByText("dart_retrieval_ko.json · quick");
  fireEvent.change(screen.getByLabelText("Dataset file"), { target: { value: "builtin:dart-en" } });
  expect(document.querySelectorAll(".evaluation-run-list .job-row")).toHaveLength(2);
  fireEvent.change(screen.getByLabelText("Status"), { target: { value: "queued" } });
  expect(document.querySelectorAll(".evaluation-run-list .job-row")).toHaveLength(1);
  fireEvent.change(screen.getByLabelText("Status"), { target: { value: "all" } });
  fireEvent.change(screen.getByLabelText("Sort by"), { target: { value: "oldest" } });
  expect(document.querySelector(".evaluation-run-list time")).toHaveAttribute("dateTime", "2026-09-08T10:00:00Z");
  fireEvent.change(screen.getByLabelText("Dataset file"), { target: { value: "all" } });
  fireEvent.change(screen.getByPlaceholderText("Search filename or settings"), { target: { value: "_ko.json" } });
  expect(document.querySelectorAll(".evaluation-run-list .job-row")).toHaveLength(1);
  expect(document.querySelector(".evaluation-run-list")).toHaveTextContent("dart_retrieval_ko.json");
});

it("filters saved snapshots using recorded dataset filenames", async () => {
  cleanup(); window.localStorage.clear();
  const snapshots = ["dart-en", "dart-ko"].map((suite, index) => ({ snapshot_id: index + 1, label: `Saved ${suite}`, status: "ready", public: false, corpus_fingerprint: "a".repeat(64), profile: DEFAULT_PROFILE, golden_revision_id: null, eval_result: { result_id: index + 1, suite, config: {}, metrics: {}, created_at: "2026-09-08T10:00:00Z" }, document_count: 7, created_at: "2026-09-08T10:00:00Z" }));
  stubFetch(url => url.endsWith("/admin/evaluations/suites") ? CANNED_SUITES : url.endsWith("/admin/snapshots") ? snapshots : []);
  render(<Host live initialTab="snapshots" />);
  await screen.findByText("Saved dart-ko");
  fireEvent.change(screen.getByLabelText("Dataset file"), { target: { value: "builtin:dart-en" } });
  expect(document.querySelectorAll(".snapshot-card")).toHaveLength(1);
  expect(document.querySelector(".snapshot-card")).toHaveTextContent("Saved dart-en");
  fireEvent.click(screen.getByRole("button", { name: "Snapshot details: Saved dart-en" }));
  expect(within(screen.getByRole("dialog", { name: "Snapshot details" })).getByText("dart_retrieval.json")).toBeVisible();
  fireEvent.keyDown(screen.getByRole("dialog", { name: "Snapshot details" }), { key: "Escape" });
  fireEvent.change(screen.getByPlaceholderText("Search filename or snapshot name"), { target: { value: "missing" } });
  expect(screen.getByText("No snapshots match these filters.")).toBeVisible();
});


it("saves evaluation defaults explicitly without changing current inputs or chat defaults", async () => {
  cleanup(); window.localStorage.clear();
  const { loadExperimentDefaults, loadDefaultProfile, saveDefaultProfile } = await import("@/lib/storage");
  saveDefaultProfile({ ...DEFAULT_SESSION_PROFILE, retrieval_preset: "accuracy" });
  stubFetch(url => url.endsWith("/suites") ? CANNED_SUITES : url.endsWith("/runs") ? { jobs: [] } : []);
  render(<Host live initialTab="runs" />);
  fireEvent.click(screen.getByRole("button", { name: "New evaluation" }));
  await within(screen.getByRole("dialog", { name: "New evaluation" })).findByRole("option", { name: /· dart_retrieval_ko\.json \(Built-in\)$/ });
  fireEvent.change(screen.getByLabelText("Golden suite"), { target: { value: "dart-ko" } });
  fireEvent.click(screen.getByText("Advanced evaluation options"));
  fireEvent.change(screen.getByLabelText("Run mode"), { target: { value: "matrix" } });
  expect(loadExperimentDefaults().suite_id).toBe("sec-en");
  fireEvent.click(screen.getByRole("button", { name: "Save as evaluation defaults" }));
  expect(loadExperimentDefaults()).toEqual({ suite_id: "dart-ko", golden_revision_id: null, mode: "matrix" });
  expect(loadDefaultProfile().retrieval_preset).toBe("accuracy");
  fireEvent.click(screen.getByRole("button", { name: "Reset evaluation defaults" }));
  expect(loadExperimentDefaults().suite_id).toBe("sec-en");
  expect(screen.getByLabelText("Golden suite")).toHaveValue("dart-ko");
  expect(screen.getByLabelText("Run mode")).toHaveValue("matrix");
});

it("keeps verdicts consistent and explains missing source evidence before sending a save", async () => {
  cleanup(); window.localStorage.clear();
  const question = { id: "draft-01", question: "Question?", category: "absent", facet: "factual", answers: [], reference_answer: "NOT_IN_DOCS", expected_label: "NOT_IN_DOCS", note: "Review this", tags: [], curation_status: "user-authored", approval_status: "pending-author-approval", human_verified: false };
  const revision = { filename: "test.json", revision_id: 7, suite_id: "sec-en", version: 1, status: "draft", payload: [question], sha256: "b".repeat(64), parent_id: null, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z" };
  const fetchMock = stubFetch(url => url.endsWith("/suites") ? CANNED_SUITES : url.endsWith("/sec-en/revisions") ? [revision] : url.endsWith("/canonical") ? { filename: "retrieval.json", suite_id: "sec-en", payload: [], sha256: "a".repeat(64) } : []);
  render(<Host live initialTab="golden" />);
  await screen.findByRole("option", { name: "test.json" });
  fireEvent.change(screen.getByLabelText("Golden suite"), { target: { value: "file:7" } });
  fireEvent.click(screen.getByRole("button", { name: "draft-01" }));
  fireEvent.click(screen.getByRole("button", { name: "Evidence available" }));
  expect(screen.getByRole("button", { name: "Evidence available" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("textbox", { name: "Reference answer" })).toHaveValue("");
  expect(screen.getByRole("button", { name: "Save draft" })).toBeEnabled();
  expect(screen.getByText("Choose a document chunk to fill its exact original-source coordinates.")).toBeVisible();
  expect(screen.getByRole("textbox", { name: "Question" })).toHaveValue("Question?");
});

it("marks a dataset file that no longer exists as deleted in the run filter and detail", async () => {
  const gone = { golden_provenance: { dataset_id: "file:4242", filename: "gone.json", golden_revision_id: 4242, golden_sha256: "b".repeat(64) } };
  stubFetch((url) => {
    if (url.endsWith("/admin/evaluations/suites")) return CANNED_SUITES;
    if (url.endsWith("/admin/evaluations/runs")) return { jobs: [{ ...CANNED_JOB, request: { ...CANNED_JOB.request, golden_revision_id: 4242 }, result_summaries: [{ result_id: 16, suite: "sec-en", config: gone, metrics: {}, created_at: CANNED_JOB.created_at }] }] };
    if (url.endsWith("/admin/snapshots")) return [];
    if (url.includes("/admin/golden/")) return [];
    return {};
  });
  render(<Host live initialTab="runs" />);
  await screen.findByRole("option", { name: "gone.json (deleted)" });
  expect(screen.queryByRole("option", { name: "retrieval.json (deleted)" })).toBeNull();
});
