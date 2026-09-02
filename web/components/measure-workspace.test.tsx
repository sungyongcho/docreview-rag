import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CANNED_JOB, CANNED_SUITES } from "@/lib/canned";
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
      onOpenSettings={vi.fn()}
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
    fireEvent.click(screen.getByRole("button", { name: "Golden Tests" }));
    expect(await screen.findByText("Which policy is absent?")).toBeInTheDocument();
    expect(screen.getByText("retrieval.json")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "test-01" }));
    expect(screen.getByText("Read-only source")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save case" })).toBeDisabled();
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

    expect(await screen.findByRole("heading", { name: "New run" })).toBeInTheDocument();
    expect(screen.getByText("Uses the current review's retrieval profile. Change presets in Settings › Review session.")).toBeInTheDocument();
    expect(screen.getByText("Retrieval profile · hybrid · ts_rank_cd · k 5")).toBeInTheDocument();
    const queue = screen.getByRole("button", { name: "Queue evaluation" });
    expect(queue).toHaveAttribute("aria-disabled", "false");
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
    expect(screen.getByRole("button", { name: "Use selected set" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "New run" })).toBeInTheDocument();
    expect(await screen.findByText("Waiting")).toBeInTheDocument();
  });

  it("applies the selected succeeded result to the review profile", async () => {
    const onApplyProfile = vi.fn();
    stubFetch((url) => {
      if (url.endsWith("/admin/evaluations/suites")) return CANNED_SUITES;
      if (url.endsWith("/admin/evaluations/runs")) return { jobs: [CANNED_JOB] };
      if (url.endsWith("/admin/snapshots")) return [];
      if (url.includes("/admin/golden/")) return [];
      return {};
    });
    render(<Host live initialTab="runs" onApplyProfile={onApplyProfile} />);

    fireEvent.click(await screen.findByRole("radio", { name: `Select ${CANNED_JOB.job_id}` }));
    fireEvent.click(screen.getByRole("button", { name: "Use selected set" }));
    expect(onApplyProfile).toHaveBeenCalledWith(CANNED_JOB.request.profile, "sec-ko:16");
  });

  it("locks Playground and Runs in the public build without calling the administrator API", async () => {
    const fetchMock = stubFetch((url) => (url.endsWith("/snapshots") ? { snapshots: [] } : {}));
    render(<Host live={false} />);

    expect(screen.getByText("Read-only portfolio")).toBeInTheDocument();
    for (const label of ["Playground", "Golden Tests", "Runs", "Compare", "Snapshots"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByText("Playground runs on the local operator build.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Runs" }));
    expect(screen.getByText("Runs happen on the local operator build.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Snapshots" }));
    expect(screen.getByRole("heading", { name: "Published snapshots" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));
    expect(screen.getByRole("heading", { name: "Case changes" })).toBeInTheDocument();

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchMock.mock.calls.every(([value]) => !String(value).includes("/admin/"))).toBe(true);
  });
});
