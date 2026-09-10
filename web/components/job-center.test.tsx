import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { OperatorJob, OperatorJobStatus } from "@/lib/types";
import { I18nProvider } from "@/lib/i18n";
import { JobCenter, JobProgress, jobErrorSummary, elapsedLabel } from "./job-center";

function job(overrides: Partial<OperatorJob> = {}): OperatorJob {
  return {
    job_id: "job-1",
    domain: "corpus",
    kind: "ingest_manifest",
    request: {},
    status: "failed" as OperatorJobStatus,
    stage: "ingest",
    current: 3,
    total: 9,
    detail_current: null,
    detail_total: null,
    message: "ValueError: manifest entry 4 has no file",
    error_code: "valueerror",
    result_refs: {},
    queue_position: null,
    can_cancel: false,
    can_retry: true,
    created_at: "2026-09-02T10:00:00Z",
    started_at: "2026-09-02T10:00:01Z",
    finished_at: "2026-09-02T10:00:41Z",
    updated_at: "2026-09-02T10:00:41Z",
    ...overrides,
  };
}

function renderCenter(jobs: OperatorJob[]) {
  render(
    <JobCenter
      board={{ jobs, active_count: 0, queued_count: 0 }}
      loading={false}
      onRefresh={vi.fn()}
      onRetry={vi.fn()}
      onCancel={vi.fn()}
      onOpenResult={vi.fn()}
    />,
  );
}

afterEach(cleanup);

describe("recorded overall and stage progress", () => {
  it("shows separate overall, stage and reported item bars with both elapsed times", () => {
    render(<JobProgress job={job({ status: "succeeded", stage: "done", progress_stage: "cleanup", current: 4, total: 4, overall_current: 100, overall_total: 100, stage_index: 5, stage_count: 5, stage_started_at: "2026-09-02T10:00:31Z", detail_current: 2, detail_total: 3 })} />);
    expect(screen.getByRole("progressbar", { name: "Overall progress" })).toHaveAttribute("value", "100");
    expect(screen.queryByRole("progressbar", { name: "Current stage" })).not.toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Current item" })).toHaveAttribute("value", "2");
    expect(screen.getByText("2 items / 3 items · 67%" )).toBeInTheDocument();
    expect(screen.getByText("Stage 5 / 5 · 100%")).toBeInTheDocument();
    expect(screen.getByText("Current stage · cleanup")).toBeInTheDocument();
    expect(screen.getByText("Elapsed: 40s")).toBeInTheDocument();
    expect(screen.getByText(/Stage elapsed: 10s/)).toBeInTheDocument();
  });

  it.each(["schema", "documents", "bm25"])("renders the running %s stage without a fabricated zero percent", (stage) => {
    render(<JobProgress job={job({ stage, status: "running", current: 0, total: 1, overall_current: 45, overall_total: 100, finished_at: null })} />);
    expect(screen.queryByRole("progressbar", { name: "Current stage" })).not.toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Overall progress" })).toHaveAttribute("value", "45");
    expect(screen.queryByText(/0 \/ 1/)).not.toBeInTheDocument();
    expect(screen.queryByText("Current item")).not.toBeInTheDocument();
  });

  it.each([[753664, 3603839, "753.7 KB / 3.6 MB · 21%"], [20, 10, "20 B / 10 B · 100%"], [0, 0, "0 B / 0 B"], [1000000000, 2000000000, "1 GB / 2 GB · 50%"]])("formats current item progress for %s of %s", (current, total, label) => {
    render(<JobProgress job={job({ kind: "acquire_dart", stage: "issuer_index", detail_current: Number(current), detail_total: Number(total) })} />);
    expect(screen.getByText(String(label))).toBeInTheDocument();
  });

  it("leaves overall progress unknown for legacy records", () => {
    render(<JobProgress job={job()} />);
    expect(screen.getByText("Progress not reported")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar", { name: "Overall progress" })).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar", { name: "Current stage" })).not.toBeInTheDocument();
  });
});

describe("jobErrorSummary", () => {
  it("explains the fixed codes and wraps a bare exception name", () => {
    expect(jobErrorSummary("process_restarted")).toContain("restart");
    expect(jobErrorSummary("worker_error")).toContain("worker failed");
    expect(jobErrorSummary("postcondition_failed")).toContain("did not satisfy");
    expect(jobErrorSummary("cancelled")).toBe("Cancelled by an operator.");
    // A lowercased exception class is the common case and reads as noise on its own.
    expect(jobErrorSummary("httpstatuserror")).toBe("Stopped by an unexpected httpstatuserror raised inside the job.");
    expect(jobErrorSummary(null)).toBeNull();
  });
});

describe("JobCenter", () => {
  it("keeps the raw code searchable and adds a sentence beside it", () => {
    renderCenter([job()]);
    fireEvent.click(screen.getByRole("button", { name: /Ingest manifest/ }));

    expect(screen.getByText("valueerror")).toBeInTheDocument();
    expect(screen.getByText(/Stopped by an unexpected valueerror/)).toBeInTheDocument();
    // The message appears in both the list row and the detail pane.
    expect(screen.getAllByText("ValueError: manifest entry 4 has no file").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Retry as new job" })).toBeInTheDocument();
  });

  it("shows a status line while job activity is stale", () => {
    render(<JobCenter board={{ jobs: [job()], active_count: 0, queued_count: 0 }} loading={false} stale onRefresh={vi.fn()} onRetry={vi.fn()} onCancel={vi.fn()} onOpenResult={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Job activity may be out of date. Retrying…");
    cleanup();
    render(<JobCenter board={{ jobs: [], active_count: 0, queued_count: 0 }} loading={false} stale onRefresh={vi.fn()} onRetry={vi.fn()} onCancel={vi.fn()} onOpenResult={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Job activity could not be loaded. Retrying…");
    expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled();
  });

  it("carries the help hook so the Jobs tab can be explained", () => {
    // The topic lives on its own screen, because the Job Center is not on the pipeline tab.
    renderCenter([job()]);
    expect(document.querySelector('[data-help="build.jobs.center"]')).not.toBeNull();
  });

  it("says why an interrupted job is not resumed, and offers no sentence when nothing failed", () => {
    renderCenter([job({ status: "interrupted", error_code: "process_restarted", message: "Interrupted by application restart; retry explicitly." })]);
    fireEvent.click(screen.getByRole("button", { name: /Ingest manifest/ }));
    expect(screen.getByText(/Nothing is resumed automatically/)).toBeInTheDocument();
    cleanup();

    renderCenter([job({ status: "succeeded", error_code: null, message: "Ingested 9 document(s)", can_retry: false })]);
    fireEvent.click(screen.getByRole("button", { name: /Ingest manifest/ }));
    expect(document.querySelector(".job-error")).toBeNull();
  });
});


describe("localized job presentation", () => {
  afterEach(() => window.localStorage.removeItem("docreview.locale"));
  it("keeps CSS status and server diagnostics intact in Korean", () => {
    window.localStorage.setItem("docreview.locale", "ko");
    render(<I18nProvider><JobCenter
      board={{ jobs: [job()], active_count: 0, queued_count: 0 }}
      loading={false} onRefresh={vi.fn()} onRetry={vi.fn()}
      onCancel={vi.fn()} onOpenResult={vi.fn()}
    /></I18nProvider>);
    fireEvent.click(screen.getByRole("button", { name: /매니페스트/ }));
    expect(document.querySelectorAll(".job-status.failed")).toHaveLength(2);
    expect(screen.getAllByText("ValueError: manifest entry 4 has no file").length).toBeGreaterThan(0);
    expect(screen.getByText("valueerror")).toBeInTheDocument();
    expect(screen.getByText("작업 중 예기치 않은 valueerror 오류가 발생해 중단되었습니다.")).toBeInTheDocument();
    expect(screen.getByText("40초")).toBeInTheDocument();
  });

  it("localizes elapsed time without changing English callers", () => {
    expect(elapsedLabel(job())).toBe("40s");
    expect(elapsedLabel(job(), "ko")).toBe("40초");
    expect(elapsedLabel(job({ started_at: null }), "ko")).toBe("시작 전");
  });
});


describe("explicit job navigation", () => {
  it("renders no detail until selection and retains selection after returning to the list", () => {
    renderCenter([job()]);
    expect(document.querySelector(".job-detail")).toBeNull();
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
    const row = screen.getByRole("button", { name: /Ingest manifest/ });
    expect(row).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(row);
    expect(document.querySelector(".job-detail")).not.toBeNull();
    expect(screen.getByRole("separator", { name: "Resize job panels" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to jobs" }));
    expect(document.querySelector(".job-detail")).toBeNull();
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
    expect(row).toHaveAttribute("aria-pressed", "true");
  });

  it("explains an excluded selection instead of silently selecting the first remaining job", () => {
    renderCenter([job(), job({ job_id: "job-2", domain: "evaluation", kind: "quick", status: "succeeded", error_code: null })]);
    fireEvent.click(screen.getByRole("button", { name: /Ingest manifest/ }));
    fireEvent.click(screen.getByRole("button", { name: "evaluation" }));
    expect(screen.getByRole("heading", { name: "Job outside current filters" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Quick evaluation/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("gates retry, cancel and result actions on both permissions and real terminal state", () => {
    renderCenter([job({ status: "running", can_retry: true, can_cancel: true, result_refs: { result_id: 7 } })]);
    fireEvent.click(screen.getByRole("button", { name: /Ingest manifest/ }));
    expect(screen.queryByRole("button", { name: "Retry as new job" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "View result #7" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel job" })).toBeInTheDocument();
  });
});


it("selects a notification's job and clears filters without requiring a row click", () => {
  const props = { board: { jobs: [job(), job({ job_id: "job-2", status: "succeeded" })], active_count: 0, queued_count: 0 }, loading: false, onRefresh: vi.fn(), onRetry: vi.fn(), onCancel: vi.fn(), onOpenResult: vi.fn() };
  const { rerender } = render(<JobCenter {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "queued" }));
  rerender(<JobCenter {...props} focusJobId="job-1" />);
  expect(screen.getByRole("button", { name: "Retry as new job" })).toBeVisible();
  expect(screen.getByRole("button", { name: /Ingest manifest.*failed/ })).toHaveAttribute("aria-pressed", "true");
});


describe("download speed", () => {
  it.each(["acquire_edgar", "acquire_dart"])("measures %s samples and clears stale item speeds", (kind) => {
    vi.useFakeTimers();
    try {
      const initial = job({ kind, status: "running", stage: "download", current: 0, total: 2, message: "first", detail_current: 1000, detail_total: null, updated_at: "2026-09-02T10:00:01Z" });
      const { rerender } = render(<JobProgress job={initial} />);
      expect(screen.queryByText(/Download speed/)).not.toBeInTheDocument();
      const next = { ...initial, detail_current: 101000, updated_at: "2026-09-02T10:00:03Z" };
      rerender(<JobProgress job={next} />);
      expect(screen.getByText("Download speed: 50 KB/s")).toBeInTheDocument();
      rerender(<JobProgress job={{ ...next }} />);
      expect(screen.getByText("Download speed: 50 KB/s")).toBeInTheDocument();
      rerender(<JobProgress job={{ ...next, detail_current: 2101000, updated_at: "2026-09-02T10:00:04Z" }} />);
      expect(screen.getByText("Download speed: 2 MB/s")).toBeInTheDocument();
      act(() => { vi.advanceTimersByTime(5000); });
      expect(screen.getByText("Download speed: 0 KB/s")).toBeInTheDocument();
      rerender(<JobProgress job={{ ...next, current: 1, message: "second", updated_at: "2026-09-02T10:00:05Z" }} />);
      expect(screen.queryByText(/Download speed/)).not.toBeInTheDocument();
      rerender(<JobProgress job={{ ...next, current: 1, message: "second", detail_current: 201000, updated_at: "2026-09-02T10:00:06Z" }} />);
      expect(screen.getByText("Download speed: 100 KB/s")).toBeInTheDocument();
      rerender(<JobProgress job={{ ...next, current: 1, message: "second", detail_current: 0, updated_at: "2026-09-02T10:00:07Z" }} />);
      expect(screen.queryByText(/Download speed/)).not.toBeInTheDocument();
      rerender(<JobProgress job={{ ...next, status: "succeeded" }} />);
      expect(screen.queryByText(/Download speed/)).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows issuer-index download speed in Korean", () => {
    const initial = job({ kind: "acquire_dart", status: "running", stage: "issuer_index", total: null, detail_current: 1000, updated_at: "2026-09-02T10:00:01Z" });
    const { rerender } = render(<I18nProvider><JobProgress job={initial} /></I18nProvider>);
    rerender(<I18nProvider><JobProgress job={{ ...initial, detail_current: 201000, updated_at: "2026-09-02T10:00:03Z" }} /></I18nProvider>);
    expect(screen.getByText("다운로드 속도: 100 KB/s")).toBeInTheDocument();
  });

  it("does not treat non-download item counts as bytes", () => {
    render(<JobProgress job={job({ status: "running", detail_current: 20, detail_total: 50 })} />);
    expect(screen.queryByText(/Download speed/)).not.toBeInTheDocument();
  });
});

it("distinguishes the company directory from a company-year original download", () => {
  const initial = job({ kind: "acquire_dart", status: "running", stage: "issuer_index", total: null, message: "corp codes", detail_current: 100, detail_total: 1000 });
  const { rerender } = render(<JobProgress job={initial} />);
  expect(screen.getByText("Current stage · DART company directory download")).toBeInTheDocument();
  expect(screen.getByText("All DART companies · company code directory")).toBeInTheDocument();
  expect(screen.queryByText("corp codes")).not.toBeInTheDocument();
  rerender(<JobProgress job={{ ...initial, stage: "select", message: "Samsung (005930) FY2024", detail_current: null, detail_total: null }} />);
  expect(screen.getByText("Current stage · DART annual report lookup")).toBeInTheDocument();
  rerender(<JobProgress job={{ ...initial, stage: "download", message: "Samsung (005930) FY2024" }} />);
  expect(screen.getByText("Current stage · Original report download")).toBeInTheDocument();
  expect(screen.getByText("Current item · Samsung (005930) FY2024")).toBeInTheDocument();
  expect(screen.queryByText("Samsung (005930) FY2024", { exact: true })).not.toBeInTheDocument();
});


it("omits null request options while preserving false, zero, and the recorded request", () => {
  const request = Object.freeze({ years: [2022, 2023, 2024], manifest: null, selection_id: null, expected_documents: null, enabled: false, max_results: 0 });
  renderCenter([job({ request })]);
  fireEvent.click(document.querySelector(".job-list-row")!);
  const options = within(screen.getByRole("heading", { name: "Request options" }).closest("section")!);
  expect(options.queryByText("manifest")).toBeNull();
  expect(options.queryByText("selection id")).toBeNull();
  expect(options.queryByText("expected documents")).toBeNull();
  expect(options.getByText("false", { selector: "code" })).toBeVisible();
  expect(options.getByText("0", { selector: "code" })).toBeVisible();
  expect(options.getByText(/2022/, { selector: "code" })).toBeVisible();
  expect(request.manifest).toBeNull();
});

it("shows the empty-options message when every recorded option is null", () => {
  renderCenter([job({ request: { manifest: null } })]);
  fireEvent.click(document.querySelector(".job-list-row")!);
  expect(screen.getByText("No request options were recorded.")).toBeVisible();
});
