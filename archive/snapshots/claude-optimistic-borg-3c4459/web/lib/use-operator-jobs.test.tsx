import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useOperatorJobs } from "./use-operator-jobs";

function Probe() {
  const { board } = useOperatorJobs(true);
  return <div>{board.active_count} active · {board.queued_count} queued · {board.jobs[0]?.message}</div>;
}

describe("operator job polling", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("loads the persistent unified job board", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      active_count: 1,
      queued_count: 2,
      jobs: [{
        job_id: "admin-1",
        domain: "corpus",
        kind: "backfill_embeddings",
        request: {},
        status: "running",
        stage: "embedding",
        current: 5,
        total: 10,
        detail_current: null,
        detail_total: null,
        message: "Embedded 5",
        error_code: null,
        result_refs: {},
        queue_position: null,
        can_cancel: true,
        can_retry: false,
        created_at: "2026-09-01T12:00:00Z",
        started_at: "2026-09-01T12:00:01Z",
        finished_at: null,
        updated_at: "2026-09-01T12:00:02Z",
      }],
    }), { status: 200, headers: { "content-type": "application/json" } })));

    render(<Probe />);

    await waitFor(() => expect(screen.getByText("1 active · 2 queued · Embedded 5")).toBeInTheDocument());
  });
});
