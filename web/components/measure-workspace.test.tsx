import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CANNED_JOB, CANNED_SUITES } from "@/lib/canned";
import { I18nProvider } from "@/lib/i18n";
import { DEFAULT_PROFILE } from "@/lib/types";
import { MeasureWorkspace, type MeasureTab } from "./measure-workspace";

type StubHandler = (url: string, init?: RequestInit) => unknown;

function stubFetch(handler: StubHandler) {
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const payload = handler(String(input), init) ?? {};
    return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Owns the tab like the shell does so tab-strip clicks work in tests. */
function Host({ live, ready = true, initialTab = "playground", onApplyProfile = vi.fn(), onRefreshJobs = vi.fn() }: { live: boolean; ready?: boolean; initialTab?: MeasureTab; onApplyProfile?: () => void; onRefreshJobs?: () => void }) {
  const [tab, setTab] = useState<MeasureTab>(initialTab);
  return (
    <MeasureWorkspace
      live={live}
      ready={ready}
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
    fireEvent.click(screen.getByRole("button", { name: "2. Golden dataset" }));
    expect(await screen.findByText("Which policy is absent?")).toBeInTheDocument();
    expect(screen.getByText("retrieval.json")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "test-01" }));
    expect(screen.getByText("Read-only source")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save case" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Question" })).not.toBeInTheDocument();
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
      const posts = fetchMock.mock.calls.filter(([value, init]) => String(value).endsWith("/admin/evaluations/runs") && (init as RequestInit | undefined)?.method === "POST");
      expect(posts).toHaveLength(1);
    });
    const [, init] = fetchMock.mock.calls.find(([value, init]) => String(value).endsWith("/admin/evaluations/runs") && (init as RequestInit | undefined)?.method === "POST")!;
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

  it("applies the selected succeeded result to the review profile", async () => {
    const onApplyProfile = vi.fn();
    stubFetch((url) => {
      if (url.endsWith("/admin/evaluations/suites")) return CANNED_SUITES;
      if (url.endsWith("/admin/evaluations/runs")) return { jobs: [CANNED_JOB] };
      if (url.endsWith("/admin/snapshots")) return [];
      if (url.endsWith("/admin/evaluations/results/16")) return { result_id: 16, suite: "sec-ko", config: {}, metrics: { mrr: 0.8 }, cases: [], raw_artifact_path: "stored.json", created_at: CANNED_JOB.created_at };
      if (url.includes("/admin/golden/")) return [];
      return {};
    });
    render(<Host live initialTab="runs" onApplyProfile={onApplyProfile} />);

    fireEvent.click(await screen.findByRole("radio", { name: `Select ${CANNED_JOB.job_id}` }));
    fireEvent.click(await screen.findByRole("button", { name: "Use selected set" }));
    expect(onApplyProfile).toHaveBeenCalledWith(CANNED_JOB.request.profile, "sec-ko:16");
  });

  it("locks Playground and Runs in the public build without calling the administrator API", async () => {
    const fetchMock = stubFetch((url) => (url.endsWith("/snapshots") ? { snapshots: [] } : {}));
    render(<Host live={false} />);

    expect(screen.getByText("Read-only portfolio")).toBeInTheDocument();
    for (const label of ["1. Search trial", "2. Golden dataset", "3. Run evaluation", "4. Compare and save"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByText("Playground runs on the local operator build.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "3. Run evaluation" }));
    expect(screen.getByText("Runs happen on the local operator build.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Snapshots" }));
    expect(screen.getByRole("heading", { name: "Published snapshots" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Compare results" }));
    expect(screen.getByText("No comparison loaded yet. Queue a run, then click Compare on a succeeded result that has a baseline.")).toBeInTheDocument();
    expect(screen.getByText("Illustrative example only — not an evaluation result.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Case changes", level: 2 })).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchMock.mock.calls.every(([value]) => !String(value).includes("/admin/"))).toBe(true);
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
    expect(screen.getByText("대기 중")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /New evaluation|새 평가/ }));
    expect(screen.getByText(/하이브리드 검색 · ts_rank_cd · k 5/)).toBeInTheDocument();
    expect(screen.getByText(`${CANNED_JOB.request.suite_id} · 빠른 평가`)).toBeInTheDocument();
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
    const revision = { revision_id: 7, suite_id: "sec-en", version: 1, status: "draft", payload: [question], sha256: "b".repeat(64), parent_id: null, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z" };
    const fetchMock = stubFetch((url) => {
      if (url.endsWith("/admin/evaluations/suites")) return CANNED_SUITES;
      if (url.endsWith("/admin/evaluations/runs")) return { jobs: [] };
      if (url.endsWith("/admin/golden/sec-en/revisions")) return [revision];
      if (url.endsWith("/canonical")) return { suite_id: "sec-en", filename: "retrieval.json", sha256: "a".repeat(64), payload: [question] };
      return [];
    });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<Host live initialTab="golden" />);
    await screen.findByRole("option", { name: "v1 · draft" });
    fireEvent.change(screen.getByLabelText("Golden revision"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "draft-01" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Question" }), { target: { value: "Unsaved question" } });
    expect(screen.getByRole("button", { name: "Validate" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Golden suite"), { target: { value: "sec-ko" } });
    expect(window.confirm).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Golden suite")).toHaveValue("sec-en");
    expect(screen.getByRole("textbox", { name: "Question" })).toHaveValue("Unsaved question");
    fireEvent.click(screen.getByText("JSON and changes"));
    fireEvent.change(screen.getByLabelText("Single-case JSON"), { target: { value: "{" } });
    expect(screen.getByLabelText("Single-case JSON")).toHaveValue("{");
    expect(screen.getByRole("button", { name: "Save case" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Single-case JSON"), { target: { value: JSON.stringify({ ...question, question: "Recovered question" }) } });
    expect(screen.getByRole("textbox", { name: "Question" })).toHaveValue("Recovered question");
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  });

  it("opens evaluation preparation from the dataset without queuing a job", async () => {
    const fetchMock = stubFetch((url) => {
      if (url.endsWith("/admin/evaluations/suites")) return CANNED_SUITES;
      if (url.endsWith("/admin/evaluations/runs")) return { jobs: [] };
      return [];
    });
    render(<Host live initialTab="golden" />);
    fireEvent.click(screen.getByRole("button", { name: "Prepare evaluation with this dataset" }));
    expect(screen.getByRole("dialog", { name: "New evaluation" })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  });

  it("shows snapshot provenance and clears old metrics when either selection changes", async () => {
    const snapshots = [1, 2, 3].map((id) => ({ snapshot_id: id, label: `Snapshot ${id}`, status: "ready", public: true, corpus_fingerprint: String(id).repeat(64), profile: DEFAULT_PROFILE, golden_revision_id: id, eval_result: { result_id: id, suite: "sec-en", config: { k: 5 }, metrics: { mrr: 0.5 }, created_at: "2026-09-01T00:00:00Z" }, document_count: 29, created_at: "2026-09-01T00:00:00Z" }));
    stubFetch((url) => {
      if (url.includes("/snapshots/compare")) return { baseline_id: 1, candidate_id: 2, directly_comparable: false, warning: "Golden source hashes differ.", metrics: [{ name: "mrr", baseline: 0.5, candidate: 0.7, delta: null }], common_case_count: 0, cases: [] };
      if (url.endsWith("/snapshots")) return { snapshots };
      return [];
    });
    render(<Host live={false} initialTab="snapshots" />);
    await screen.findAllByRole("option", { name: "Snapshot 1 · sec-en" });
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
