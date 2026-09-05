import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { OperatorJob, OperatorJobStatus } from "@/lib/types";
import { I18nProvider } from "@/lib/i18n";
import { JobCenter, jobErrorSummary, elapsedLabel } from "./job-center";

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
