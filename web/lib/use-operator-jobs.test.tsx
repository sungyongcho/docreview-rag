import { act, cleanup, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { pollDelay, useOperatorJobs } from "./use-operator-jobs";
import type { OperatorJobBoard } from "./types";

const notifications = vi.hoisted(() => ({ notify: vi.fn(), dismissNotice: vi.fn() }));
vi.mock("@/components/notifications", () => ({ useNotifications: () => notifications }));

const RUNNING_BOARD: OperatorJobBoard = {
  active_count: 1, queued_count: 0,
  jobs: [{ job_id: "job-1", domain: "corpus", kind: "rebuild_bm25", request: {}, status: "running", stage: "indexing", current: 1, total: 2, detail_current: null, detail_total: null, message: "Indexing", error_code: null, result_refs: {}, queue_position: null, can_cancel: true, can_retry: false, created_at: "2026-09-05T12:00:00Z", started_at: "2026-09-05T12:00:01Z", finished_at: null, updated_at: "2026-09-05T12:00:02Z" }],
};

function response(board: OperatorJobBoard) {
  return new Response(JSON.stringify(board), { headers: { "content-type": "application/json" } });
}

function Probe() {
  const { board } = useOperatorJobs(true);
  return <div>{board.active_count} active · {board.queued_count} queued · {board.jobs[0]?.message}</div>;
}

describe("operator job polling", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
    notifications.notify.mockClear();
  });

  it("computes poll delays with floors and a capped failure ladder", () => {
    expect([0, 1, 2, 3, 4].map((failures) => pollDelay(failures, true, true))).toEqual([1_000, 2_000, 4_000, 8_000, 10_000]);
    expect(pollDelay(0, false, true)).toBe(5_000);
    expect(pollDelay(1, false, true)).toBe(5_000);
    expect(pollDelay(3, false, true)).toBe(8_000);
    expect(pollDelay(4, true, false)).toBe(15_000);
  });

  it("backs off 2/4/8/10 s after failed polls, keeps the last board, marks it stale and never toasts", async () => {
    vi.useFakeTimers();
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      reads += 1;
      if (reads > 1 && reads <= 5) throw new TypeError("Failed to fetch");
      return response(RUNNING_BOARD);
    }));
    const { result } = renderHook(() => useOperatorJobs(true));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.board).toEqual(RUNNING_BOARD);
    expect(result.current.stale).toBe(false);

    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    expect(reads).toBe(2);
    expect(result.current.stale).toBe(true);
    expect(result.current.board).toEqual(RUNNING_BOARD);
    await act(async () => { await vi.advanceTimersByTimeAsync(1_900); });
    expect(reads).toBe(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    expect(reads).toBe(3);
    await act(async () => { await vi.advanceTimersByTimeAsync(4_000); });
    expect(reads).toBe(4);
    await act(async () => { await vi.advanceTimersByTimeAsync(8_000); });
    expect(reads).toBe(5);
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(reads).toBe(6);
    expect(result.current.stale).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    expect(reads).toBe(7);
    expect(notifications.notify).not.toHaveBeenCalled();
  });

  it("toasts a manual refresh failure once under jobs-refresh and keeps automatic failures silent", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    const { result } = renderHook(() => useOperatorJobs(true));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(notifications.notify).not.toHaveBeenCalled();
    expect(result.current.stale).toBe(true);
    expect(result.current.loading).toBe(false);

    await act(async () => { await result.current.refresh(true); });
    expect(notifications.notify).toHaveBeenCalledTimes(1);
    expect(notifications.notify).toHaveBeenCalledWith("Failed to fetch", "error", "jobs-refresh", undefined, { event: "jobs-refresh-error", detail: undefined });
  });

  it("keeps board identity when a poll returns an identical board", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(async () => response(RUNNING_BOARD)));
    const { result } = renderHook(() => useOperatorJobs(true));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const first = result.current.board;
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000); });
    expect(result.current.board).toBe(first);
  });

  it("starts paused without admin reads or mutation actions and polls when resumed", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn(async () => response(RUNNING_BOARD));
    vi.stubGlobal("fetch", fetch);
    const { result, rerender } = renderHook(({ active }) => useOperatorJobs(true, undefined, active), { initialProps: { active: false } });
    await act(async () => {
      await result.current.refresh();
      await result.current.retry("job-1");
      await result.current.cancel("job-1");
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(fetch).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(false);
    rerender({ active: true });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.board).toEqual(RUNNING_BOARD);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("preserves a paused board and ignores a late aborted poll until a fresh resume", async () => {
    vi.useFakeTimers();
    let release!: (response: Response) => void;
    let signal: AbortSignal | null | undefined;
    let reads = 0;
    const pending = new Promise<Response>((resolve) => { release = resolve; });
    const completed: OperatorJobBoard = { ...RUNNING_BOARD, active_count: 0, jobs: [{ ...RUNNING_BOARD.jobs[0], status: "succeeded", message: "Finished", current: 2, can_cancel: false }] };
    const fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      reads += 1;
      if (reads === 2) { signal = init?.signal; return pending; }
      return response(reads === 1 ? RUNNING_BOARD : completed);
    });
    const onTerminal = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const { result, rerender } = renderHook(({ active, enabled }) => useOperatorJobs(enabled, onTerminal, active), { initialProps: { active: true, enabled: true } });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const retained = result.current.board;
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    expect(reads).toBe(2);
    rerender({ active: false, enabled: false });
    expect(signal?.aborted).toBe(true);
    await act(async () => {
      release(response(completed));
      await result.current.refresh();
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(result.current.board).toBe(retained);
    expect(result.current.loading).toBe(false);
    expect(reads).toBe(2);
    expect(onTerminal).not.toHaveBeenCalled();
    rerender({ active: true, enabled: true });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.board).toEqual(completed);
    expect(reads).toBe(3);
    expect(onTerminal).toHaveBeenCalledTimes(1);
  });

  it("coalesces manual refreshes and discards polling results after unmount", async () => {
    let release!: (response: Response) => void;
    let signal: AbortSignal | null | undefined;
    const fetch = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      signal = init?.signal;
      return new Promise<Response>((resolve) => { release = resolve; });
    });
    vi.stubGlobal("fetch", fetch);
    const onTerminal = vi.fn();
    const { result, unmount } = renderHook(() => useOperatorJobs(true, onTerminal));
    await act(async () => { await result.current.refresh(); });
    expect(fetch).toHaveBeenCalledTimes(1);
    unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => release(response(RUNNING_BOARD)));
    expect(onTerminal).not.toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledTimes(1);
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
