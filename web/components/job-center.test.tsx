import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { OperatorJob, OperatorJobStatus } from "@/lib/types";
import { JobCenter, jobErrorSummary } from "./job-center";

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
